"""Structured contracts for artifact analysis and scenario generation.

Both are forced through Anthropic tool calls, same pattern as the roleplay
contract in app/ai/schemas.py: the model can only ever return the fields
listed here, and everything is re-validated on the backend regardless.
"""

from app.scenarios.schema import DIFFICULTIES, STAGE_ORDER

SEVERITIES = {"low", "medium", "high"}
RISK_LEVELS = {"low", "medium", "high"}
DANGEROUS_CATEGORIES = {"credential_harvesting", "financial_manipulation", "suspicious_links", "none"}

INDICATOR_TYPES = {
    "urgency",
    "authority_impersonation",
    "fear",
    "financial_pressure",
    "suspicious_links",
    "credential_request",
    "otp_request",
    "unusual_payment_request",
    "impersonation",
    "spelling_grammar_anomalies",
    "suspicious_contact_details",
    "inconsistent_branding",
    "unusual_instructions",
    "emotional_manipulation",
    "bypass_normal_procedure",
}

ARTIFACT_ANALYSIS_TOOL = {
    "name": "report_artifact_analysis",
    "description": "Report a structured, evidence-based analysis of a submitted message/screenshot. Never assert certainty — report evidence and let risk_assessment reflect confidence, not a verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "risk_assessment": {"type": "string", "enum": sorted(RISK_LEVELS)},
            "confidence": {"type": "number", "description": "0.0-1.0, how confident this assessment is given the available evidence."},
            "indicators": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": sorted(INDICATOR_TYPES)},
                        "evidence": {"type": "string", "description": "A short quote or description of what in the artifact shows this indicator."},
                        "severity": {"type": "string", "enum": sorted(SEVERITIES)},
                    },
                    "required": ["type", "evidence", "severity"],
                    "additionalProperties": False,
                },
            },
            "possible_techniques": {
                "type": "array",
                "maxItems": 6,
                "items": {"type": "string"},
                "description": "Manipulation techniques this evidence suggests, e.g. urgency, authority, scarcity, financial_pressure.",
            },
            "recommended_verification": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string"},
            },
            "summary": {
                "type": "string",
                "description": "1-2 sentences, hedged (\"evidence suggests...\"), never a flat verdict like \"this is a scam\".",
            },
        },
        "required": ["risk_assessment", "confidence", "indicators", "possible_techniques", "recommended_verification", "summary"],
        "additionalProperties": False,
    },
}

# Claude supplies narrative content only (messages, red flags, phrases).
# All scoring mechanics (deltas, terminal flags, table structure) are
# assembled deterministically in scenario_generator.py — same principle as
# the roleplay layer: Claude narrates, the backend decides what counts.
GENERATION_TOOL = {
    "name": "generate_training_scenario",
    "description": "Propose a fictionalized training scenario based on the techniques found in an analyzed artifact. Never reuse the artifact's real names, domains, or account details — fictionalize everything while preserving the educational techniques.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "category": {"type": "string", "description": "lowercase category, e.g. banking, delivery, employment, investment"},
            "context": {"type": "string", "description": "1-2 sentences describing the fictional setting/organization."},
            "classification": {"type": "string", "enum": ["SCAM", "LEGITIMATE"]},
            "difficulty": {"type": "string", "enum": sorted(DIFFICULTIES)},
            "manipulation_techniques": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
            "dangerous_category": {"type": "string", "enum": sorted(DANGEROUS_CATEGORIES), "description": "'none' if classification is LEGITIMATE."},
            "stages": {
                "type": "array",
                "minItems": 2,
                "maxItems": len(STAGE_ORDER),
                "items": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string", "enum": STAGE_ORDER},
                        "message": {"type": "string"},
                        "technique": {"type": "string"},
                    },
                    "required": ["stage", "message"],
                    "additionalProperties": False,
                },
            },
            "expected_red_flags": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
            "safe_verification_actions": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
            "dangerous_phrases": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
                "description": "Lowercase phrases that would indicate the user complied with the core dangerous request (for keyword detection). Empty if classification is LEGITIMATE.",
            },
            "safe_phrases": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string"},
                "description": "Lowercase phrases indicating the user chose to verify independently.",
            },
        },
        "required": [
            "title", "category", "context", "classification", "difficulty",
            "manipulation_techniques", "dangerous_category", "stages",
            "expected_red_flags", "safe_verification_actions", "dangerous_phrases", "safe_phrases",
        ],
        "additionalProperties": False,
    },
}


class AnalysisValidationError(ValueError):
    pass


class GenerationValidationError(ValueError):
    pass


