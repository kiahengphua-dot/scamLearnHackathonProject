import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    ROLEPLAY_MODEL = os.environ.get("ROLEPLAY_MODEL", "claude-haiku-4-5-20251001")
    SYNTHESIS_MODEL = os.environ.get("SYNTHESIS_MODEL", "claude-sonnet-5")

    DB_PATH = BASE_DIR / "instance" / "scamlearn.db"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Safety limits for untrusted input (section 28/30 of the spec)
    MAX_USER_MESSAGE_LENGTH = 1000
    MAX_TURNS_HARD_CAP = 20

    # Claude roleplay call limits — keep hackathon API cost/latency bounded.
    CLAUDE_MAX_OUTPUT_TOKENS = 300
    CLAUDE_TIMEOUT_SECONDS = 20
    CLAUDE_MAX_ATTEMPTS = 2  # 1 initial call + 1 retry on failure/malformed output
    MAX_HISTORY_MESSAGES = 20

    # Separate, larger budget from roleplay turns — a narrative + lesson is
    # naturally longer than a single in-character line, and a too-small
    # budget risks truncating the JSON tool call mid-response, silently
    # dropping trailing fields (found via live testing, not a hypothetical).
    REPLAY_MAX_OUTPUT_TOKENS = 600

    # Artifact analysis: uses the heavier model (vision + more complex
    # structured reasoning than a single roleplay turn); called far less
    # often than roleplay turns so the extra cost/latency is acceptable.
    ANALYSIS_MODEL = os.environ.get("SYNTHESIS_MODEL", "claude-sonnet-5")
    ANALYSIS_MAX_OUTPUT_TOKENS = 1024
    ANALYSIS_TIMEOUT_SECONDS = 30
    ANALYSIS_MAX_ATTEMPTS = 2
    GENERATION_MAX_OUTPUT_TOKENS = 2048
    GENERATION_MAX_ATTEMPTS = 2
    MAX_ARTIFACT_TEXT_LENGTH = 4000
    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
    MAX_URL_LENGTH = 2000

    # In-memory per-IP rate limits. Deliberately conservative on the
    # Claude-calling and URL-fetching endpoints — both cost real money/API
    # quota and (for URL fetching) real network requests out of this server.
    RATELIMIT_DEFAULT = "200 per hour"
    RATELIMIT_ANALYZE = "20 per hour"
    RATELIMIT_GENERATE = "20 per hour"
    RATELIMIT_DECISIONS = "120 per hour"

    @classmethod
    def validate(cls):
        missing = []
        if not cls.SECRET_KEY:
            missing.append("FLASK_SECRET_KEY")
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill in real values."
            )
