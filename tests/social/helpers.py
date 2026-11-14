"""Shared pieces for the social tests: the real fixture, a synthetic page builder and a fake HTTP client."""
from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import social_feed as feed  # noqa: E402

FIXTURES = HERE / "fixtures"
SECTIONS = {
    "ai": "AI & Chips",
    "big_tech": "Big US Tech",
    "robotics": "Robotics",
    "space": "Space & Aircraft",
    "technology": "Technology",
    "markets_news": "Markets",
}


def real_edition() -> dict:
    return feed.parse_edition((FIXTURES / "edition.html").read_text(encoding="utf-8"))


def story(number: int, section: str = "ai", coverage: int = 1, **fields) -> dict:
    base = {
        "title": f"Story number {number} about something that happened",
        "url": f"https://example.com/story-{number}",
        "source": f"Outlet {number}",
        "section": section,
        "tag": "Topic",
        "dek": f"A one line summary of story {number}.",
        "coverage": coverage,
        "related": [],
        "kind": "card",
    }
    base.update(fields)
    return base


def page(stories: list[dict], date: str = "November 14, 2026", updated: str = "09:15", markets: bool = True) -> str:
    """A small page in the published markup: a front section with the lead, then one block per section."""
    def article(item: dict) -> str:
        kicker = ""
        if item["kind"] != "row":
            kicker = f'<p class="kicker">{html.escape(SECTIONS[item["section"]])} · {html.escape(item["tag"])}</p>'
        coverage = ""
        if item["coverage"] > 1:
            coverage = f'<span class="cov" title="Reported by {item["coverage"]} outlets">{item["coverage"]}</span>'
        related = ""
        if item["related"]:
            links = "".join(
                f'<li><a href="{html.escape(link["url"])}"><b>{html.escape(link["source"])}</b> '
                f'{html.escape(link["title"])}</a></li>'
                for link in item["related"]
            )
            related = f'<details class="related"><summary>More</summary><ul>{links}</ul></details>'
        return (
            f'<article class="story {item["kind"]}">{kicker}'
            f'<h3><a class="story-link" href="{html.escape(item["url"])}">{html.escape(item["title"])}</a></h3>'
            f'<p class="dek">{html.escape(item["dek"])}</p>'
            f'<div class="meta"><span class="src">{html.escape(item["source"])}</span>'
            f'<time datetime="2026-11-14T01:00:00+00:00">1h</time>{coverage}</div>{related}</article>'
        )

    front = "".join(article(item) for item in stories if item["kind"] == "lead")
    blocks = ""
    for section_id, name in SECTIONS.items():
        members = [item for item in stories if item["section"] == section_id and item["kind"] != "lead"]
        if members:
            blocks += (
                f'<section id="s-{section_id}"><div class="block-head"><h2>{html.escape(name)}</h2></div>'
                + "".join(article(item) for item in members) + "</section>"
            )
    tape = ""
    if markets:
        tape = (
            '<div id="markets">'
            '<div class="qcard down"><span class="qname">S&amp;P 500</span><span class="qprice">6,812.40</span>'
            '<span class="qpct">-0.40%</span></div>'
            '<div class="qcard up"><span class="qname">IHSG (Jakarta)</span><span class="qprice">8,120.10</span>'
            '<span class="qpct">+1.78%</span></div></div>'
        )
    return (
        f"<html><head><title>Morrow · {date}</title></head><body>"
        f'<header><p class="dateline">{date} · Updated {updated}</p></header>'
        f'{tape}<section class="front">{front}</section>{blocks}</body></html>'
    )


def edition_from(stories: list[dict], **options) -> dict:
    return feed.parse_edition(page(stories, **options))


class FakeResponse:
    def __init__(self, status: int = 200, body=None, headers: dict | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


class FakeHttp:
    """Stands in for `requests`. Answers come from queues; the last answer of a queue repeats."""

    def __init__(self, channels: list[dict] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.channels = channels if channels is not None else []
        self.telegram: list = [FakeResponse(200, {"ok": True, "result": {"message_id": 7}})]
        self.create: list = [FakeResponse(200, {"data": {"createPost": {
            "__typename": "PostActionSuccess", "post": {"id": "post-1", "status": "sent"}}}})]
        self.organizations: list = [FakeResponse(200, {"data": {"account": {"organizations": [{"id": "org-1"}]}}})]
        self.images: list = [FakeResponse(200, None, {"Content-Type": "image/png"})]

    @staticmethod
    def _next(queue: list):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if "api.telegram.org" in url:
            return self._next(self.telegram)
        query = kwargs["json"]["query"]
        if "createPost" in query:
            return self._next(self.create)
        if "organizations" in query:
            return self._next(self.organizations)
        return FakeResponse(200, {"data": {"channels": self.channels}})

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self._next(self.images)

    def count(self, fragment: str) -> int:
        """How many calls went to a URL, or carried a GraphQL query, containing the fragment."""
        total = 0
        for url, kwargs in self.calls:
            query = (kwargs.get("json") or {}).get("query", "") if isinstance(kwargs.get("json"), dict) else ""
            if fragment in url or fragment in query:
                total += 1
        return total
