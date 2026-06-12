from __future__ import annotations
import os

import httpx
from ddgs import DDGS


BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def search_duckduckgo(query: str, max_results: int = 10) -> list[dict]:
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    results = []
    for item in raw:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("href", ""),
            "snippet": item.get("body", ""),
        })
    return results


def search_brave(query: str, max_results: int = 10) -> list[dict]:
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        raise ValueError("BRAVE_API_KEY not set")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            BRAVE_URL,
            params={"q": query, "count": max_results},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    return results


def search_web(query: str, max_results: int = 10, fallback: bool = True) -> list[dict]:
    try:
        return search_duckduckgo(query, max_results)
    except Exception as e:
        if not fallback:
            raise
        try:
            return search_brave(query, max_results)
        except Exception:
            raise ValueError(
                f"search failed (DDG: {e}, Brave: not available or also failed)"
            )
