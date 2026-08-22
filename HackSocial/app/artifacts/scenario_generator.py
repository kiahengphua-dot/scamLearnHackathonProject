"""Turns an artifact analysis into a full, schema-valid training scenario.

Claude supplies narrative content only (title, context, stage messages,
red flags, phrases). Every scoring/structural mechanic — score deltas,
terminal flags, maximum_turns, base_risk — is assembled here in plain
Python, exactly like app/ai/roleplay.py keeps Claude out of scoring
during live play. This is also what makes the result reliably valid:
Claude only has to get narrative content right, not a large nested schema.
"""

import logging
import uuid

from app.ai.claude_client import call_tool, is_configured
from app.artifacts.prompts import GENERATION_SYSTEM_PROMPT, build_generation_messages
from app.artifacts.schemas import GENERATION_TOOL, GenerationValidationError, validate_generation_raw
from app.scenarios.schema import ScenarioValidationError, validate_scenario_dict

logger = logging.getLogger(__name__)

# A small, deliberately non-exhaustive denylist of well-known real
# institutions/domains/payment services. Defense in depth alongside the
# prompt instruction to fictionalize — never relied on as the only check,
# but the model must never be the sole enforcer of this either.
REAL_ENTITY_DENYLIST = [
    "paypal", "venmo", "zelle", "western union",
    "amazon", "google", "microsoft", "apple", "facebook", "meta",
    "chase bank", "wells fargo", "bank of america", "citibank", "hsbc",
    "dbs bank", "ocbc", "uob", "singpass", "gov.sg",
    "irs.gov", "hmrc", "paypal.com", "amazon.com",
]

BASE_RISK_TABLE = {
    ("SCAM", "beginner"): 60,
    ("SCAM", "intermediate"): 75,
    ("SCAM", "advanced"): 90,
    ("LEGITIMATE", "beginner"): 10,
    ("LEGITIMATE", "intermediate"): 15,
    ("LEGITIMATE", "advanced"): 20,
}


class GenerationUnavailableError(RuntimeError):
    """Raised when Claude is unconfigured or a valid, safe scenario
    couldn't be produced after all retries. There is no scripted fallback
    for arbitrary user-submitted content — callers must surface this as
    "couldn't generate a scenario," not fabricate one."""


def _contains_real_entity(scenario):
    haystack = " ".join(
        [
            scenario["title"],
            scenario["context"],
            scenario["initial_message"],
            *(s["message"] for s in scenario["script"]),
        ]
    ).lower()
    return next((term for term in REAL_ENTITY_DENYLIST if term in haystack), None)


def _build_standard_scoring_rules(classification, dangerous_category):
    if classification == "LEGITIMATE":
        return [
            {"trigger": "action:continue", "delta": 10, "category": "verification_behaviour",
             "explanation": "Proceeding was reasonable — nothing here indicated malicious intent."},
            {"trigger": "action:verify", "delta": 15, "category": "verification_behaviour",
             "explanation": "Double-checking is a good habit even when a message turns out to be legitimate."},
            {"trigger": "action:stop", "delta": -10, "category": "verification_behaviour",
             "explanation": "Cutting off contact wasn't necessary here — nothing indicated malicious intent."},
            {"trigger": "action:report", "delta": -10, "category": "verification_behaviour",
             "explanation": "Reporting a legitimate message spends others' time on something that wasn't a threat."},
        ]

    rules = [
        {"trigger": "action:verify", "delta": 20, "category": "verification_behaviour",
         "explanation": "Choosing to verify independently instead of acting on the message directly."},
        {"trigger": "action:stop", "delta": 15, "category": "verification_behaviour",
         "explanation": "Ending contact prevented further pressure."},
        {"trigger": "action:report", "delta": 15, "category": "verification_behaviour",
         "explanation": "Reporting the message helps flag it for others."},
        {"trigger": "keyword:verifies_independently", "delta": 20, "category": "verification_behaviour",
         "explanation": "Verifying through an independent, known channel is the safest response."},
    ]
    if dangerous_category != "none":
        rules.append({
            "trigger": "keyword:falls_for_request",
            "delta": -30,
            "category": dangerous_category,
            "terminal": True,
            "explanation": "Complying with this request is exactly what this kind of scam is designed to get you to do.",
        })
    return rules


