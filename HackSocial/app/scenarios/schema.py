"""Scenario schema + validation.

Scenario JSON files are trusted, version-controlled content (not user input),
but we validate them anyway so a malformed scenario file fails loudly at
startup instead of corrupting session state at runtime.
"""

CLASSIFICATIONS = {"SCAM", "LEGITIMATE"}
DIFFICULTIES = {"beginner", "intermediate", "advanced"}

# Canonical stage order. A scenario's allowed_stages must be an ordered
# subset of this list (excluding RESOLUTION, which the engine appends
# implicitly once a scenario concludes).
STAGE_ORDER = [
    "CONTACT",
    "RAPPORT",
    "CREDIBILITY",
    "MANIPULATION",
    "REQUEST",
    "ESCALATION",
]
RESOLUTION_STAGE = "RESOLUTION"

ACTION_TYPES = {"CONTINUE", "ASK_QUESTION", "VERIFY", "STOP", "REPORT"}

REQUIRED_FIELDS = [
    "id",
    "title",
    "category",
    "difficulty",
    "classification",
    "base_risk",
    "context",
    "target_learning_objectives",
    "manipulation_techniques",
    "allowed_stages",
    "initial_message",
    "script",
    "expected_red_flags",
    "safe_verification_actions",
    "dangerous_actions",
    "maximum_turns",
    "success_conditions",
    "failure_conditions",
    "scoring_rules",
]


class ScenarioValidationError(ValueError):
    pass


def validate_scenario_dict(data):
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field: {field}")

    if errors:
        raise ScenarioValidationError(f"{data.get('id', '<unknown>')}: {'; '.join(errors)}")

    if data["classification"] not in CLASSIFICATIONS:
        errors.append(f"classification must be one of {CLASSIFICATIONS}, got {data['classification']!r}")

    if data["difficulty"] not in DIFFICULTIES:
        errors.append(f"difficulty must be one of {DIFFICULTIES}, got {data['difficulty']!r}")

    base_risk = data["base_risk"]
    if not isinstance(base_risk, int) or not (0 <= base_risk <= 100):
        errors.append("base_risk must be an integer between 0 and 100")

    allowed_stages = data["allowed_stages"]
    if not isinstance(allowed_stages, list) or not allowed_stages:
        errors.append("allowed_stages must be a non-empty list")
    else:
        if any(s not in STAGE_ORDER for s in allowed_stages):
            errors.append(f"allowed_stages contains unknown stage(s); valid stages are {STAGE_ORDER}")
        # must be in canonical order, no repeats
        indices = [STAGE_ORDER.index(s) for s in allowed_stages if s in STAGE_ORDER]
        if indices != sorted(set(indices)) or len(indices) != len(set(indices)):
            errors.append("allowed_stages must be in canonical order with no repeats")

    script = data["script"]
    if not isinstance(script, list):
        errors.append("script must be a list")
    elif len(allowed_stages) > 0 and len(script) != len(allowed_stages) - 1:
        errors.append(
            f"script must have exactly len(allowed_stages) - 1 entries "
            f"({len(allowed_stages) - 1} expected, got {len(script)})"
        )
    else:
        for i, entry in enumerate(script):
            if "stage" not in entry or "message" not in entry:
                errors.append(f"script[{i}] must have 'stage' and 'message'")
            elif entry["stage"] != allowed_stages[i + 1]:
                errors.append(
                    f"script[{i}].stage ({entry.get('stage')!r}) must match "
                    f"allowed_stages[{i + 1}] ({allowed_stages[i + 1]!r})"
                )

    if not isinstance(data["maximum_turns"], int) or data["maximum_turns"] < 1:
        errors.append("maximum_turns must be a positive integer")

    scoring_rules = data["scoring_rules"]
    if not isinstance(scoring_rules, list) or not scoring_rules:
        errors.append("scoring_rules must be a non-empty list")
    else:
        for i, rule in enumerate(scoring_rules):
            for f in ("trigger", "delta", "category", "explanation"):
                if f not in rule:
                    errors.append(f"scoring_rules[{i}] missing field: {f}")
            trigger = rule.get("trigger", "")
            if not (trigger.startswith("action:") or trigger.startswith("keyword:")):
                errors.append(f"scoring_rules[{i}].trigger must start with 'action:' or 'keyword:', got {trigger!r}")
            if trigger.startswith("action:") and trigger[len("action:"):].upper() not in ACTION_TYPES:
                errors.append(f"scoring_rules[{i}].trigger references unknown action type: {trigger!r}")

    keyword_triggers = {r["trigger"] for r in scoring_rules if isinstance(r, dict) and r.get("trigger", "").startswith("keyword:")}
    trigger_keywords = data.get("trigger_keywords", {})
    missing_keyword_defs = keyword_triggers - set(trigger_keywords.keys())
    if missing_keyword_defs:
        errors.append(f"trigger_keywords is missing definitions for: {missing_keyword_defs}")

    if errors:
        raise ScenarioValidationError(f"{data['id']}: {'; '.join(errors)}")

    return True
