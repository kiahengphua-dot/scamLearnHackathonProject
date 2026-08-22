"""The Claude roleplay contract.

Claude is FORCED to respond through this tool (via tool_choice) so it can
only ever return these three fields — it structurally cannot smuggle a
score, classification, or outcome back through this channel. We still
validate the values defensively: never trust AI output just because the
API accepted the tool call.
"""

ROLEPLAY_INTENTS = {
    "build_rapport",
    "assert_authority",
    "create_urgency",
    "create_fear",
    "offer_reward",
    "request_information",
    "escalate_pressure",
    "respond_to_resistance",
    "maintain_cover",
    "reassure",
    "de_escalate",
}

MAX_MESSAGE_LENGTH = 800

ROLEPLAY_TOOL = {
    "name": "provide_roleplay_response",
    "description": "Provide the in-character roleplay message for this turn of the ScamLearn simulation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The in-character message to show the user. Stay fully in character. 1-4 sentences.",
            },
            "roleplay_intent": {
                "type": "string",
                "enum": sorted(ROLEPLAY_INTENTS),
                "description": "The dramatic intent behind this message.",
            },
            "technique_used": {
                "type": "string",
                "description": "The manipulation technique this message primarily uses, or 'none' if this scenario is legitimate / no technique applies.",
            },
        },
        "required": ["message", "roleplay_intent", "technique_used"],
        "additionalProperties": False,
    },
}


class RoleplayValidationError(ValueError):
    pass


def validate_roleplay_response(data, scenario):
    if not isinstance(data, dict):
        raise RoleplayValidationError("tool input was not an object")

    message = data.get("message")
    if not isinstance(message, str):
        raise RoleplayValidationError("message must be a string")
    message = message.strip()
    if not (1 <= len(message) <= MAX_MESSAGE_LENGTH):
        raise RoleplayValidationError(f"message length out of bounds (1-{MAX_MESSAGE_LENGTH})")

    intent = data.get("roleplay_intent")
    if intent not in ROLEPLAY_INTENTS:
        raise RoleplayValidationError(f"roleplay_intent {intent!r} is not an allowed value")

    technique = data.get("technique_used")
    allowed_techniques = set(scenario["manipulation_techniques"]) | {"none"}
    if technique not in allowed_techniques:
        raise RoleplayValidationError(
            f"technique_used {technique!r} is not in this scenario's allowed techniques {allowed_techniques}"
        )

    return {"message": message, "roleplay_intent": intent, "technique_used": technique}
