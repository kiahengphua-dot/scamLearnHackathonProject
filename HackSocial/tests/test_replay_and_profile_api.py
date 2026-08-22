from app.ai import replay_narrative as replay_narrative_module


def start_and_finish(client, scenario_id, decisions):
    resp = client.post("/api/sessions", json={"mode": "train", "scenario_id": scenario_id})
    session_id = resp.get_json()["session_id"]
    last = None
    for action_type, text in decisions:
        last = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": action_type, "text": text})
    return session_id, last


def test_replay_unavailable_before_completion(client):
    resp = client.post("/api/sessions", json={"mode": "train", "scenario_id": "delivery-scam-01"})
    session_id = resp.get_json()["session_id"]
    resp = client.get(f"/api/sessions/{session_id}/replay")
    assert resp.status_code == 409


def test_replay_404_for_unknown_session(client):
    resp = client.get("/api/sessions/99999/replay")
    assert resp.status_code == 404


def test_replay_returns_full_structure_after_completion(client):
    session_id, last = start_and_finish(client, "delivery-scam-01", [("stop", "")])
    assert last.get_json()["status"] == "completed"

    resp = client.get(f"/api/sessions/{session_id}/replay")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["classification"] == "SCAM"
    assert data["outcome"] == "avoided_scam"
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1
    assert data["intervention_point"]["framing"] == "caught"
    assert data["lesson_to_remember"]
    assert data["narrative_ai_generated"] is False  # Claude unconfigured in tests


def test_replay_uses_ai_narrative_when_available(client, app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "fake-configured-key"
    monkeypatch.setattr(
        replay_narrative_module,
        "call_tool",
        lambda *a, **k: {"narrative": "You handled this well by verifying independently.", "lesson_to_remember": "Verify before you trust."},
    )
    session_id, _ = start_and_finish(client, "delivery-scam-01", [("stop", "")])
    resp = client.get(f"/api/sessions/{session_id}/replay")
    data = resp.get_json()
    assert data["narrative_ai_generated"] is True
    assert data["lesson_to_remember"] == "Verify before you trust."


def test_replay_isolated_between_users(client, app):
    session_id, _ = start_and_finish(client, "delivery-scam-01", [("stop", "")])
    other_client = app.test_client()
    resp = other_client.get(f"/api/sessions/{session_id}/replay")
    assert resp.status_code == 404


def test_profile_includes_new_fields(client):
    session_id, _ = start_and_finish(client, "delivery-scam-01", [("verify", ""), ("stop", "")])
    resp = client.get("/api/profile")
    data = resp.get_json()
    assert "overall_proficiency" in data
    assert "strongest_category" in data
    assert "recommended" in data
    assert data["recommended"]["scenario_id"]
    assert "achievements" in data
    keys = {a["key"] for a in data["achievements"]}
    assert "first_scenario_completed" in keys
    assert "scam_spotter" in keys


def test_newly_earned_achievements_surfaced_on_completion(client):
    session_id, last = start_and_finish(client, "delivery-scam-01", [("stop", "")])
    data = last.get_json()
    assert "first_scenario_completed" in data["newly_earned_achievements"]
