from app.engine.scoring import BASELINE_SCORE, apply_score, detect_triggers, score_triggers
from app.scenarios.loader import get_scenario


def test_detect_triggers_includes_action_trigger():
    scenario = get_scenario("banking-alert-01")
    triggers = detect_triggers(scenario, "VERIFY", "")
    assert "action:verify" in triggers


def test_detect_triggers_matches_keyword_case_insensitively():
    scenario = get_scenario("banking-alert-01")
    triggers = detect_triggers(scenario, "CONTINUE", "Sure, the OTP is fine to share right?")
    assert "keyword:provides_otp" in triggers


def test_detect_triggers_ignores_unmapped_action():
    scenario = get_scenario("workplace-hr-01")  # has no keyword triggers defined
    triggers = detect_triggers(scenario, "CONTINUE", "here is my card number 1234")
    assert triggers == ["action:continue"]


def test_score_triggers_deduplicates_same_trigger():
    scenario = get_scenario("banking-alert-01")
    applied = score_triggers(scenario, ["action:verify", "action:verify"])
    assert len(applied) == 1


def test_apply_score_clamps_to_max():
    scenario = get_scenario("banking-alert-01")
    applied = score_triggers(scenario, ["action:verify"] * 10)  # deduped to one rule internally per call
    total = BASELINE_SCORE
    for _ in range(10):
        total = apply_score(total, score_triggers(scenario, ["action:verify"]))
    assert total <= 100


def test_apply_score_clamps_to_min():
    scenario = get_scenario("banking-alert-01")
    total = BASELINE_SCORE
    for _ in range(10):
        total = apply_score(total, score_triggers(scenario, ["keyword:provides_otp"]))
    assert total >= 0


def test_terminal_flag_present_on_dangerous_trigger():
    scenario = get_scenario("banking-alert-01")
    applied = score_triggers(scenario, ["keyword:provides_otp"])
    assert applied[0]["terminal"] is True


def test_terminal_flag_absent_on_safe_trigger():
    scenario = get_scenario("banking-alert-01")
    applied = score_triggers(scenario, ["action:verify"])
    assert applied[0]["terminal"] is False
