"""Tests for artifact analysis: schema validation, the analysis/generation
orchestrators, and the API endpoints. No real network calls — Claude is
mocked everywhere, same pattern as tests/test_ai_roleplay.py.
"""

import base64
import io
import json

import pytest

from app.artifacts import analysis as analysis_module
from app.artifacts import scenario_generator as generator_module
from app.artifacts.analysis import AnalysisUnavailableError, analyze_artifact
from app.artifacts.scenario_generator import GenerationUnavailableError, generate_scenario_from_analysis
from app.artifacts.schemas import AnalysisValidationError, GenerationValidationError, validate_analysis, validate_generation_raw

VALID_ANALYSIS_RAW = {
    "risk_assessment": "high",
    "confidence": 0.8,
    "indicators": [
        {"type": "urgency", "evidence": "Account will be locked in 15 minutes", "severity": "high"},
        {"type": "credential_request", "evidence": "asks for your one-time code", "severity": "high"},
    ],
    "possible_techniques": ["urgency", "authority"],
    "recommended_verification": ["Open your bank's official app directly"],
    "summary": "Evidence suggests urgency and credential-harvesting patterns consistent with a phishing attempt.",
}

VALID_GENERATION_RAW = {
    "title": "Account Verification Needed",
    "category": "banking",
    "context": "A fictional bank, Northfield Trust, contacts the user about account activity.",
    "classification": "SCAM",
    "difficulty": "beginner",
    "manipulation_techniques": ["urgency", "authority"],
    "dangerous_category": "credential_harvesting",
    "stages": [
        {"stage": "CONTACT", "message": "Northfield Trust: unusual sign-in detected on your account."},
        {"stage": "MANIPULATION", "message": "Your account will be suspended in 10 minutes unless verified.", "technique": "urgency"},
        {"stage": "REQUEST", "message": "Reply with the 6-digit code sent to your phone to cancel the suspension."},
    ],
    "expected_red_flags": ["Countdown pressure", "Request for a one-time code"],
    "safe_verification_actions": ["Log in via the bank's official app instead"],
    "dangerous_phrases": ["the code is", "here's my otp"],
    "safe_phrases": ["official app", "call the bank"],
}


def make_config(**overrides):
    base = {
        "ANTHROPIC_API_KEY": "fake-configured-key",
        "ANALYSIS_MODEL": "claude-sonnet-5",
        "ANALYSIS_MAX_OUTPUT_TOKENS": 1024,
        "ANALYSIS_TIMEOUT_SECONDS": 30,
        "ANALYSIS_MAX_ATTEMPTS": 2,
        "GENERATION_MAX_OUTPUT_TOKENS": 2048,
        "GENERATION_MAX_ATTEMPTS": 2,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_valid_analysis_passes_validation():
    validated = validate_analysis(VALID_ANALYSIS_RAW)
    assert validated["risk_assessment"] == "high"
    assert validated["confidence"] == 0.8


def test_analysis_rejects_bad_confidence():
    bad = dict(VALID_ANALYSIS_RAW, confidence=1.5)
    with pytest.raises(AnalysisValidationError):
        validate_analysis(bad)


def test_analysis_rejects_overconfident_summary():
    bad = dict(VALID_ANALYSIS_RAW, summary="This is definitely a scam, 100% a scam.")
    with pytest.raises(AnalysisValidationError):
        validate_analysis(bad)


def test_analysis_rejects_invalid_indicator_type():
    bad = json.loads(json.dumps(VALID_ANALYSIS_RAW))
    bad["indicators"][0]["type"] = "not_a_real_indicator"
    with pytest.raises(AnalysisValidationError):
        validate_analysis(bad)


def test_valid_generation_raw_passes():
    validated = validate_generation_raw(VALID_GENERATION_RAW)
    assert validated["classification"] == "SCAM"


def test_generation_rejects_scam_with_no_dangerous_category():
    bad = dict(VALID_GENERATION_RAW, dangerous_category="none")
    with pytest.raises(GenerationValidationError):
        validate_generation_raw(bad)


def test_generation_rejects_out_of_order_stages():
    bad = json.loads(json.dumps(VALID_GENERATION_RAW))
    bad["stages"] = [bad["stages"][2], bad["stages"][0], bad["stages"][1]]
    with pytest.raises(GenerationValidationError):
        validate_generation_raw(bad)


def test_generation_rejects_too_few_stages():
    bad = dict(VALID_GENERATION_RAW, stages=[VALID_GENERATION_RAW["stages"][0]])
    with pytest.raises(GenerationValidationError):
        validate_generation_raw(bad)


# ---------------------------------------------------------------------------
# analyze_artifact orchestration
# ---------------------------------------------------------------------------

def test_analyze_artifact_raises_when_unconfigured():
    with pytest.raises(AnalysisUnavailableError):
        analyze_artifact({"ANTHROPIC_API_KEY": "your_api_key_here"}, "text", text="hello")


def test_analyze_artifact_success(monkeypatch):
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)
    result = analyze_artifact(make_config(), "text", text="Your account will be suspended, click here now")
    assert result["risk_assessment"] == "high"


