from app.artifacts import analysis as analysis_module
from app.routes import artifacts as artifacts_route_module

VALID_ANALYSIS_RAW = {
    "risk_assessment": "high",
    "confidence": 0.85,
    "indicators": [
        {"type": "credential_request", "evidence": "login form asks for password", "severity": "high"},
    ],
    "possible_techniques": ["phishing"],
    "recommended_verification": ["Do not enter credentials on this page"],
    "summary": "Evidence suggests a credential-harvesting page.",
}


def _configure_and_mock(app, monkeypatch, html="<html><head><title>Login</title></head><body>Sign in</body></html>", final_url=None):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(
        artifacts_route_module, "fetch_url_safely", lambda url: (html, final_url or url)
    )
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)


def test_url_analysis_success(client, app, monkeypatch):
    _configure_and_mock(app, monkeypatch)
    resp = client.post("/api/artifacts/analyze", json={"type": "url", "url": "http://example.com/login"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["risk_assessment"] == "high"
    assert "analysis_id" in data


def test_url_analysis_requires_url_field(client):
    resp = client.post("/api/artifacts/analyze", json={"type": "url"})
    assert resp.status_code == 400


def test_url_analysis_rejects_oversized_url(client, app):
    app.config["MAX_URL_LENGTH"] = 10
    resp = client.post("/api/artifacts/analyze", json={"type": "url", "url": "http://example.com/way-too-long-path"})
    assert resp.status_code == 400


def test_url_fetch_failure_returns_generic_error_message(client, app, monkeypatch):
    from app.artifacts.url_fetcher import URLFetchError

    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"

    def raise_fetch_error(url):
        raise URLFetchError("resolved address not allowed")  # e.g. an SSRF block

    monkeypatch.setattr(artifacts_route_module, "fetch_url_safely", raise_fetch_error)
    resp = client.post("/api/artifacts/analyze", json={"type": "url", "url": "http://169.254.169.254/"})
    assert resp.status_code == 400
    data = resp.get_json()
    # The specific reason (SSRF-blocked vs DNS failure vs timeout) must
    # never be distinguishable from the API response.
    assert "resolved address" not in data["error"]
    assert "not allowed" not in data["error"]
    assert data["error"] == "This URL could not be analyzed. It may be unreachable, blocked, or too large."


def test_url_analysis_full_flow_to_generated_scenario(client, app, monkeypatch):
    from app.artifacts import scenario_generator as generator_module

    _configure_and_mock(app, monkeypatch, html="<html><head><title>Verify Account</title></head><body>Enter your password</body></html>")

    resp = client.post("/api/artifacts/analyze", json={"type": "url", "url": "http://example.com/verify"})
    analysis_id = resp.get_json()["analysis_id"]

    generation_raw = {
        "title": "Suspicious Verification Page",
        "category": "banking",
        "context": "A fictional bank verification page.",
        "classification": "SCAM",
        "difficulty": "beginner",
        "manipulation_techniques": ["authority"],
        "dangerous_category": "credential_harvesting",
        "stages": [
            {"stage": "CONTACT", "message": "Please verify your account."},
            {"stage": "REQUEST", "message": "Enter your password to continue."},
        ],
        "expected_red_flags": ["unexpected verification request"],
        "safe_verification_actions": ["Log in via the official app"],
        "dangerous_phrases": ["entered my password"],
        "safe_phrases": ["used the official app"],
    }
    monkeypatch.setattr(generator_module, "call_tool", lambda *a, **k: generation_raw)

    resp = client.post(f"/api/artifacts/{analysis_id}/generate-scenario", json={})
    assert resp.status_code == 201
    assert resp.get_json()["title"] == "Suspicious Verification Page"
