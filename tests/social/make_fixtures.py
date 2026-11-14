"""Rebuild the test fixtures from a published page.

    python tests/social/make_fixtures.py index.html

Writes fixtures/edition.html (the page with scripts, styles and pictures removed) and
fixtures/bot_cases.json (messages and the replies both bot implementations must give).
Run it only when the page's markup changes; the tests then pin the new behaviour.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))

import social_bot as bot  # noqa: E402
import social_feed as feed  # noqa: E402

MESSAGES = [
    ("/start", True),
    ("/help", True),
    ("/today", True),
    ("/TODAY", True),
    ("/today@MorrowBriefBot", False),
    ("/ai", True),
    ("/bigtech", True),
    ("/robotics", True),
    ("/space", True),
    ("/tech", True),
    ("/markets", True),
    ("/tape", True),
    ("/sources", True),
    ("/about", True),
    ("/find nvidia", True),
    ("/find@MorrowBriefBot  SpaceX starship ", False),
    ("/find", True),
    ("/find a", True),
    ("/find zzzzqqq <b>", True),
    ("/unknown", True),
    ("hello there", True),
    ("hello there", False),
    ("", True),
]


def trim(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup.select("script, style, svg, img, noscript, link, meta, #analysis, template, canvas, form, dialog"):
        tag.decompose()
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    lines = [line.rstrip() for line in str(soup).splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def main() -> int:
    page = Path(sys.argv[1] if len(sys.argv) > 1 else "index.html").read_text(encoding="utf-8")
    fixtures = HERE / "fixtures"
    fixtures.mkdir(exist_ok=True)
    trimmed = trim(page)
    (fixtures / "edition.html").write_text(trimmed, encoding="utf-8", newline="\n")
    edition = feed.parse_edition(trimmed)
    feed_data = feed.public_feed(edition, [])
    cases = [
        {"text": text, "private": private, "reply": bot.reply_for(feed_data, text, private)}
        for text, private in MESSAGES
    ]
    (fixtures / "bot_cases.json").write_text(
        json.dumps({"feed": feed_data, "cases": cases}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"edition.html {len(trimmed) // 1024} KB, {len(edition['stories'])} stories, {len(cases)} bot cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