def test_analyze_artifact_falls_back_to_unavailable_after_malformed_retries(monkeypatch):
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: {"risk_assessment": "not_valid"})
    with pytest.raises(AnalysisUnavailableError):
        analyze_artifact(make_config(), "text", text="hi")


def test_analyze_artifact_handles_none_from_call_tool(monkeypatch):
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: None)
    with pytest.raises(AnalysisUnavailableError):
        analyze_artifact(make_config(), "text", text="hi")


# ---------------------------------------------------------------------------
# generate_scenario_from_analysis orchestration
# ---------------------------------------------------------------------------

def test_generate_scenario_success(monkeypatch):
    monkeypatch.setattr(generator_module, "call_tool", lambda *a, **k: VALID_GENERATION_RAW)
    analysis = validate_analysis(VALID_ANALYSIS_RAW)
    scenario = generate_scenario_from_analysis(make_config(), analysis)
    assert scenario["classification"] == "SCAM"
    assert scenario["id"].startswith("generated-")
    assert scenario["allowed_stages"] == ["CONTACT", "MANIPULATION", "REQUEST"]
    assert scenario["scoring_rules"]  # deterministically assembled, not from Claude


def test_generate_scenario_rejects_real_entity_names(monkeypatch):
    tainted = json.loads(json.dumps(VALID_GENERATION_RAW))
    tainted["context"] = "PayPal support contacts the user about a frozen account."

    monkeypatch.setattr(generator_module, "call_tool", lambda *a, **k: tainted)
    with pytest.raises(GenerationUnavailableError):
        generate_scenario_from_analysis(make_config(GENERATION_MAX_ATTEMPTS=1), validate_analysis(VALID_ANALYSIS_RAW))


def test_generate_scenario_unavailable_when_unconfigured():
    with pytest.raises(GenerationUnavailableError):
        generate_scenario_from_analysis({"ANTHROPIC_API_KEY": "your_api_key_here"}, validate_analysis(VALID_ANALYSIS_RAW))


def test_generated_scenario_is_playable_by_existing_engine(monkeypatch):
    """The whole point of the design: a generated scenario must work with
    the exact same deterministic engine as the static ones."""
    from app.engine.state_machine import apply_decision, create_session_state

    monkeypatch.setattr(generator_module, "call_tool", lambda *a, **k: VALID_GENERATION_RAW)
    scenario = generate_scenario_from_analysis(make_config(), validate_analysis(VALID_ANALYSIS_RAW))

    state = create_session_state(scenario)
    state = apply_decision(scenario, state, "CONTINUE", "")
    state = apply_decision(scenario, state, "CONTINUE", "here's my otp 123456")
    assert state["status"] == "completed"
    assert state["outcome"] == "manipulated"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def test_analyze_text_endpoint(client, app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "Your account will be suspended in 30 minutes"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert "analysis_id" in data
    assert data["risk_assessment"] == "high"
    assert "classification" not in data  # analysis is evidence, never a scenario verdict


def test_analyze_rejects_empty_text(client):
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": ""})
    assert resp.status_code == 400


def test_analyze_rejects_oversized_text(client, app):
    app.config["MAX_ARTIFACT_TEXT_LENGTH"] = 10
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "way too long for the limit"})
    assert resp.status_code == 400


