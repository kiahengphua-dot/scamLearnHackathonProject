from flask import Blueprint, render_template

from app.identity import get_or_create_user

pages_bp = Blueprint("pages", __name__)


@pages_bp.before_request
def _ensure_identity():
    get_or_create_user()


@pages_bp.route("/")
def home():
    return render_template("home.html")


@pages_bp.route("/train")
def train():
    return render_template("train.html")


@pages_bp.route("/test")
def test_mode():
    return render_template("test.html")


@pages_bp.route("/analyze")
def analyze():
    return render_template("analyze.html")


@pages_bp.route("/profile")
def profile():
    return render_template("profile.html")


@pages_bp.route("/about")
def about():
    return render_template("about.html")
