from app.engine.achievements import check_and_award_achievements, get_achievements
from app.engine.skill_profile import (
    build_category_scenario_index,
    overall_proficiency,
    recommend_scenario,
    strongest_category,
    update_profile_for_session,
)
from app.scenarios.loader import get_scenario


def _make_user(app_ctx_db, cookie="test-user"):
    cursor = app_ctx_db.execute("INSERT INTO users (cookie_token) VALUES (?)", (cookie,))
    app_ctx_db.commit()
    return cursor.lastrowid


def _record_completed_session(db, user_id, scenario_id="delivery-scam-01"):
    """check_and_award_achievements() checks the sessions table to detect a
    user's first completion — in the real API flow that row is always
    already marked completed by the time achievements are checked, so
    tests need to set up the same precondition."""
    db.execute(
        "INSERT INTO sessions (user_id, scenario_id, mode, state_json, status) "
        "VALUES (?, ?, 'train', '{}', 'completed')",
        (user_id, scenario_id),
    )
    db.commit()


def _fake_state(reasoning_score=50, outcome="avoided_scam"):
    return {"reasoning_score": reasoning_score, "outcome": outcome}


def test_first_completion_awards_getting_started(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        scenario = get_scenario("delivery-scam-01")
        _record_completed_session(db, user_id)

        earned = check_and_award_achievements(db, user_id, scenario, _fake_state())
        assert "first_scenario_completed" in earned
        assert "scam_spotter" in earned


def test_achievement_not_awarded_twice(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        scenario = get_scenario("delivery-scam-01")

        check_and_award_achievements(db, user_id, scenario, _fake_state())
        second = check_and_award_achievements(db, user_id, scenario, _fake_state())
        # first_scenario_completed and scam_spotter both already earned
        assert "first_scenario_completed" not in second
        assert "scam_spotter" not in second


def test_perfect_reasoning_achievement(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        scenario = get_scenario("delivery-scam-01")

        earned = check_and_award_achievements(db, user_id, scenario, _fake_state(reasoning_score=100))
        assert "perfect_reasoning" in earned


def test_advanced_resistance_achievement_requires_advanced_difficulty(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        advanced_scenario = get_scenario("investment-scam-01")  # difficulty: advanced

        earned = check_and_award_achievements(db, user_id, advanced_scenario, _fake_state(outcome="avoided_scam"))
        assert "advanced_resistance" in earned


def test_well_calibrated_achievement_for_legitimate_scenario(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        legit_scenario = get_scenario("workplace-hr-01")

        earned = check_and_award_achievements(db, user_id, legit_scenario, _fake_state(outcome="handled_correctly"))
        assert "well_calibrated" in earned


def test_artifact_investigator_achievement_for_generated_scenario(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        generated_scenario = dict(get_scenario("delivery-scam-01"), source="artifact_analysis")

        earned = check_and_award_achievements(db, user_id, generated_scenario, _fake_state())
        assert "artifact_investigator" in earned


def test_get_achievements_returns_titles(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        scenario = get_scenario("delivery-scam-01")
        _record_completed_session(db, user_id)
        check_and_award_achievements(db, user_id, scenario, _fake_state())

        achievements = get_achievements(db, user_id)
        keys = {a["key"] for a in achievements}
        assert "first_scenario_completed" in keys
        assert all(a["title"] for a in achievements)


def test_category_scenario_index_maps_known_categories():
    index = build_category_scenario_index()
    assert "credential_harvesting" in index
    assert "banking-alert-01" in index["credential_harvesting"]


def test_recommend_scenario_defaults_for_new_user(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        rec = recommend_scenario(db, user_id)
        assert rec["scenario_id"] == "banking-alert-01"
        assert rec["target_category"] is None


def test_recommend_scenario_targets_weakest_category(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        # Simulate a session log that hurts credential_harvesting badly.
        update_profile_for_session(db, user_id, [
            {"turn": 0, "action_type": "CONTINUE", "applied_rules": [
                {"category": "credential_harvesting", "delta": -30, "explanation": "bad"}
            ]},
        ])
        rec = recommend_scenario(db, user_id)
        assert rec["target_category"] == "credential_harvesting"
        assert rec["scenario_id"] == "banking-alert-01"


def test_overall_and_strongest_category(app):
    with app.app_context():
        from app.db import get_db
        db = get_db()
        user_id = _make_user(db)
        update_profile_for_session(db, user_id, [
            {"turn": 0, "action_type": "VERIFY", "applied_rules": [
                {"category": "verification_behaviour", "delta": 20, "explanation": "good"}
            ]},
            {"turn": 1, "action_type": "CONTINUE", "applied_rules": [
                {"category": "credential_harvesting", "delta": -30, "explanation": "bad"}
            ]},
        ])
        assert strongest_category(db, user_id) == "verification_behaviour"
        overall = overall_proficiency(db, user_id)
        assert overall is not None
