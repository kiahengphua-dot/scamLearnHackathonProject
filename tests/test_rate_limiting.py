"""Rate limiting is disabled for the rest of the suite (see conftest.py)
so other tests can hammer endpoints in tight loops. This file explicitly
re-enables it against a fresh app instance to prove the limiter actually
enforces a 429, since that's the entire point of the earlier audit
finding it fixes."""

import pytest

from app import create_app
from tests.conftest import TestConfig


class StrictLimitConfig(TestConfig):
    TESTING = False  # so create_app's default doesn't disable rate limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_ANALYZE = "2 per hour"
    RATELIMIT_DEFAULT = "1000 per hour"


@pytest.fixture
def strict_app(tmp_path):
    StrictLimitConfig.DB_PATH = tmp_path / "strict.db"
    application = create_app(config_class=StrictLimitConfig)
    application.config.update(TESTING=True)  # test client behaves correctly, but limiter already initialized as enabled
    yield application


def test_analyze_endpoint_returns_429_after_exceeding_limit(strict_app):
    client = strict_app.test_client()
    for _ in range(2):
        resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "hello there"})
        assert resp.status_code in (400, 503, 201)  # unconfigured Claude -> 503, but limiter hasn't tripped yet

    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "hello there"})
    assert resp.status_code == 429
