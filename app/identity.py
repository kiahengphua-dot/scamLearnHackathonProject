import secrets

from flask import g, request

from app.db import get_db

COOKIE_NAME = "scamlearn_uid"


def get_or_create_user():
    """Resolve the anonymous demo user for this browser, creating one if needed.

    No login system (per spec section 32) — identity is a random signed
    cookie value mapped to a users row, generated on first visit.
    """
    if "user_id" in g:
        return g.user_id

    token = request.cookies.get(COOKIE_NAME)
    db = get_db()

    if token:
        row = db.execute("SELECT id FROM users WHERE cookie_token = ?", (token,)).fetchone()
        if row:
            g.user_id = row["id"]
            g.new_cookie_token = None
            return g.user_id

    new_token = secrets.token_urlsafe(32)
    cursor = db.execute("INSERT INTO users (cookie_token) VALUES (?)", (new_token,))
    db.commit()
    g.user_id = cursor.lastrowid
    g.new_cookie_token = new_token
    return g.user_id


def apply_identity_cookie(response):
    new_token = g.pop("new_cookie_token", None)
    if new_token:
        response.set_cookie(
            COOKIE_NAME,
            new_token,
            httponly=True,
            samesite="Lax",
            max_age=60 * 60 * 24 * 365,
        )
    return response
