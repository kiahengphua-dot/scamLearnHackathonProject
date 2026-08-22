import urllib.error
from unittest.mock import patch

import pytest

from app.artifacts.url_fetcher import (
    URLFetchError,
    _is_blocked_ip,
    _validate_and_resolve,
    describe_url_structure,
    extract_page_content,
    fetch_url_safely,
)


# ---------------------------------------------------------------------------
# IP classification (the core SSRF guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip", [
    "127.0.0.1",        # loopback
    "10.0.0.1",         # private
    "172.16.0.1",       # private
    "192.168.1.1",      # private
    "169.254.169.254",  # link-local / cloud metadata endpoint
    "0.0.0.0",          # unspecified
    "224.0.0.1",        # multicast
    "::1",              # IPv6 loopback
    "fc00::1",          # IPv6 unique local (private)
    "fe80::1",          # IPv6 link-local
])
def test_blocked_ips_are_rejected(ip):
    assert _is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", [
    "93.184.216.34",    # public IP (example.com, historical)
    "8.8.8.8",           # public IP (Google DNS)
    "2606:2800:220:1:248:1893:25c8:1946",  # public IPv6
])
def test_public_ips_are_allowed(ip):
    assert _is_blocked_ip(ip) is False


def test_malformed_ip_string_is_treated_as_blocked():
    assert _is_blocked_ip("not-an-ip") is True


# ---------------------------------------------------------------------------
# URL structural validation
# ---------------------------------------------------------------------------

def test_rejects_non_http_scheme():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("file:///etc/passwd")


def test_rejects_ftp_scheme():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("ftp://example.com/file")


def test_rejects_url_with_no_hostname():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http:///path")


def test_rejects_non_default_port():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://93.184.216.34:8080/")


def test_allows_default_port_explicit():
    # Should not raise -- 93.184.216.34 is a public IP, port matches scheme default.
    _validate_and_resolve("http://93.184.216.34:80/")


def test_rejects_loopback_ip_literal_in_url():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://127.0.0.1/admin")


def test_rejects_cloud_metadata_ip_literal():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://169.254.169.254/latest/meta-data/")


def test_rejects_private_ip_literal():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://10.0.0.5/internal")


def test_rejects_localhost_hostname():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://localhost/")


def test_allows_public_ip_literal():
    _validate_and_resolve("http://93.184.216.34/")


def test_unresolvable_hostname_raises_fetch_error():
    with pytest.raises(URLFetchError):
        _validate_and_resolve("http://this-domain-should-not-exist-scamlearn-test.invalid/")


# ---------------------------------------------------------------------------
# HTML extraction (no JS execution, just static parsing)
# ---------------------------------------------------------------------------

def test_extract_page_content_gets_title_text_and_links():
    html = """
    <html><head><title>Fake Bank Login</title>
    <script>alert('should not appear in text')</script>
    <style>.x{color:red}</style>
    </head><body>
    <p>Please verify your account now.</p>
    <a href="http://evil.example/login">Login here</a>
    </body></html>
    """
    result = extract_page_content(html)
    assert result["title"] == "Fake Bank Login"
    assert "verify your account" in result["visible_text"]
    assert "alert" not in result["visible_text"]
    assert "color:red" not in result["visible_text"]
    assert "http://evil.example/login" in result["links"]


def test_extract_page_content_caps_text_length():
    html = "<html><body><p>" + ("a " * 5000) + "</p></body></html>"
    result = extract_page_content(html)
    assert len(result["visible_text"]) <= 4000


def test_extract_page_content_caps_link_count():
    links_html = "".join(f'<a href="http://example.com/{i}">l{i}</a>' for i in range(50))
    html = f"<html><body>{links_html}</body></html>"
    result = extract_page_content(html)
    assert len(result["links"]) <= 30


# ---------------------------------------------------------------------------
# URL structure facts (deterministic, backend-computed)
# ---------------------------------------------------------------------------

def test_describe_url_structure_detects_ip_literal():
    facts = describe_url_structure("http://93.184.216.34/login", "http://93.184.216.34/login")
    assert facts["uses_ip_literal_instead_of_domain"] is True


def test_describe_url_structure_detects_redirect():
    facts = describe_url_structure("http://bit.ly/xyz", "http://totally-different-domain.example/page")
    assert facts["redirected"] is True


def test_describe_url_structure_counts_subdomains():
    facts = describe_url_structure("http://secure.login.example.com/", "http://secure.login.example.com/")
    assert facts["subdomain_count"] == 2


# ---------------------------------------------------------------------------
# Redirect-hop re-validation — the trickiest SSRF guard: a hostname that
# resolves fine on the first hop must not let a redirect smuggle the fetch
# to a blocked address on a later hop.
# ---------------------------------------------------------------------------

def test_redirect_to_cloud_metadata_ip_is_blocked_before_second_fetch():
    calls = []

    def fake_open(self, request, timeout=None):
        calls.append(request.full_url)
        if "example.com" in request.full_url:
            raise urllib.error.HTTPError(
                request.full_url, 302, "Found", {"Location": "http://169.254.169.254/latest/meta-data/"}, None
            )
        raise AssertionError("must never attempt the redirect target -- SSRF guard failed")

    with patch("urllib.request.OpenerDirector.open", fake_open):
        with pytest.raises(URLFetchError):
            fetch_url_safely("http://example.com/redirector")

    assert calls == ["http://example.com/redirector"]


def test_redirect_to_private_ip_is_blocked():
    def fake_open(self, request, timeout=None):
        if "example.com" in request.full_url:
            raise urllib.error.HTTPError(
                request.full_url, 302, "Found", {"Location": "http://10.0.0.1/internal-admin"}, None
            )
        raise AssertionError("must never attempt the redirect target")

    with patch("urllib.request.OpenerDirector.open", fake_open):
        with pytest.raises(URLFetchError):
            fetch_url_safely("http://example.com/redirector")


def test_too_many_redirects_raises():
    def fake_open(self, request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 302, "Found", {"Location": "http://example.com/next"}, None
        )

    with patch("urllib.request.OpenerDirector.open", fake_open):
        with pytest.raises(URLFetchError):
            fetch_url_safely("http://example.com/start")


def test_oversized_response_is_rejected():
    import io

    class FakeResponse:
        def __init__(self, body):
            self._body = body
            self.headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()

        def read(self, n):
            return self._body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    from app.artifacts.url_fetcher import MAX_RESPONSE_BYTES

    def fake_open(self, request, timeout=None):
        return FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 100))

    with patch("urllib.request.OpenerDirector.open", fake_open):
        with pytest.raises(URLFetchError):
            fetch_url_safely("http://example.com/huge-page")
