def test_home_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"ScamLearn" in resp.data


def test_anonymous_identity_cookie_is_set(client):
    resp = client.get("/")
    assert "scamlearn_uid" in resp.headers.get("Set-Cookie", "")


def test_identity_persists_across_requests(client):
    first = client.get("/")
    cookie_header = first.headers.get("Set-Cookie", "")
    assert cookie_header

    second = client.get("/")
    # No new cookie should be set once the user already has one.
    assert "scamlearn_uid" not in second.headers.get("Set-Cookie", "")


def test_security_headers_present(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_nav_pages_load(client):
    for path in ["/train", "/test", "/analyze", "/profile", "/about"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
