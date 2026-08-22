"""Deterministic scenario state machine.

The application owns scenario state, stage progression, and resolution.
No AI is involved here — this must work standalone so the engine's
correctness can be verified independently of the (later) Claude roleplay
layer.
"""

from app.engine import outcome as outcome_module
from app.engine.scoring import BASELINE_SCORE, apply_score, detect_triggers, score_triggers
from app.scenarios.schema import ACTION_TYPES

# Rough urgency/trust progression by position in the stage sequence — a
# deterministic stand-in for the "tension" the AI roleplay will later
# convey dynamically. Indexed by (position / total_stages).
_URGENCY_CURVE = [10, 30, 50, 70, 85, 95]


def _urgency_for_position(position, total_stages):
    if total_stages <= 1:
        return _URGENCY_CURVE[0]
    curve_index = min(len(_URGENCY_CURVE) - 1, round(position * (len(_URGENCY_CURVE) - 1) / max(1, total_stages - 1)))
    return _URGENCY_CURVE[curve_index]


def create_session_state(scenario):
    allowed_stages = scenario["allowed_stages"]
    return {
        "stage_index": 0,
        "stage": allowed_stages[0],
        "turn_count": 0,
        "reasoning_score": BASELINE_SCORE,
        "urgency_level": _urgency_for_position(0, len(allowed_stages)),
        "risk_level": scenario["base_risk"],
        "detected_behaviours": [],
        "applied_scoring_log": [],
        "status": "in_progress",
        "outcome": None,
        "ending_reason": None,
    }


class InvalidActionError(ValueError):
    pass


def apply_decision(scenario, state, action_type, text=""):
    """Advance the state machine by one user decision.

    Returns the updated state dict. The caller is responsible for
    persisting messages/decisions rows; this function is pure state logic
    so it's trivially unit-testable without a database.
    """
    if state["status"] != "in_progress":
        raise InvalidActionError("Cannot act on a completed session")

    action_type = action_type.upper()
    if action_type not in ACTION_TYPES:
        raise InvalidActionError(f"Unknown action_type: {action_type}")

    text = (text or "")[:1000]

    triggers = detect_triggers(scenario, action_type, text)
    applied_rules = score_triggers(scenario, triggers)

    state["reasoning_score"] = apply_score(state["reasoning_score"], applied_rules)
    state["detected_behaviours"].extend(r["trigger"] for r in applied_rules)
    state["applied_scoring_log"].append(
        {"turn": state["turn_count"], "action_type": action_type, "applied_rules": applied_rules}
    )

    terminal_rule = next((r for r in applied_rules if r["terminal"]), None)
    allowed_stages = scenario["allowed_stages"]

    if terminal_rule is not None:
        _resolve(scenario, state, outcome_module.END_DANGEROUS_TRIGGER)
    elif action_type == "STOP":
        _resolve(scenario, state, outcome_module.END_USER_STOPPED)
    elif action_type == "REPORT":
        _resolve(scenario, state, outcome_module.END_USER_REPORTED)
    else:
        next_index = state["stage_index"] + 1
        state["turn_count"] += 1
        if next_index >= len(allowed_stages) or state["turn_count"] >= scenario["maximum_turns"]:
            _resolve(scenario, state, outcome_module.END_TURNS_EXHAUSTED)
        else:
            state["stage_index"] = next_index
            state["stage"] = allowed_stages[next_index]
            state["urgency_level"] = _urgency_for_position(next_index, len(allowed_stages))

    return state


def _resolve(scenario, state, ending_reason):
    state["status"] = "completed"
    state["stage"] = "RESOLUTION"
    state["ending_reason"] = ending_reason
    state["outcome"] = outcome_module.determine_outcome(scenario, ending_reason)


def next_scenario_message(scenario, state):
    """The scripted message for the current stage, or None once resolved."""
    if state["status"] == "completed":
        return None
    stage_index = state["stage_index"]
    if stage_index == 0:
        return scenario["initial_message"]
    return scenario["script"][stage_index - 1]["message"]
