"""Prototype achievement system (spec section 21).

Every trigger here is a deterministic check against data the backend
already owns (session outcome, score, scenario metadata) — never
something Claude decides. These are demo/local rewards only; no real
vouchers or payments are involved.
"""

ACHIEVEMENTS = {
    "first_scenario_completed": {
        "title": "Getting Started",
        "description": "Completed your first ScamLearn scenario.",
    },
    "scam_spotter": {
        "title": "Scam Spotter",
        "description": "Successfully avoided a simulated scam.",
    },
    "perfect_reasoning": {
        "title": "Perfect Reasoning",
        "description": "Finished a scenario with a 100/100 reasoning score.",
    },
    "advanced_resistance": {
        "title": "Held Your Ground",
        "description": "Avoided a scam in an advanced-difficulty scenario.",
    },
    "well_calibrated": {
        "title": "Well Calibrated",
        "description": "Correctly handled a legitimate situation without unnecessary alarm.",
    },
    "artifact_investigator": {
        "title": "Artifact Investigator",
        "description": "Trained against a scenario generated from your own submitted artifact.",
    },
}


def _is_first_completed_session(db, user_id):
    row = db.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE user_id = ? AND status = 'completed'",
        (user_id,),
    ).fetchone()
    return row["n"] == 1  # this session's own completion already counted


def check_and_award_achievements(db, user_id, scenario, state):
    """Call once, right after a session transitions to completed. Returns
    the list of achievement keys newly earned this call (empty if none —
    already-earned achievements are never re-awarded, enforced by the
    UNIQUE(user_id, achievement_key) constraint)."""
    outcome = state["outcome"]
    newly_earned = []

    candidates = []
    if _is_first_completed_session(db, user_id):
        candidates.append("first_scenario_completed")
    if outcome == "avoided_scam":
        candidates.append("scam_spotter")
        if scenario["difficulty"] == "advanced":
            candidates.append("advanced_resistance")
    if outcome == "handled_correctly":
        candidates.append("well_calibrated")
    if state["reasoning_score"] == 100:
        candidates.append("perfect_reasoning")
    if scenario.get("source") == "artifact_analysis":
        candidates.append("artifact_investigator")

    for key in candidates:
        # Check first rather than relying on the UNIQUE constraint to fail:
        # a failed INSERT doesn't abort the whole SQLite transaction, but
        # rollback() here would also undo any achievements already inserted
        # earlier in this same loop, which we don't want.
        existing = db.execute(
            "SELECT 1 FROM achievements WHERE user_id = ? AND achievement_key = ?",
            (user_id, key),
        ).fetchone()
        if existing:
            continue
        db.execute(
            "INSERT INTO achievements (user_id, achievement_key) VALUES (?, ?)",
            (user_id, key),
        )
        newly_earned.append(key)
    db.commit()
    return newly_earned


def get_achievements(db, user_id):
    rows = db.execute(
        "SELECT achievement_key, earned_at FROM achievements WHERE user_id = ? ORDER BY earned_at ASC",
        (user_id,),
    ).fetchall()
    return [
        {
            "key": r["achievement_key"],
            "title": ACHIEVEMENTS.get(r["achievement_key"], {}).get("title", r["achievement_key"]),
            "description": ACHIEVEMENTS.get(r["achievement_key"], {}).get("description", ""),
            "earned_at": r["earned_at"],
        }
        for r in rows
    ]
