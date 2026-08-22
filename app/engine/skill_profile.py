"""Adaptive skill profile updates (spec section 18).

Proficiency per category is nudged toward good/bad outcomes each time a
scoring rule in that category fires. This is intentionally a simple moving
average, not machine learning — enough to demonstrate real adaptation
without over-building for the MVP.
"""

DEFAULT_PROFICIENCY = 50
LEARNING_RATE = 0.2
MIN_PROFICIENCY = 0
MAX_PROFICIENCY = 100


def update_profile_for_session(db, user_id, applied_rules_log):
    """applied_rules_log: list of {turn, action_type, applied_rules: [...]}
    as produced by the state machine over a whole session."""
    category_deltas = {}
    for turn in applied_rules_log:
        for rule in turn["applied_rules"]:
            category_deltas.setdefault(rule["category"], []).append(rule["delta"])

    for category, deltas in category_deltas.items():
        row = db.execute(
            "SELECT proficiency FROM skill_profiles WHERE user_id = ? AND category = ?",
            (user_id, category),
        ).fetchone()
        current = row["proficiency"] if row else DEFAULT_PROFICIENCY

        # A positive delta this session nudges proficiency up; negative
        # nudges it down. Averaged across the session's occurrences of the
        # category so one lucky/unlucky turn doesn't swing it too far.
        avg_delta = sum(deltas) / len(deltas)
        direction = 1 if avg_delta > 0 else (-1 if avg_delta < 0 else 0)
        magnitude = min(abs(avg_delta), 30)  # cap a single session's influence
        new_value = current + direction * magnitude * LEARNING_RATE
        new_value = max(MIN_PROFICIENCY, min(MAX_PROFICIENCY, round(new_value)))

        if row:
            db.execute(
                "UPDATE skill_profiles SET proficiency = ?, updated_at = datetime('now') "
                "WHERE user_id = ? AND category = ?",
                (new_value, user_id, category),
            )
        else:
            db.execute(
                "INSERT INTO skill_profiles (user_id, category, proficiency) VALUES (?, ?, ?)",
                (user_id, category, new_value),
            )
    db.commit()


def get_profile(db, user_id):
    rows = db.execute(
        "SELECT category, proficiency FROM skill_profiles WHERE user_id = ? ORDER BY category",
        (user_id,),
    ).fetchall()
    return {row["category"]: row["proficiency"] for row in rows}


def weakest_category(db, user_id):
    profile = get_profile(db, user_id)
    if not profile:
        return None
    return min(profile, key=profile.get)


def strongest_category(db, user_id):
    profile = get_profile(db, user_id)
    if not profile:
        return None
    return max(profile, key=profile.get)


def overall_proficiency(db, user_id):
    profile = get_profile(db, user_id)
    if not profile:
        return None
    return round(sum(profile.values()) / len(profile))


def build_category_scenario_index():
    """category -> list of static scenario ids that exercise it, derived
    from each scenario's own scoring_rules — no manually-maintained mapping
    to drift out of sync with the actual scenario content."""
    from app.scenarios.loader import load_all_scenarios

    index = {}
    for scenario in load_all_scenarios().values():
        categories = {rule["category"] for rule in scenario["scoring_rules"]}
        for category in categories:
            index.setdefault(category, []).append(scenario["id"])
    return index


DEFAULT_RECOMMENDATION_SCENARIO_ID = "banking-alert-01"


def recommend_scenario(db, user_id):
    """A concrete next scenario targeting the user's weakest category, per
    spec section 19 — never a random suggestion. Falls back to a sensible
    beginner scenario for a brand-new user with no profile yet."""
    from app.scenarios.loader import get_scenario

    category = weakest_category(db, user_id)
    if category is None:
        scenario_id = DEFAULT_RECOMMENDATION_SCENARIO_ID
        reason = "Start here to build your baseline profile."
    else:
        index = build_category_scenario_index()
        candidates = index.get(category, [DEFAULT_RECOMMENDATION_SCENARIO_ID])
        scenario_id = candidates[0]
        reason = f"You've struggled most with {category.replace('_', ' ')} — this scenario targets it directly."

    scenario = get_scenario(scenario_id)
    return {
        "scenario_id": scenario_id,
        "title": scenario["title"],
        "category": scenario["category"],
        "difficulty": scenario["difficulty"],
        "reason": reason,
        "target_category": category,
    }
