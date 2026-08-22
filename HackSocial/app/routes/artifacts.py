import base64
import json
import logging
import uuid

from flask import Blueprint, current_app, g, jsonify, request

from app.artifacts.analysis import AnalysisUnavailableError, analyze_artifact
from app.artifacts.scenario_generator import GenerationUnavailableError, generate_scenario_from_analysis
from app.artifacts.url_fetcher import URLFetchError, describe_url_structure, extract_page_content, fetch_url_safely
from app.db import fetch_artifact_analysis, get_db, save_artifact_analysis, save_generated_scenario
from app.extensions import limiter
from app.identity import get_or_create_user

logger = logging.getLogger(__name__)

artifacts_bp = Blueprint("artifacts", __name__, url_prefix="/api/artifacts")

VALID_ARTIFACT_TYPES = {"text", "screenshot", "url"}

# Deliberately the same message for every URL-fetch failure — SSRF-blocked,
# DNS failure, timeout, oversized response all look identical externally
# so this endpoint can't be used to map internal network topology via
# differing error responses. Specifics only ever go to the server log.
URL_FETCH_GENERIC_ERROR = "This URL could not be analyzed. It may be unreachable, blocked, or too large."


@artifacts_bp.before_request
def _ensure_identity():
    get_or_create_user()


def _error(message, status=400):
    return jsonify({"error": message}), status


@artifacts_bp.route("/analyze", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_ANALYZE"])
def analyze():
    artifact_type = request.form.get("type") or (request.get_json(silent=True) or {}).get("type")
    if artifact_type not in VALID_ARTIFACT_TYPES:
        return _error("type must be 'text', 'screenshot', or 'url'")

    text = None
    image_b64 = None
    media_type = None
    url_facts = None
    url_page = None

    if artifact_type == "text":
        body = request.get_json(silent=True) or {}
        text = (request.form.get("text") or body.get("text") or "").strip()
        if not text:
            return _error("text is required for a text artifact")
        max_len = current_app.config["MAX_ARTIFACT_TEXT_LENGTH"]
        if len(text) > max_len:
            return _error(f"text exceeds the maximum length of {max_len} characters")

    elif artifact_type == "url":
        body = request.get_json(silent=True) or {}
        url = (request.form.get("url") or body.get("url") or "").strip()
        if not url:
            return _error("url is required for a url artifact")
        if len(url) > current_app.config["MAX_URL_LENGTH"]:
            return _error(f"url exceeds the maximum length of {current_app.config['MAX_URL_LENGTH']} characters")

        try:
            html_text, final_url = fetch_url_safely(url)
        except URLFetchError as e:
            logger.warning("URL fetch blocked/failed for artifact analysis: %s", e)
            return _error(URL_FETCH_GENERIC_ERROR, 400)

        url_facts = describe_url_structure(url, final_url)
        url_page = extract_page_content(html_text)

    else:
        file = request.files.get("image")
        if file is None or file.filename == "":
            return _error("image file is required for a screenshot artifact")
        if file.mimetype not in current_app.config["ALLOWED_IMAGE_TYPES"]:
            return _error(f"unsupported image type: {file.mimetype}")

        raw_bytes = file.read(current_app.config["MAX_IMAGE_BYTES"] + 1)
        if len(raw_bytes) > current_app.config["MAX_IMAGE_BYTES"]:
            return _error("image exceeds the maximum allowed size")
        if not raw_bytes:
            return _error("uploaded image was empty")

        media_type = file.mimetype
        image_b64 = base64.b64encode(raw_bytes).decode("ascii")
        # raw_bytes intentionally never touches disk and is discarded once
        # this request ends — only the derived analysis is persisted below.

    try:
        analysis = analyze_artifact(
            current_app.config,
            artifact_type,
            text=text,
            image_b64=image_b64,
            media_type=media_type,
            url_facts=url_facts,
            url_page=url_page,
        )
    except AnalysisUnavailableError as e:
        logger.warning("Artifact analysis unavailable: %s", e)
        return _error("Artifact analysis is temporarily unavailable. Please try again shortly.", 503)

    analysis_id = f"analysis-{uuid.uuid4().hex[:16]}"
    db = get_db()
    save_artifact_analysis(db, analysis_id, g.user_id, artifact_type, json.dumps(analysis))

    return jsonify({"analysis_id": analysis_id, **analysis}), 201


@artifacts_bp.route("/<analysis_id>/generate-scenario", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_GENERATE"])
def generate_scenario(analysis_id):
    db = get_db()
    row = fetch_artifact_analysis(db, analysis_id, g.user_id)
    if row is None:
        return _error("Analysis not found", 404)

    analysis = json.loads(row["analysis_json"])

    try:
        scenario = generate_scenario_from_analysis(current_app.config, analysis)
    except GenerationUnavailableError as e:
        logger.warning("Scenario generation unavailable: %s", e)
        return _error("Couldn't generate a training scenario from this artifact. Please try again.", 503)

    save_generated_scenario(db, scenario["id"], g.user_id, analysis_id, json.dumps(scenario))

    # Same leakage discipline as a static scenario summary: title/category/
    # difficulty/objectives are fine to reveal before play; classification,
    # scoring_rules, and dangerous/red-flag details are not.
    return jsonify({
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "category": scenario["category"],
        "difficulty": scenario["difficulty"],
        "target_learning_objectives": scenario["target_learning_objectives"],
    }), 201
