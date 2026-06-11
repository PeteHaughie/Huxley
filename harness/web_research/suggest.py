from __future__ import annotations

import httpx


DDG_SUGGEST_URL = "https://duckduckgo.com/ac/"


def suggest_query(partial_query: str) -> list[str]:
    params = {"q": partial_query}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(DDG_SUGGEST_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    suggestions = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                phrase = item.get("phrase", "")
                if phrase:
                    suggestions.append(phrase)
            elif isinstance(item, str):
                suggestions.append(item)
    return suggestions
