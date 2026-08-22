"""Orchestrates one roleplay turn: try Claude, validate, retry once, and
fall back to the deterministic scripted message if anything goes wrong.

This module is the ONLY thing api.py calls for dialogue generation. It
never touches scoring, classification, or scenario state — those stay
entirely in app.engine, decided before this module is ever invoked.
"""

import logging

from app.ai.claude_client import call_tool, is_configured
from app.ai.prompts import build_messages, build_system_prompt
from app.ai.schemas import ROLEPLAY_TOOL, RoleplayValidationError, validate_roleplay_response
from app.engine.state_machine import next_scenario_message

logger = logging.getLogger(__name__)


def get_next_message(config, scenario, state, history_rows, action_type, user_text):
    """Returns a dict: {message, technique_used, ai_generated}.

    history_rows must be the session's messages in chronological order,
    with the very first (initial_message) row already excluded, and the
    just-recorded current user turn included as the last row.
    """
    if not is_configured(config):
        return _fallback(scenario, state)

    system = build_system_prompt(scenario)
    messages = build_messages(scenario, state, history_rows, action_type, user_text)

    for attempt in range(config.get("CLAUDE_MAX_ATTEMPTS", 2)):
        raw = call_tool(
            config,
            model=config["ROLEPLAY_MODEL"],
            system=system,
            messages=messages,
            tool=ROLEPLAY_TOOL,
            max_tokens=config.get("CLAUDE_MAX_OUTPUT_TOKENS", 300),
            timeout=config.get("CLAUDE_TIMEOUT_SECONDS", 20),
        )
        if raw is None:
            continue  # call_tool already logged the failure reason
        try:
            validated = validate_roleplay_response(raw, scenario)
        except RoleplayValidationError as e:
            logger.warning("Claude roleplay response failed validation (attempt %d): %s", attempt + 1, e)
            continue
        return {
            "message": validated["message"],
            "technique_used": validated["technique_used"],
            "ai_generated": True,
        }

    logger.warning("Falling back to scripted response for scenario %s after exhausting Claude attempts", scenario["id"])
    return _fallback(scenario, state)


def _fallback(scenario, state):
    return {
        "message": next_scenario_message(scenario, state),
        "technique_used": None,
        "ai_generated": False,
    }
