from __future__ import annotations
import ipaddress
import socket
import urllib.parse
import httpx
import trafilatura


_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost."})


def _is_safe_host(host: str) -> bool:
    """Return True if host is a public (non-private/loopback/reserved) address."""
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False
    # Check if it is a bare IP literal first.
    try:
        addr = ipaddress.ip_address(host)
        return not (
            addr.is_loopback
            or addr.is_private
            or addr.is_reserved
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
        )
    except ValueError:
        pass  # not a bare IP literal – resolve it
    # Resolve hostname and check every resulting address.
    try:
        results = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in results:
            raw_ip = sockaddr[0]
            addr = ipaddress.ip_address(raw_ip)
            if (
                addr.is_loopback
                or addr.is_private
                or addr.is_reserved
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_unspecified
            ):
                return False
    except OSError:
        # Cannot resolve – treat as unsafe.
        return False
    return True


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
    return _is_safe_host(host)


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

    def _on_redirect(response: httpx.Response) -> None:
        location = response.headers.get("location", "")
        target_url = urllib.parse.urljoin(str(response.url), location)
        if location and not _is_safe_url(target_url):
            raise ValueError(
                f"Blocked redirect to '{target_url}': only public http/https URLs are allowed"
            )

    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        event_hooks={"response": [_on_redirect]},
    ) as client:
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
