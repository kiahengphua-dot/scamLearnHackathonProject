"""SSRF-hardened URL fetcher for artifact analysis.

This is the one place in the app that makes a server-side request to a
URL the USER supplies — the classic SSRF surface (internal services,
cloud metadata endpoints like 169.254.169.254, etc.). Every safeguard
here is defense against that, not just correctness:

- Only http/https, only default ports (80/443)
- Every resolved IP for the hostname is checked against private/loopback/
  link-local/reserved/multicast ranges — checked again on every redirect
  hop, since a hostname can resolve differently or a redirect can point
  anywhere
- Redirects are never auto-followed by the HTTP client; we intercept and
  re-validate each one ourselves, capped at a small number of hops
- Response size is capped while reading, not just via headers (a server
  can lie about Content-Length)
- No JavaScript execution, no headless browser — just static HTML parsing
- Errors are never distinguished to the caller (DNS failure vs blocked
  private IP vs timeout vs oversized response all look identical
  externally) so this endpoint can't be used as a network-mapping oracle
"""

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {"http": 80, "https": 443}
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 8
MAX_EXTRACTED_TEXT_CHARS = 4000
MAX_EXTRACTED_LINKS = 30
USER_AGENT = "ScamLearnBot/1.0 (+artifact analysis; does not execute scripts or submit forms)"


class URLFetchError(RuntimeError):
    """Raised for ANY fetch failure — SSRF-blocked, unreachable, too large,
    timed out, whatever. Deliberately undifferentiated; see module docstring."""


def _is_blocked_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_and_resolve(url):
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise URLFetchError("unsupported scheme")
    if not parsed.hostname:
        raise URLFetchError("no hostname")

    expected_port = DEFAULT_PORTS[parsed.scheme]
    if parsed.port is not None and parsed.port != expected_port:
        raise URLFetchError("non-default port not allowed")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, expected_port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise URLFetchError("could not resolve host")

    if not addrinfo:
        raise URLFetchError("could not resolve host")

    for info in addrinfo:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise URLFetchError("resolved address not allowed")

    return parsed


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # caller re-validates and follows manually


def fetch_url_safely(url):
    """Returns (html_text, final_url). Raises URLFetchError on any failure."""
    current_url = url
    opener = urllib.request.build_opener(_NoAutoRedirect)

    for _ in range(MAX_REDIRECTS + 1):
        _validate_and_resolve(current_url)  # raises on anything not allowed

        request = urllib.request.Request(current_url, headers={"User-Agent": USER_AGENT})
        try:
            response = opener.open(request, timeout=FETCH_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    raise URLFetchError("redirect with no location")
                current_url = urllib.parse.urljoin(current_url, location)
                continue
            raise URLFetchError(f"http error {e.code}")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise URLFetchError("network error")

        with response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise URLFetchError("response too large")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                html_text = data.decode(charset, errors="replace")
            except LookupError:
                html_text = data.decode("utf-8", errors="replace")
            return html_text, current_url

    raise URLFetchError("too many redirects")


class _PageTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip = False
        self._text_parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in ("script", "style"):
            self._skip = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href and len(self.links) < MAX_EXTRACTED_LINKS:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        else:
            self._text_parts.append(text)

    @property
    def visible_text(self):
        return " ".join(self._text_parts)[:MAX_EXTRACTED_TEXT_CHARS]


def extract_page_content(html_text):
    parser = _PageTextExtractor()
    parser.feed(html_text)
    return {"title": parser.title.strip(), "visible_text": parser.visible_text, "links": parser.links}


def describe_url_structure(original_url, final_url):
    """Deterministic, backend-computed facts about the URL — handed to
    Claude as trusted context rather than asking it to judge the raw
    string itself."""
    parsed = urllib.parse.urlparse(final_url)
    hostname = parsed.hostname or ""
    is_ip_literal = False
    try:
        ipaddress.ip_address(hostname)
        is_ip_literal = True
    except ValueError:
        pass

    return {
        "original_url": original_url,
        "final_url": final_url,
        "redirected": original_url != final_url,
        "hostname": hostname,
        "subdomain_count": max(0, hostname.count(".") - 1) if not is_ip_literal else 0,
        "uses_ip_literal_instead_of_domain": is_ip_literal,
        "scheme": parsed.scheme,
    }
