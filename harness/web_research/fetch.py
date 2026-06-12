from __future__ import annotations
import ipaddress
import urllib.parse
import httpx
import trafilatura


_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost."})


def _is_safe_url(url: str) -> bool:
    """Return True only for public http/https URLs; block SSRF targets."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False
    try:
        addr = ipaddress.ip_address(host)
        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_reserved
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    except ValueError:
        pass  # hostname, not a bare IP literal
    return True


def fetch_url(url: str) -> dict:
    if not _is_safe_url(url):
        raise ValueError(f"Blocked URL '{url}': only public http/https URLs are allowed")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text

    text = trafilatura.extract(
        html,
        include_links=True,
        no_fallback=False,
        output_format="txt",
    )
    title = trafilatura.extract(
        html,
        include_links=False,
        no_fallback=False,
        output_format="txt",
        favor_precision=True,
    )
    extracted_title = None
    if title:
        lines = title.strip().split("\n")
        extracted_title = lines[0].strip() if lines else None

    return {
        "url": url,
        "title": extracted_title,
        "text": (text or "").strip(),
        "word_count": len((text or "").split()),
    }