def _assemble_scenario_dict(raw):
    stages = raw["stages"]
    stage_names = [s["stage"] for s in stages]
    initial_message = stages[0]["message"]
    script = [{"stage": s["stage"], "message": s["message"]} for s in stages[1:]]

    trigger_keywords = {
        "keyword:verifies_independently": [p.lower() for p in raw["safe_phrases"]][:8] or ["i will verify independently"],
    }
    if raw["classification"] == "SCAM" and raw["dangerous_category"] != "none":
        trigger_keywords["keyword:falls_for_request"] = [p.lower() for p in raw["dangerous_phrases"]][:8] or ["yes, i'll do that"]

    techniques = raw["manipulation_techniques"] if raw["classification"] == "SCAM" else []

    return {
        "id": f"generated-{uuid.uuid4().hex[:12]}",
        "title": raw["title"].strip()[:120],
        "category": raw["category"].strip().lower(),
        "difficulty": raw["difficulty"],
        "classification": raw["classification"],
        "base_risk": BASE_RISK_TABLE[(raw["classification"], raw["difficulty"])],
        "context": raw["context"].strip(),
        "target_learning_objectives": [
            f"Recognize the manipulation techniques used in this scenario: {', '.join(techniques) or 'none — this is a legitimate example'}"
        ],
        "manipulation_techniques": techniques,
        "allowed_stages": stage_names,
        "initial_message": initial_message,
        "script": script,
        "expected_red_flags": raw["expected_red_flags"],
        "safe_verification_actions": raw["safe_verification_actions"],
        "dangerous_actions": ["Complying with the core request made in this message"] if raw["classification"] == "SCAM" else [],
        "maximum_turns": len(stage_names) + 1,
        "success_conditions": ["Session ends without complying with the core dangerous request"],
        "failure_conditions": ["User complies with the core dangerous request"],
        "scoring_rules": _build_standard_scoring_rules(raw["classification"], raw["dangerous_category"]),
        "trigger_keywords": trigger_keywords,
        "generated": True,
        "source": "artifact_analysis",
    }


def generate_scenario_from_analysis(config, analysis):
    if not is_configured(config):
        raise GenerationUnavailableError("Scenario generation requires ANTHROPIC_API_KEY to be configured.")

    messages = build_generation_messages(analysis)

    for attempt in range(config.get("GENERATION_MAX_ATTEMPTS", 2)):
        raw = call_tool(
            config,
            model=config["ANALYSIS_MODEL"],
            system=GENERATION_SYSTEM_PROMPT,
            messages=messages,
            tool=GENERATION_TOOL,
            max_tokens=config.get("GENERATION_MAX_OUTPUT_TOKENS", 2048),
            timeout=config.get("ANALYSIS_TIMEOUT_SECONDS", 30),
        )
        if raw is None:
            continue

        try:
            validated_raw = validate_generation_raw(raw)
            scenario = _assemble_scenario_dict(validated_raw)
            validate_scenario_dict(scenario)
        except (GenerationValidationError, ScenarioValidationError) as e:
            logger.warning("Generated scenario failed validation (attempt %d): %s", attempt + 1, e)
            continue

        blocked_term = _contains_real_entity(scenario)
        if blocked_term:
            logger.warning("Generated scenario rejected: contained real-entity term %r (attempt %d)", blocked_term, attempt + 1)
            continue

        return scenario

    raise GenerationUnavailableError("Couldn't generate a safe, valid training scenario from this artifact after retrying.")
