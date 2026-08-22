"""Resolves a finished session into a labeled outcome.

This is where the scenario's true classification is finally revealed —
never before this point, and never by the AI mid-conversation.
"""

OUTCOME_AVOIDED_SCAM = "avoided_scam"
OUTCOME_MANIPULATED = "manipulated"
OUTCOME_HANDLED_CORRECTLY = "handled_correctly"
OUTCOME_OVERLY_CAUTIOUS = "overly_cautious"

END_DANGEROUS_TRIGGER = "dangerous_trigger"
END_USER_STOPPED = "user_stopped"
END_USER_REPORTED = "user_reported"
END_TURNS_EXHAUSTED = "turns_exhausted"


def determine_outcome(scenario, ending_reason):
    classification = scenario["classification"]
    is_scam = classification == "SCAM"

    if ending_reason == END_DANGEROUS_TRIGGER:
        return OUTCOME_MANIPULATED if is_scam else OUTCOME_HANDLED_CORRECTLY

    if ending_reason in (END_USER_STOPPED, END_USER_REPORTED):
        return OUTCOME_AVOIDED_SCAM if is_scam else OUTCOME_OVERLY_CAUTIOUS

    if ending_reason == END_TURNS_EXHAUSTED:
        return OUTCOME_AVOIDED_SCAM if is_scam else OUTCOME_HANDLED_CORRECTLY

    raise ValueError(f"Unknown ending_reason: {ending_reason}")


OUTCOME_SUMMARIES = {
    OUTCOME_AVOIDED_SCAM: "You avoided the scam.",
    OUTCOME_MANIPULATED: "You were successfully manipulated in this simulation.",
    OUTCOME_HANDLED_CORRECTLY: "This was a legitimate situation, and you handled it appropriately.",
    OUTCOME_OVERLY_CAUTIOUS: "This was a legitimate situation. Your caution wasn't harmful here, but it wasn't needed either.",
}
