from flask import Flask

from app import db as db_module
from app.config import Config
from app.extensions import limiter
from app.identity import apply_identity_cookie


def create_app(config_class=Config, validate_config=True):
    app = Flask(__name__)
    app.config.from_object(config_class)

    if validate_config:
        config_class.validate()

    db_module.init_app(app)

    # Hard cap enforced by Werkzeug itself (413) before our own per-field
    # checks ever run — a request body larger than this is rejected without
    # buffering the whole thing into memory first.
    app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_IMAGE_BYTES"] + 1024 * 1024

    # Rate limiting is disabled under TESTING so the suite stays
    # deterministic — tests intentionally hammer the same endpoints in
    # tight loops and shouldn't be throttled by a real per-IP limit.
    app.config.setdefault("RATELIMIT_ENABLED", not app.config.get("TESTING", False))
    app.config.setdefault("RATELIMIT_DEFAULT", app.config.get("RATELIMIT_DEFAULT", "200 per hour"))
    limiter.init_app(app)

    from app.routes.pages import pages_bp
    from app.routes.api import api_bp
    from app.routes.artifacts import artifacts_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(artifacts_bp)

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return apply_identity_cookie(response)

    return app
