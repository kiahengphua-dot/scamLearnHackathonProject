import json
import random

from flask import Blueprint, current_app, g, jsonify, request

from app.ai.replay_narrative import generate_replay_narrative
from app.ai.roleplay import get_next_message
from app.db import fetch_generated_scenario, fetch_session_messages, get_db
from app.engine.achievements import check_and_award_achievements, get_achievements
from app.engine.replay import build_replay
from app.engine.skill_profile import (
    get_profile,
    overall_proficiency,
    recommend_scenario,
    strongest_category,
    update_profile_for_session,
    weakest_category,
)
from app.engine.state_machine import InvalidActionError, apply_decision, create_session_state, next_scenario_message
from app.engine.outcome import OUTCOME_SUMMARIES
from app.extensions import limiter
from app.identity import get_or_create_user
from app.scenarios.loader import get_scenario, list_scenario_summaries, load_all_scenarios

api_bp = Blueprint("api", __name__, url_prefix="/api")

VALID_MODES = {"train", "test"}


@api_bp.before_request
def _ensure_identity():
    get_or_create_user()


def _error(message, status=400):
    return jsonify({"error": message}), status


def _resolve_scenario(scenario_id, db, user_id):
    """Static demo scenarios first, then a user's own artifact-generated
    scenarios. Raises KeyError if neither has it (including if a generated
    scenario belongs to a different user — same isolation guarantee as
    session ownership)."""
    try:
        return get_scenario(scenario_id)
    except KeyError:
        pass
    row = fetch_generated_scenario(db, scenario_id, user_id)
    if row is None:
        raise KeyError(scenario_id)
    return json.loads(row["scenario_json"])


@api_bp.route("/scenarios", methods=["GET"])
def scenarios():
    mode = request.args.get("mode", "train")
    if mode not in VALID_MODES:
        return _error("mode must be 'train' or 'test'")

    if mode == "train":
        return jsonify({"scenarios": list_scenario_summaries()})

    # Test mode never reveals which scenario or what it's about up front.
    return jsonify({"message": "In Test Mode, scenarios are selected for you and not previewed."})


@api_bp.route("/sessions", methods=["POST"])
def start_session():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    scenario_id = body.get("scenario_id")

    if mode not in VALID_MODES:
        return _error("mode must be 'train' or 'test'")

    db = get_db()

    if mode == "train":
        # Train mode may play either a static demo scenario or one of the
        # user's own artifact-generated scenarios (app/artifacts/).
        if not scenario_id:
            return _error("A valid scenario_id is required for Training Mode")
        try:
            scenario = _resolve_scenario(scenario_id, db, g.user_id)
        except KeyError:
            return _error("A valid scenario_id is required for Training Mode")
    else:
        # Test mode always draws from the curated static set — a
        # user's own generated scenario would defeat the blind-test
        # purpose, since they already know what artifact they submitted.
        all_scenarios = load_all_scenarios()
        scenario = all_scenarios[scenario_id] if scenario_id in all_scenarios else random.choice(list(all_scenarios.values()))

    state = create_session_state(scenario)
    cursor = db.execute(
        "INSERT INTO sessions (user_id, scenario_id, mode, state_json, reasoning_score, risk_score) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (g.user_id, scenario["id"], mode, json.dumps(state), state["reasoning_score"], scenario["base_risk"]),
    )
    session_id = cursor.lastrowid

    initial_message = next_scenario_message(scenario, state)
    db.execute(
        "INSERT INTO messages (session_id, turn_number, speaker, content) VALUES (?, 0, 'scenario', ?)",
        (session_id, initial_message),
    )
    db.commit()

    # Deliberately excluded from every in-progress response, in either mode:
    # classification, reasoning_score, scoring_rules, success/failure
    # conditions, expected_red_flags. These only appear once the session
    # completes (see submit_decision below).
    response = {
        "session_id": session_id,
        "mode": mode,
        "stage": state["stage"],
        "message": initial_message,
        "status": state["status"],
    }
    if mode == "train":
        response["title"] = scenario["title"]
        response["category"] = scenario["category"]
        response["difficulty"] = scenario["difficulty"]
        response["target_learning_objectives"] = scenario["target_learning_objectives"]

    return jsonify(response), 201


def _load_session_or_404(session_id):
    db = get_db()
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None or row["user_id"] != g.user_id:
        return None
    return row


