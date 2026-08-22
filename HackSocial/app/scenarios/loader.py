import json
from pathlib import Path

from app.scenarios.schema import ScenarioValidationError, validate_scenario_dict

DATA_DIR = Path(__file__).resolve().parent / "data"

_cache = None


def load_all_scenarios(force_reload=False):
    """Load and validate every scenario JSON file in scenarios/data.

    Returns a dict keyed by scenario id. Cached after first load since
    scenario content is static, version-controlled data, not user input.
    """
    global _cache
    if _cache is not None and not force_reload:
        return _cache

    scenarios = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        try:
            validate_scenario_dict(data)
        except ScenarioValidationError as e:
            raise ScenarioValidationError(f"Invalid scenario file {path.name}: {e}") from e

        if data["id"] in scenarios:
            raise ScenarioValidationError(f"Duplicate scenario id {data['id']!r} found in {path.name}")

        scenarios[data["id"]] = data

    _cache = scenarios
    return scenarios


def get_scenario(scenario_id):
    scenarios = load_all_scenarios()
    if scenario_id not in scenarios:
        raise KeyError(f"Unknown scenario id: {scenario_id}")
    return scenarios[scenario_id]


def list_scenario_summaries(mode=None):
    """Metadata safe to show a user before they start — never includes
    classification (SCAM/LEGITIMATE), which must stay server-side only
    until the scenario is resolved."""
    scenarios = load_all_scenarios()
    summaries = []
    for s in scenarios.values():
        summaries.append(
            {
                "id": s["id"],
                "title": s["title"],
                "category": s["category"],
                "difficulty": s["difficulty"],
                "target_learning_objectives": s["target_learning_objectives"],
                "manipulation_techniques": s["manipulation_techniques"],
            }
        )
    return summaries