def validate_analysis(data):
    if not isinstance(data, dict):
        raise AnalysisValidationError("tool input was not an object")

    if data.get("risk_assessment") not in RISK_LEVELS:
        raise AnalysisValidationError("invalid risk_assessment")

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        raise AnalysisValidationError("confidence must be a number between 0 and 1")

    indicators = data.get("indicators")
    if not isinstance(indicators, list):
        raise AnalysisValidationError("indicators must be a list")
    for ind in indicators:
        if ind.get("type") not in INDICATOR_TYPES:
            raise AnalysisValidationError(f"invalid indicator type: {ind.get('type')!r}")
        if ind.get("severity") not in SEVERITIES:
            raise AnalysisValidationError(f"invalid indicator severity: {ind.get('severity')!r}")
        if not isinstance(ind.get("evidence"), str) or not (1 <= len(ind["evidence"]) <= 400):
            raise AnalysisValidationError("indicator evidence must be a non-empty string up to 400 chars")

    possible_techniques = data.get("possible_techniques")
    if not isinstance(possible_techniques, list) or any(not isinstance(t, str) for t in possible_techniques):
        raise AnalysisValidationError("possible_techniques must be a list of strings")

    recommended_verification = data.get("recommended_verification")
    if not isinstance(recommended_verification, list) or any(not isinstance(v, str) for v in recommended_verification):
        raise AnalysisValidationError("recommended_verification must be a list of strings")

    summary = data.get("summary")
    if not isinstance(summary, str) or not (1 <= len(summary) <= 500):
        raise AnalysisValidationError("summary must be a string up to 500 chars")

    # Defense in depth against overconfident phrasing, even though the
    # prompt already instructs Claude to hedge.
    banned_phrases = ["this is definitely", "this is certainly", "100% a scam", "guaranteed scam", "confirmed scam"]
    lowered = summary.lower()
    if any(p in lowered for p in banned_phrases):
        raise AnalysisValidationError("summary asserts unwarranted certainty")

    return {
        "risk_assessment": data["risk_assessment"],
        "confidence": float(confidence),
        "indicators": [
            {"type": i["type"], "evidence": i["evidence"].strip(), "severity": i["severity"]} for i in indicators
        ],
        "possible_techniques": [str(t).strip().lower().replace(" ", "_") for t in data["possible_techniques"]][:6],
        "recommended_verification": [str(v).strip() for v in data["recommended_verification"]][:5],
        "summary": summary.strip(),
    }


def validate_generation_raw(data):
    """Structural/enum validation of Claude's proposal, BEFORE it's
    assembled into a full scenario dict. The assembled dict is validated
    again by app.scenarios.schema.validate_scenario_dict — this function
    only checks the narrower contract Claude actually filled in."""
    if not isinstance(data, dict):
        raise GenerationValidationError("tool input was not an object")

    if data.get("classification") not in {"SCAM", "LEGITIMATE"}:
        raise GenerationValidationError("invalid classification")
    if data.get("difficulty") not in DIFFICULTIES:
        raise GenerationValidationError("invalid difficulty")
    if data.get("dangerous_category") not in DANGEROUS_CATEGORIES:
        raise GenerationValidationError("invalid dangerous_category")

    stages = data.get("stages")
    if not isinstance(stages, list) or not (2 <= len(stages) <= len(STAGE_ORDER)):
        raise GenerationValidationError(f"stages must be a list of 2-{len(STAGE_ORDER)} entries")

    seen_indices = []
    for s in stages:
        if s.get("stage") not in STAGE_ORDER:
            raise GenerationValidationError(f"invalid stage name: {s.get('stage')!r}")
        if not isinstance(s.get("message"), str) or not (1 <= len(s["message"]) <= 600):
            raise GenerationValidationError("stage message must be a string up to 600 chars")
        seen_indices.append(STAGE_ORDER.index(s["stage"]))

    if seen_indices != sorted(seen_indices) or len(seen_indices) != len(set(seen_indices)):
        raise GenerationValidationError("stages must be in canonical order with no repeats")

    for field in ("title", "category", "context"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise GenerationValidationError(f"{field} must be a non-empty string")

    if len(data["title"]) > 120:
        raise GenerationValidationError("title too long")

    if data["classification"] == "SCAM" and data["dangerous_category"] == "none":
        raise GenerationValidationError("a SCAM scenario must have a dangerous_category other than 'none'")
    if data["classification"] == "LEGITIMATE" and data["dangerous_category"] != "none":
        raise GenerationValidationError("a LEGITIMATE scenario must have dangerous_category 'none'")

    # Tool schemas are advisory, not strictly enforced by the model — a
    # forced tool call can still come back with the wrong shape (e.g. a
    # comma-joined string where an array of strings was asked for). Every
    # list field must be validated as an actual list of strings before use.
    list_fields = (
        "manipulation_techniques",
        "expected_red_flags",
        "safe_verification_actions",
        "dangerous_phrases",
        "safe_phrases",
    )
    for field in list_fields:
        value = data.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise GenerationValidationError(f"{field} must be a list of strings, got {type(value).__name__}: {value!r}")

    return data
