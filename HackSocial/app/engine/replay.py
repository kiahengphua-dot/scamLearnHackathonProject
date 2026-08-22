"""Scam Replay: reconstructs a completed session's turn-by-turn timeline
and its intervention point, entirely from data already recorded by the
deterministic engine (messages + decisions tables).

No AI is required for correctness here — every fact in the replay is
backend-derived and verifiable. app/ai/replay_narrative.py may add a short
human-readable narrative on top, but the underlying timeline never depends
on it.
"""


def _stage_for_turn(scenario, turn_number):
    stages = scenario["allowed_stages"]
    if turn_number < len(stages):
        return stages[turn_number]
    return "RESOLUTION"


def build_replay(scenario, messages_rows, decisions_rows):
    scenario_msgs = {m["turn_number"]: m for m in messages_rows if m["speaker"] == "scenario"}
    user_msgs = {m["turn_number"]: m for m in messages_rows if m["speaker"] == "user"}

    decisions_by_turn = {}
    for d in decisions_rows:
        decisions_by_turn.setdefault(d["turn_number"], []).append(
            {"category": d["category"], "delta": d["score_delta"], "explanation": d["explanation"]}
        )

    turns = sorted(set(scenario_msgs) | set(user_msgs))
    steps = []
    did_well = []
    missed = []

    for t in turns:
        smsg = scenario_msgs.get(t)
        umsg = user_msgs.get(t)
        applied = decisions_by_turn.get(t, [])

        steps.append({
            "turn": t,
            "stage": _stage_for_turn(scenario, t),
            "scenario_message": smsg["content"] if smsg else None,
            "technique_used": smsg["technique_used"] if smsg else None,
            "user_action": umsg["content"] if umsg else None,
            "score_delta": sum(r["delta"] for r in applied),
            "applied_rules": applied,
        })

        for rule in applied:
            entry = {"turn": t, "category": rule["category"], "explanation": rule["explanation"]}
            if rule["delta"] > 0:
                did_well.append(entry)
            elif rule["delta"] < 0:
                missed.append(entry)

    final_turn = max(turns) if turns else None
    intervention_point = _find_intervention_point(scenario, steps, final_turn)

    return {
        "steps": steps,
        "what_you_did_well": did_well,
        "what_you_missed": missed,
        "intervention_point": intervention_point,
    }


def _find_intervention_point(scenario, steps, final_turn):
    """Where the outcome was actually decided — the turn carrying the
    scenario's terminal decision, framed as either 'caught' (a safe action
    ended it) or 'missed' (a dangerous trigger ended it). Legitimate
    scenarios have no attack to intervene on."""
    if scenario["classification"] != "SCAM" or final_turn is None:
        return None

    final_step = next((s for s in steps if s["turn"] == final_turn), None)
    if final_step is None:
        return None

    framing = "caught" if final_step["score_delta"] >= 0 else "missed"
    return {
        "turn": final_step["turn"],
        "stage": final_step["stage"],
        "scenario_message": final_step["scenario_message"],
        "framing": framing,
    }
