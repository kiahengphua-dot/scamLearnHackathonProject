import pytest

from app.engine import outcome as outcome_module
from app.engine.state_machine import (
    InvalidActionError,
    apply_decision,
    create_session_state,
    next_scenario_message,
)
from app.scenarios.loader import get_scenario


def test_initial_state_starts_at_first_stage():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    assert state["stage"] == "CONTACT"
    assert state["turn_count"] == 0
    assert state["status"] == "in_progress"
    assert state["reasoning_score"] == 50


def test_initial_message_matches_scenario():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    assert next_scenario_message(scenario, state) == scenario["initial_message"]


def test_continue_advances_stage():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "CONTINUE", "")
    assert state["stage"] == "MANIPULATION"
    assert state["turn_count"] == 1
    assert state["status"] == "in_progress"


def test_stop_ends_scam_scenario_as_avoided():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "STOP", "")
    assert state["status"] == "completed"
    assert state["outcome"] == outcome_module.OUTCOME_AVOIDED_SCAM


def test_stop_on_legitimate_scenario_is_overly_cautious():
    scenario = get_scenario("workplace-hr-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "STOP", "")
    assert state["outcome"] == outcome_module.OUTCOME_OVERLY_CAUTIOUS


def test_providing_otp_triggers_immediate_manipulated_outcome():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "CONTINUE", "")  # -> MANIPULATION
    apply_decision(scenario, state, "CONTINUE", "The otp code is 123456")  # -> REQUEST + provides_otp
    assert state["status"] == "completed"
    assert state["outcome"] == outcome_module.OUTCOME_MANIPULATED
    assert state["reasoning_score"] < 50


def test_verifying_independently_increases_score_without_ending_session():
    scenario = get_scenario("banking-alert-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "VERIFY", "I'll check the bank's official app instead")
    assert state["status"] == "in_progress"
    assert state["reasoning_score"] > 50


def test_turns_exhausted_resolves_scenario():
    scenario = get_scenario("delivery-scam-01")  # 2 stages -> resolves after both are consumed
    state = create_session_state(scenario)
    apply_decision(scenario, state, "CONTINUE", "")
    assert state["status"] == "in_progress"
    apply_decision(scenario, state, "CONTINUE", "")
    assert state["status"] == "completed"
    assert state["outcome"] == outcome_module.OUTCOME_AVOIDED_SCAM


def test_cannot_act_on_completed_session():
    scenario = get_scenario("delivery-scam-01")
    state = create_session_state(scenario)
    apply_decision(scenario, state, "STOP", "")
    with pytest.raises(InvalidActionError):
        apply_decision(scenario, state, "CONTINUE", "")


def test_unknown_action_type_rejected():
    scenario = get_scenario("delivery-scam-01")
    state = create_session_state(scenario)
    with pytest.raises(InvalidActionError):
        apply_decision(scenario, state, "DO_SOMETHING_WEIRD", "")


def test_legitimate_scenario_handled_correctly_when_user_continues():
    scenario = get_scenario("workplace-hr-01")  # 2 stages
    state = create_session_state(scenario)
    apply_decision(scenario, state, "CONTINUE", "")
    apply_decision(scenario, state, "CONTINUE", "")
    assert state["status"] == "completed"
    assert state["outcome"] == outcome_module.OUTCOME_HANDLED_CORRECTLY
