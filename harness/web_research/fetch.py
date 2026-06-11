from __future__ import annotations
import httpx
import trafilatura


def fetch_url(url: str) -> dict:
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
