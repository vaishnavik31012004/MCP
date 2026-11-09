"""Information MCP server — web search, news, and reading a page's text.

web_search and read_page work with zero API keys (DuckDuckGo HTML + a plain
httpx fetch). get_news uses NewsAPI.org if NEWSAPI_KEY is set, and otherwise
falls back to web_search transparently — the agent always gets a usable
result either way, it just gets a better one with a key configured.
"""
from __future__ import annotations

import os
import re

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from mcp_servers.shared.http import get_json
from mcp_servers.shared.risk import risk

mcp = FastMCP("information")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-agent-mcp/1.0)"}


@mcp.tool()
@risk("LOW")
async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web and return a list of results with title, url, and snippet."""
    max_results = max(1, min(max_results, 10))
    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
        resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")
        if not link:
            continue
        results.append(
            {
                "title": link.get_text(strip=True),
                "url": link.get("href"),
                "snippet": snippet.get_text(strip=True) if snippet else "",
            }
        )
    return {"query": query, "results": results}


@mcp.tool()
@risk("LOW")
async def get_news(topic: str, max_results: int = 5) -> dict:
    """Get recent news headlines about a topic."""
    api_key = os.environ.get("NEWSAPI_KEY")
    max_results = max(1, min(max_results, 10))
    if not api_key:
        fallback = await web_search(f"{topic} news", max_results)
        fallback["note"] = "NEWSAPI_KEY not configured — showing web search results instead."
        return fallback

    data = await get_json(
        "https://newsapi.org/v2/everything",
        params={"q": topic, "sortBy": "publishedAt", "pageSize": max_results, "language": "en"},
        headers={"X-Api-Key": api_key},
    )
    articles = [
        {
            "title": a.get("title"),
            "source": (a.get("source") or {}).get("name"),
            "url": a.get("url"),
            "published_at": a.get("publishedAt"),
            "description": a.get("description"),
        }
        for a in data.get("articles", [])
    ]
    return {"topic": topic, "articles": articles}


@mcp.tool()
@risk("LOW")
async def read_page(url: str, max_chars: int = 4000) -> dict:
    """Fetch a web page and return its main readable text, stripped of HTML/scripts/nav clutter."""
    async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    truncated = len(text) > max_chars
    return {
        "url": url,
        "title": soup.title.string.strip() if soup.title and soup.title.string else None,
        "text": text[:max_chars],
        "truncated": truncated,
    }


if __name__ == "__main__":
    mcp.run()
