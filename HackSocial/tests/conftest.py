import tempfile
from pathlib import Path

import pytest

from app import create_app
from app.config import Config


class TestConfig(Config):
    SECRET_KEY = "test-secret-key"
    # Deliberately "unconfigured" so the default test suite exercises the
    # scripted fallback path and never makes a real network call. Tests
    # that specifically exercise the Claude integration mock the client
    # and override this per-test (see test_ai_roleplay.py).
    ANTHROPIC_API_KEY = "your_api_key_here"
    # Set on the class (not via app.config.update after the fact) so
    # create_app() sees it in time to skip enabling rate limiting — tests
    # intentionally hammer the same endpoints in tight loops.
    TESTING = True


@pytest.fixture
def app(tmp_path):
    TestConfig.DB_PATH = tmp_path / "test.db"
    application = create_app(config_class=TestConfig)
    application.config.update(TESTING=True)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()
