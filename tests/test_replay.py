from app.engine.replay import build_replay


def _row(**kwargs):
    return kwargs


def test_replay_reconstructs_steps_in_turn_order():
    scenario = {"classification": "SCAM", "allowed_stages": ["CONTACT", "MANIPULATION", "REQUEST"]}
    messages = [
        _row(turn_number=0, speaker="scenario", content="initial msg", technique_used=None),
        _row(turn_number=0, speaker="user", content="I'll verify first", technique_used=None),
        _row(turn_number=1, speaker="scenario", content="urgency msg", technique_used="urgency"),
        _row(turn_number=1, speaker="user", content="[STOP]", technique_used=None),
    ]
    decisions = [
        _row(turn_number=0, action_type="VERIFY", score_delta=20, category="verification_behaviour", explanation="good"),
        _row(turn_number=1, action_type="STOP", score_delta=15, category="verification_behaviour", explanation="stopped"),
    ]

    replay = build_replay(scenario, messages, decisions)
    assert [s["turn"] for s in replay["steps"]] == [0, 1]
    assert replay["steps"][0]["stage"] == "CONTACT"
    assert replay["steps"][1]["stage"] == "MANIPULATION"
    assert replay["steps"][1]["technique_used"] == "urgency"


def test_replay_buckets_positive_and_negative_deltas():
    scenario = {"classification": "SCAM", "allowed_stages": ["CONTACT", "REQUEST"]}
    messages = [
        _row(turn_number=0, speaker="scenario", content="msg", technique_used=None),
        _row(turn_number=0, speaker="user", content="gave otp", technique_used=None),
    ]
    decisions = [
        _row(turn_number=0, action_type="CONTINUE", score_delta=-30, category="credential_harvesting", explanation="bad move"),
    ]
    replay = build_replay(scenario, messages, decisions)
    assert len(replay["what_you_missed"]) == 1
    assert replay["what_you_did_well"] == []


def test_intervention_point_missed_when_final_turn_is_negative():
    scenario = {"classification": "SCAM", "allowed_stages": ["CONTACT", "REQUEST"]}
    messages = [
        _row(turn_number=0, speaker="scenario", content="msg", technique_used=None),
        _row(turn_number=0, speaker="user", content="gave otp", technique_used=None),
    ]
    decisions = [
        _row(turn_number=0, action_type="CONTINUE", score_delta=-30, category="credential_harvesting", explanation="bad"),
    ]
    replay = build_replay(scenario, messages, decisions)
    assert replay["intervention_point"]["framing"] == "missed"


def test_intervention_point_caught_when_final_turn_is_positive():
    scenario = {"classification": "SCAM", "allowed_stages": ["CONTACT", "REQUEST"]}
    messages = [
        _row(turn_number=0, speaker="scenario", content="msg", technique_used=None),
        _row(turn_number=0, speaker="user", content="stop", technique_used=None),
    ]
    decisions = [
        _row(turn_number=0, action_type="STOP", score_delta=15, category="verification_behaviour", explanation="good"),
    ]
    replay = build_replay(scenario, messages, decisions)
    assert replay["intervention_point"]["framing"] == "caught"


def test_no_intervention_point_for_legitimate_scenario():
    scenario = {"classification": "LEGITIMATE", "allowed_stages": ["CONTACT", "REQUEST"]}
    messages = [
        _row(turn_number=0, speaker="scenario", content="msg", technique_used=None),
        _row(turn_number=0, speaker="user", content="continue", technique_used=None),
    ]
    decisions = [
        _row(turn_number=0, action_type="CONTINUE", score_delta=10, category="verification_behaviour", explanation="fine"),
    ]
    replay = build_replay(scenario, messages, decisions)
    assert replay["intervention_point"] is None
