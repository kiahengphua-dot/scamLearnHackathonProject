"""Turns a deterministic replay (app/engine/replay.py) into a short,
human-readable narrative and a one-line lesson to remember (spec section
15: explain rather than judge, never shame).

Every fact Claude narrates here (techniques used, what was done well/
missed, the intervention point) is handed to it as already-computed,
trusted context — it is not asked to determine any of that itself. If
Claude is unavailable or its output fails validation, a templated
narrative is used instead so the replay page never breaks.
"""

import logging

from app.ai.claude_client import call_tool, is_configured

logger = logging.getLogger(__name__)

MAX_NARRATIVE_LENGTH = 900
MAX_LESSON_LENGTH = 200

REPLAY_NARRATIVE_TOOL = {
    "name": "provide_replay_narrative",
    "description": "Write a short, non-judgmental explanation of what happened in this training scenario, and one lesson to remember.",
    "input_schema": {
        "type": "object",
        "properties": {
            # lesson_to_remember is listed first and kept intentionally
            # short: a truncated response (from too small a token budget)
            # is far more likely to lose a later, longer field, so put the
            # short, essential one first.
            "lesson_to_remember": {
                "type": "string",
                "description": "One short, memorable sentence the user can carry forward. Under 150 characters.",
            },
            "narrative": {
                "type": "string",
                "description": "2-3 sentences (under 500 characters total) explaining what happened and why it works as manipulation (or why the situation was actually benign), addressed to the user as 'you'. Never shaming — explain the technique, not the person's failure. Be concise, not exhaustive.",
            },
        },
        "required": ["lesson_to_remember", "narrative"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are the educational-explanation engine for ScamLearn. You are given a factual, already-computed replay of a training scenario the user just completed: the manipulation techniques used, what the user did well, what they missed, and where the outcome was decided.

RULES:
1. Explain, don't judge. If the user was manipulated, never say things like "you failed" or "you should have known better." Instead explain the mechanism, e.g. "authority-based requests can feel legitimate before you verify them."
2. Never invent facts not present in the replay data you're given — you are narrating a fixed timeline, not deciding what happened.
3. Be concise. Both fields together should be well under 200 words — this is a short takeaway, not an essay. Brevity matters more than completeness here.
4. You must respond by calling the provide_replay_narrative tool exactly once, with lesson_to_remember before narrative."""


def _build_user_content(scenario, replay, outcome):
    lines = [
        f"Scenario: {scenario['title']} ({scenario['category']}, classification: {scenario['classification']})",
        f"Outcome: {outcome}",
    ]
    techniques = {s["technique_used"] for s in replay["steps"] if s["technique_used"]}
    if techniques:
        lines.append(f"Techniques used: {', '.join(sorted(techniques))}")

    if replay["what_you_did_well"]:
        lines.append("What the user did well: " + "; ".join(e["explanation"] for e in replay["what_you_did_well"]))
    if replay["what_you_missed"]:
        lines.append("What the user missed: " + "; ".join(e["explanation"] for e in replay["what_you_missed"]))

    ip = replay["intervention_point"]
    if ip:
        verb = "successfully caught" if ip["framing"] == "caught" else "could have intervened at"
        lines.append(f"Intervention point ({verb}): stage {ip['stage']} — \"{ip['scenario_message']}\"")

    return "\n".join(lines)


def _validate(data):
    if not isinstance(data, dict):
        return None
    narrative = data.get("narrative")
    lesson = data.get("lesson_to_remember")
    if not isinstance(narrative, str) or not (1 <= len(narrative) <= MAX_NARRATIVE_LENGTH):
        return None
    if not isinstance(lesson, str) or not (1 <= len(lesson) <= MAX_LESSON_LENGTH):
        return None
    return {"narrative": narrative.strip(), "lesson_to_remember": lesson.strip()}


def _template_fallback(scenario, replay, outcome):
    ip = replay["intervention_point"]
    if scenario["classification"] != "SCAM":
        narrative = (
            "This situation was legitimate. The lesson here isn't to distrust every message like this one — "
            "it's to verify calmly rather than assume the worst, since caution and suspicion aren't the same thing."
        )
        lesson = "Verify, don't assume — legitimate messages deserve a check, not automatic distrust."
    elif ip and ip["framing"] == "caught":
        narrative = (
            f"This scenario used {', '.join(sorted({s['technique_used'] for s in replay['steps'] if s['technique_used']})) or 'social pressure'} "
            "to try to get you to act quickly. You paused and verified instead, which is exactly the behaviour that "
            "stops this kind of attempt from working."
        )
        lesson = "Verifying independently, even under pressure, is what breaks the scam."
    else:
        narrative = (
            "This scenario built pressure gradually before making its real request. That escalation is deliberate — "
            "it's designed to make the request feel routine by the time it arrives, before you've had a chance to verify."
        )
        lesson = "When a request feels urgent, that urgency is often the manipulation itself."
    return {"narrative": narrative, "lesson_to_remember": lesson}


def generate_replay_narrative(config, scenario, replay, outcome):
    fallback = _template_fallback(scenario, replay, outcome)

    if not is_configured(config):
        return {**fallback, "ai_generated": False}

    user_content = _build_user_content(scenario, replay, outcome)
    for attempt in range(config.get("CLAUDE_MAX_ATTEMPTS", 2)):
        raw = call_tool(
            config,
            model=config.get("SYNTHESIS_MODEL", "claude-sonnet-5"),
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tool=REPLAY_NARRATIVE_TOOL,
            max_tokens=config.get("REPLAY_MAX_OUTPUT_TOKENS", 600),
            timeout=config.get("CLAUDE_TIMEOUT_SECONDS", 20),
        )
        if raw is None:
            continue
        validated = _validate(raw)
        if validated is None:
            logger.warning("Replay narrative failed validation (attempt %d)", attempt + 1)
            continue
        return {**validated, "ai_generated": True}

    return {**fallback, "ai_generated": False}
