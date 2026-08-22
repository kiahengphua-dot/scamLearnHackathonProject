import logging

from app.ai.claude_client import call_tool, is_configured
from app.artifacts.prompts import ANALYSIS_SYSTEM_PROMPT, build_analysis_messages
from app.artifacts.schemas import ARTIFACT_ANALYSIS_TOOL, AnalysisValidationError, validate_analysis

logger = logging.getLogger(__name__)


class AnalysisUnavailableError(RuntimeError):
    """Raised when Claude is unconfigured or fails after all retries.

    Unlike roleplay, there's no scripted fallback for an arbitrary
    user-submitted artifact — the honest response is to tell the user
    analysis isn't available right now, not to fake one.
    """


def analyze_artifact(config, artifact_type, text=None, image_b64=None, media_type=None, url_facts=None, url_page=None):
    if not is_configured(config):
        raise AnalysisUnavailableError("Artifact analysis requires ANTHROPIC_API_KEY to be configured.")

    messages = build_analysis_messages(
        artifact_type, text=text, image_b64=image_b64, media_type=media_type, url_facts=url_facts, url_page=url_page
    )

    for attempt in range(config.get("ANALYSIS_MAX_ATTEMPTS", 2)):
        raw = call_tool(
            config,
            model=config["ANALYSIS_MODEL"],
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=messages,
            tool=ARTIFACT_ANALYSIS_TOOL,
            max_tokens=config.get("ANALYSIS_MAX_OUTPUT_TOKENS", 1024),
            timeout=config.get("ANALYSIS_TIMEOUT_SECONDS", 30),
        )
        if raw is None:
            continue
        try:
            return validate_analysis(raw)
        except AnalysisValidationError as e:
            logger.warning("Artifact analysis failed validation (attempt %d): %s", attempt + 1, e)
            continue

    raise AnalysisUnavailableError("Claude did not return a usable analysis after retrying.")
