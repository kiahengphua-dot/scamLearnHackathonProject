"""Server-side reasoning score engine.

Claude (once wired in) may TAG what happened in a turn, but this module is
the only thing that ever converts a tag into points. Scores are always
computed here from each scenario's own scoring_rules table, never trusted
from AI output or from the client.
"""

BASELINE_SCORE = 50
MIN_SCORE = 0
MAX_SCORE = 100


def detect_triggers(scenario, action_type, text):
    """Return the list of trigger keys that fired this turn.

    Detection here is deliberately simple (action type + keyword matching)
    because this phase must work without any AI involvement. Phase 5 will
    let Claude propose additional trigger tags, but this function's output
    remains the authoritative fallback / cross-check.
    """
    triggers = [f"action:{action_type.lower()}"]

    if text:
        lowered = text.lower()
        for trigger, keywords in scenario.get("trigger_keywords", {}).items():
            if any(kw.lower() in lowered for kw in keywords):
                triggers.append(trigger)

    # Only keep triggers this scenario actually has a scoring rule for.
    known = {r["trigger"] for r in scenario["scoring_rules"]}
    return [t for t in triggers if t in known]


def score_triggers(scenario, triggers):
    """Map fired triggers to their configured score deltas, deduplicated
    so the same trigger can't be double-counted in a single turn."""
    rules_by_trigger = {r["trigger"]: r for r in scenario["scoring_rules"]}
    applied = []
    seen = set()
    for trigger in triggers:
        if trigger in seen:
            continue
        seen.add(trigger)
        rule = rules_by_trigger.get(trigger)
        if rule:
            applied.append(
                {
                    "trigger": trigger,
                    "delta": rule["delta"],
                    "category": rule["category"],
                    "explanation": rule["explanation"],
                    "terminal": rule.get("terminal", False),
                }
            )
    return applied


def apply_score(current_score, applied_rules):
    total = current_score
    for rule in applied_rules:
        total += rule["delta"]
    return max(MIN_SCORE, min(MAX_SCORE, total))
