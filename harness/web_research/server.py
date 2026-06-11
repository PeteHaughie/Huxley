from __future__ import annotations
from fastmcp import FastMCP

from harness.web_research.search import search_web
from harness.web_research.fetch import fetch_url
from harness.web_research.suggest import suggest_query


def create_server() -> FastMCP:
    mcp = FastMCP("web-research")

    @mcp.tool()
    def web_search(query: str, max_results: int = 10, fallback: bool = True) -> str:
        results = search_web(query, max_results, fallback=fallback)
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines) if lines else "No results found."

    @mcp.tool()
    def web_fetch(url: str) -> str:
        result = fetch_url(url)
        parts = [f"Title: {result['title'] or 'N/A'}", f"URL: {result['url']}"]
        if result["text"]:
            if result["word_count"] > 5000:
                text = (
                    " ".join(result["text"].split()[:5000])
                    + "\n\n[truncated at 5000 words]"
                )
            else:
                text = result["text"]
            parts.append(f"\n{text}")
        else:
            parts.append("\n(no extractable text)")
        return "\n".join(parts)

    @mcp.tool()
    def web_suggest(partial_query: str) -> str:
        suggestions = suggest_query(partial_query)
        if not suggestions:
            return "No suggestions."
        return "\n".join(f"{i}. {s}" for i, s in enumerate(suggestions, 1))

    return mcp


if __name__ == "__main__":
    mcp = create_server()
    mcp.run(transport="stdio")
