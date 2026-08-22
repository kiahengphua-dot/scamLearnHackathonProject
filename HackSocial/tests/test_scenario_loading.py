import pytest

from app.scenarios.loader import get_scenario, list_scenario_summaries, load_all_scenarios
from app.scenarios.schema import ScenarioValidationError, validate_scenario_dict


def test_all_demo_scenarios_load():
    scenarios = load_all_scenarios(force_reload=True)
    assert len(scenarios) == 6


def test_scenario_ids_are_unique():
    scenarios = load_all_scenarios()
    assert len(scenarios) == len(set(scenarios.keys()))


def test_at_least_one_legitimate_and_one_scam_scenario():
    scenarios = load_all_scenarios()
    classifications = {s["classification"] for s in scenarios.values()}
    assert "SCAM" in classifications
    assert "LEGITIMATE" in classifications


def test_get_scenario_unknown_id_raises():
    with pytest.raises(KeyError):
        get_scenario("does-not-exist")


def test_get_scenario_known_id():
    scenario = get_scenario("workplace-hr-01")
    assert scenario["classification"] == "LEGITIMATE"


def test_summaries_never_expose_classification():
    summaries = list_scenario_summaries()
    assert len(summaries) == 6
    for s in summaries:
        assert "classification" not in s
        assert "id" in s and "title" in s and "category" in s


def test_validate_scenario_dict_rejects_missing_fields():
    with pytest.raises(ScenarioValidationError):
        validate_scenario_dict({"id": "broken"})


def test_validate_scenario_dict_rejects_bad_classification():
    scenario = dict(get_scenario("workplace-hr-01"))
    scenario["classification"] = "NOT_A_REAL_VALUE"
    with pytest.raises(ScenarioValidationError):
        validate_scenario_dict(scenario)


def test_validate_scenario_dict_rejects_mismatched_script_length():
    scenario = dict(get_scenario("banking-alert-01"))
    scenario["script"] = scenario["script"][:-1]  # drop one entry
    with pytest.raises(ScenarioValidationError):
        validate_scenario_dict(scenario)


def test_validate_scenario_dict_rejects_out_of_order_stages():
    scenario = dict(get_scenario("banking-alert-01"))
    scenario["allowed_stages"] = ["REQUEST", "CONTACT", "MANIPULATION"]
    with pytest.raises(ScenarioValidationError):
        validate_scenario_dict(scenario)
