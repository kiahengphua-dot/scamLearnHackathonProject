import json


def start_training_session(client, scenario_id="delivery-scam-01"):
    resp = client.post("/api/sessions", json={"mode": "train", "scenario_id": scenario_id})
    assert resp.status_code == 201
    return resp.get_json()


def test_train_scenarios_listing_hides_classification(client):
    resp = client.get("/api/scenarios?mode=train")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["scenarios"]) == 6
    for s in data["scenarios"]:
        assert "classification" not in s


def test_test_mode_listing_reveals_nothing(client):
    resp = client.get("/api/scenarios?mode=test")
    assert resp.status_code == 200
    assert "scenarios" not in resp.get_json()


def test_invalid_mode_rejected(client):
    resp = client.get("/api/scenarios?mode=bogus")
    assert resp.status_code == 400


def test_start_training_session_requires_scenario_id(client):
    resp = client.post("/api/sessions", json={"mode": "train"})
    assert resp.status_code == 400


def test_start_training_session_reveals_metadata_but_not_classification(client):
    data = start_training_session(client)
    assert data["title"] == "Unpaid Customs Fee"
    assert "classification" not in data
    assert data["status"] == "in_progress"
    assert "reasoning_score" not in data


def test_start_test_mode_session_picks_random_scenario_and_hides_metadata(client):
    resp = client.post("/api/sessions", json={"mode": "test"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert "title" not in data
    assert "category" not in data
    assert "message" in data


def test_full_playthrough_avoiding_scam_reveals_classification_at_end(client):
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]

    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "verify", "text": "I'll check the courier's official site"})
    data = resp.get_json()
    assert data["status"] == "in_progress"
    assert "reasoning_score" not in data
    assert "message" in data
    assert data["ai_generated"] is False  # Claude unconfigured in tests -> scripted fallback

    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "stop", "text": ""})
    data = resp.get_json()
    assert data["status"] == "completed"
    assert data["classification"] == "SCAM"
    assert data["outcome"] == "avoided_scam"


def test_providing_otp_ends_session_as_manipulated(client):
    session = start_training_session(client, "banking-alert-01")
    session_id = session["session_id"]

    client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "continue", "text": ""})
    resp = client.post(
        f"/api/sessions/{session_id}/decisions",
        json={"action_type": "continue", "text": "ok the otp is 445566"},
    )
    data = resp.get_json()
    assert data["status"] == "completed"
    assert data["outcome"] == "manipulated"
    assert data["classification"] == "SCAM"


def test_cannot_act_on_a_completed_session(client):
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]
    client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "stop", "text": ""})
    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "continue", "text": ""})
    assert resp.status_code == 409


def test_invalid_action_type_rejected(client):
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "HACK_THE_MAINFRAME", "text": ""})
    assert resp.status_code == 400


def test_client_cannot_inject_a_score_directly(client):
    """The API only accepts action_type/text — there is no field a client
    could pass to set reasoning_score, outcome, or status directly. The
    in-progress response doesn't even echo a score back."""
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]
    resp = client.post(
        f"/api/sessions/{session_id}/decisions",
        json={"action_type": "verify", "text": "", "reasoning_score": 9999, "outcome": "avoided_scam", "status": "completed"},
    )
    data = resp.get_json()
    assert "reasoning_score" not in data
    assert data["status"] == "in_progress"


def test_session_isolated_between_anonymous_users(client, app):
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]

    other_client = app.test_client()  # fresh client -> fresh anonymous cookie
    resp = other_client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "stop", "text": ""})
    assert resp.status_code == 404


def test_legitimate_scenario_full_playthrough(client):
    session = start_training_session(client, "workplace-hr-01")
    session_id = session["session_id"]

    client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "continue", "text": ""})
    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "continue", "text": ""})
    data = resp.get_json()
    assert data["status"] == "completed"
    assert data["classification"] == "LEGITIMATE"
    assert data["outcome"] == "handled_correctly"


FORBIDDEN_BEFORE_COMPLETION = [
    "classification",
    "scoring_rules",
    "success_conditions",
    "failure_conditions",
    "reasoning_score",
    "applied_rules",
    "manipulation_techniques",
    "expected_red_flags",
    "safe_verification_actions",
]


def test_test_mode_session_start_never_leaks_secrets(client):
    resp = client.post("/api/sessions", json={"mode": "test"})
    data = resp.get_json()
    for field in FORBIDDEN_BEFORE_COMPLETION + ["title", "category", "difficulty", "target_learning_objectives"]:
        assert field not in data, f"test-mode session start leaked {field!r}"


def test_train_mode_session_start_never_leaks_hidden_fields(client):
    # Train mode intentionally reveals title/category/difficulty/objectives —
    # only the truly hidden fields must stay absent.
    data = start_training_session(client, "banking-alert-01")
    for field in FORBIDDEN_BEFORE_COMPLETION:
        assert field not in data, f"train-mode session start leaked {field!r}"


def test_in_progress_decision_response_never_leaks_secrets(client):
    session = start_training_session(client, "banking-alert-01")
    session_id = session["session_id"]
    resp = client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "continue", "text": ""})
    data = resp.get_json()
    assert data["status"] == "in_progress"
    for field in FORBIDDEN_BEFORE_COMPLETION:
        assert field not in data, f"in-progress decision response leaked {field!r}"


def test_profile_reflects_completed_sessions(client):
    session = start_training_session(client, "delivery-scam-01")
    session_id = session["session_id"]
    client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "verify", "text": ""})
    client.post(f"/api/sessions/{session_id}/decisions", json={"action_type": "stop", "text": ""})

    resp = client.get("/api/profile")
    data = resp.get_json()
    assert "verification_behaviour" in data["skill_profile"]
    assert data["skill_profile"]["verification_behaviour"] > 50