def test_analyze_rejects_invalid_type(client):
    resp = client.post("/api/artifacts/analyze", json={"type": "video", "text": "hi"})
    assert resp.status_code == 400


def test_analyze_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: None)
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "hello there"})
    assert resp.status_code == 503


def test_analyze_screenshot_endpoint(client, app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)
    fake_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    data = {"type": "screenshot", "image": (io.BytesIO(fake_png), "test.png", "image/png")}
    resp = client.post("/api/artifacts/analyze", content_type="multipart/form-data", data=data)
    assert resp.status_code == 201
    assert resp.get_json()["risk_assessment"] == "high"


def test_analyze_screenshot_rejects_disallowed_type(client):
    data = {"type": "screenshot", "image": (io.BytesIO(b"not really a gif"), "test.gif", "image/gif")}
    resp = client.post("/api/artifacts/analyze", content_type="multipart/form-data", data=data)
    assert resp.status_code == 400


def test_analyze_screenshot_requires_file(client):
    resp = client.post("/api/artifacts/analyze", content_type="multipart/form-data", data={"type": "screenshot"})
    assert resp.status_code == 400


def start_generated_scenario(client, app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "urgent account suspension notice"})
    analysis_id = resp.get_json()["analysis_id"]

    monkeypatch.setattr(generator_module, "call_tool", lambda *a, **k: VALID_GENERATION_RAW)
    resp = client.post(f"/api/artifacts/{analysis_id}/generate-scenario", json={})
    return resp


def test_generate_scenario_endpoint_hides_classification(client, app, monkeypatch):
    resp = start_generated_scenario(client, app, monkeypatch)
    assert resp.status_code == 201
    data = resp.get_json()
    assert "classification" not in data
    assert "scoring_rules" not in data
    assert data["title"] == "Account Verification Needed"


def test_generate_scenario_unknown_analysis_id_404(client):
    resp = client.post("/api/artifacts/does-not-exist/generate-scenario", json={})
    assert resp.status_code == 404


def test_generate_scenario_analysis_isolated_between_users(client, app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(analysis_module, "call_tool", lambda *a, **k: VALID_ANALYSIS_RAW)
    resp = client.post("/api/artifacts/analyze", json={"type": "text", "text": "urgent account suspension notice"})
    analysis_id = resp.get_json()["analysis_id"]

    other_client = app.test_client()
    resp = other_client.post(f"/api/artifacts/{analysis_id}/generate-scenario", json={})
    assert resp.status_code == 404


def test_full_flow_generated_scenario_playable_via_sessions_api(client, app, monkeypatch):
    resp = start_generated_scenario(client, app, monkeypatch)
    scenario_id = resp.get_json()["scenario_id"]

    resp = client.post("/api/sessions", json={"mode": "train", "scenario_id": scenario_id})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["title"] == "Account Verification Needed"
    assert "classification" not in data
    session_id = data["session_id"]

    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "stop", "text": ""})
    data = resp.get_json()
    assert data["status"] == "completed"
    assert data["classification"] == "SCAM"
    assert data["outcome"] == "avoided_scam"


def test_generated_scenario_cannot_be_started_in_test_mode(client, app, monkeypatch):
    """Test mode always draws from the curated static set — starting your
    own generated scenario there would defeat the blind-test purpose."""
    resp = start_generated_scenario(client, app, monkeypatch)
    scenario_id = resp.get_json()["scenario_id"]

    resp = client.post("/api/sessions", json={"mode": "test", "scenario_id": scenario_id})
    assert resp.status_code == 201
    data = resp.get_json()
    assert "title" not in data  # test mode never reveals scenario identity regardless of what was requested


def test_generated_scenario_isolated_between_users_for_sessions(client, app, monkeypatch):
    resp = start_generated_scenario(client, app, monkeypatch)
    scenario_id = resp.get_json()["scenario_id"]

    other_client = app.test_client()
    resp = other_client.post("/api/sessions", json={"mode": "train", "scenario_id": scenario_id})
    assert resp.status_code == 400  # not visible to another user, same as an unknown scenario_id