@api_bp.route("/sessions/<int:session_id>/decisions", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_DECISIONS"])
def submit_decision(session_id):
    row = _load_session_or_404(session_id)
    if row is None:
        return _error("Session not found", 404)
    if row["status"] == "completed":
        return _error("This session has already ended", 409)

    body = request.get_json(silent=True) or {}
    action_type = (body.get("action_type") or "").upper()
    text = (body.get("text") or "")[: current_app.config["MAX_USER_MESSAGE_LENGTH"]]

    db = get_db()
    scenario = _resolve_scenario(row["scenario_id"], db, g.user_id)
    state = json.loads(row["state_json"])

    turn_number_for_this_decision = state["turn_count"]

    try:
        state = apply_decision(scenario, state, action_type, text)
    except InvalidActionError as e:
        return _error(str(e), 400)

    db.execute(
        "INSERT INTO messages (session_id, turn_number, speaker, content) VALUES (?, ?, 'user', ?)",
        (session_id, turn_number_for_this_decision, text or f"[{action_type}]"),
    )

    last_turn_log = state["applied_scoring_log"][-1] if state["applied_scoring_log"] else {"applied_rules": []}
    for rule in last_turn_log["applied_rules"]:
        db.execute(
            "INSERT INTO decisions (session_id, turn_number, action_type, score_delta, category, explanation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, turn_number_for_this_decision, action_type, rule["delta"], rule["category"], rule["explanation"]),
        )

    # In-progress responses are deliberately minimal: no reasoning_score, no
    # applied_rules, no classification, no scoring internals. All of that is
    # backend-owned and only surfaces once the scenario resolves below.
    response = {
        "session_id": session_id,
        "stage": state["stage"],
        "status": state["status"],
    }

    if state["status"] == "completed":
        db.execute(
            "UPDATE sessions SET state_json = ?, status = 'completed', reasoning_score = ?, "
            "outcome = ?, completed_at = datetime('now') WHERE id = ?",
            (json.dumps(state), state["reasoning_score"], state["outcome"], session_id),
        )
        db.commit()
        update_profile_for_session(db, g.user_id, state["applied_scoring_log"])
        newly_earned = check_and_award_achievements(db, g.user_id, scenario, state)

        response["reasoning_score"] = state["reasoning_score"]
        response["outcome"] = state["outcome"]
        response["classification"] = scenario["classification"]
        response["outcome_summary"] = OUTCOME_SUMMARIES[state["outcome"]]
        response["scenario_title"] = scenario["title"]
        response["expected_red_flags"] = scenario["expected_red_flags"]
        response["safe_verification_actions"] = scenario["safe_verification_actions"]
        response["newly_earned_achievements"] = newly_earned
    else:
        # Claude never decides whether/when the scenario ends or what stage
        # comes next — apply_decision() already settled that above. Claude
        # only narrates whichever stage the backend already moved to.
        history_rows = fetch_session_messages(db, session_id, limit=current_app.config["MAX_HISTORY_MESSAGES"])[1:]
        result = get_next_message(current_app.config, scenario, state, history_rows, action_type, text)

        db.execute(
            "INSERT INTO messages (session_id, turn_number, speaker, content, technique_used) VALUES (?, ?, 'scenario', ?, ?)",
            (session_id, state["turn_count"], result["message"], result["technique_used"]),
        )
        db.execute(
            "UPDATE sessions SET state_json = ?, reasoning_score = ? WHERE id = ?",
            (json.dumps(state), state["reasoning_score"], session_id),
        )
        db.commit()
        response["message"] = result["message"]
        response["ai_generated"] = result["ai_generated"]

    return jsonify(response)


@api_bp.route("/sessions/<int:session_id>/replay", methods=["GET"])
def session_replay(session_id):
    row = _load_session_or_404(session_id)
    if row is None:
        return _error("Session not found", 404)
    if row["status"] != "completed":
        return _error("Replay is only available once a session has completed", 409)

    db = get_db()
    scenario = _resolve_scenario(row["scenario_id"], db, g.user_id)
    messages_rows = db.execute(
        "SELECT turn_number, speaker, content, technique_used FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    decisions_rows = db.execute(
        "SELECT turn_number, action_type, score_delta, category, explanation FROM decisions WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()

    replay = build_replay(scenario, messages_rows, decisions_rows)
    narrative = generate_replay_narrative(current_app.config, scenario, replay, row["outcome"])

    return jsonify({
        "session_id": session_id,
        "scenario_title": scenario["title"],
        "classification": scenario["classification"],
        "outcome": row["outcome"],
        "reasoning_score": row["reasoning_score"],
        "steps": replay["steps"],
        "what_you_did_well": replay["what_you_did_well"],
        "what_you_missed": replay["what_you_missed"],
        "intervention_point": replay["intervention_point"],
        "narrative": narrative["narrative"],
        "lesson_to_remember": narrative["lesson_to_remember"],
        "narrative_ai_generated": narrative["ai_generated"],
    })


@api_bp.route("/profile", methods=["GET"])
def profile():
    db = get_db()
    return jsonify({
        "skill_profile": get_profile(db, g.user_id),
        "overall_proficiency": overall_proficiency(db, g.user_id),
        "weakest_category": weakest_category(db, g.user_id),
        "strongest_category": strongest_category(db, g.user_id),
        "recommended": recommend_scenario(db, g.user_id),
        "achievements": get_achievements(db, g.user_id),
    })
