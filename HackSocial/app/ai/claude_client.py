"""Thin wrapper around the Anthropic SDK.

Never imported by route handlers directly — routes talk to
app.ai.roleplay, which owns the fallback logic. This module only knows
how to make (or refuse to make) one API call.
"""

import logging

import anthropic

logger = logging.getLogger(__name__)


def is_configured(config):
    key = config.get("ANTHROPIC_API_KEY")
    return bool(key) and key != "your_api_key_here"


def get_client(config):
    if not is_configured(config):
        return None
    return anthropic.Anthropic(api_key=config["ANTHROPIC_API_KEY"])


def call_tool(config, *, model, system, messages, tool, max_tokens, timeout):
    """Make one Claude call forced through `tool`. Returns the tool's raw
    input dict on success, or None on any failure. Never raises — this is
    an external, unreliable dependency and the caller must be able to fall
    back safely no matter what goes wrong."""
    client = get_client(config)
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            timeout=timeout,
        )
    except anthropic.APIError as e:
        logger.warning("Claude API error: %s", e)
        return None
    except Exception as e:  # noqa: BLE001 - external dependency, must never crash the session
        logger.warning("Unexpected error calling Claude: %s", e)
        return None

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
            return block.input

    logger.warning("Claude response contained no tool_use block for %s", tool["name"])
    return None
