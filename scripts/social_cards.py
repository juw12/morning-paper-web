"""Morrow Brief: typographic cards (1080 x 1350) for the social posts.

Text only, in the Morrow palette, with the bundled Source Serif 4 and Source Sans 3 fonts so a card
looks the same on the Linux runner as on a desk. No publisher photos are used.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import social_feed as feed

WIDTH, HEIGHT = 1080, 1350
MARGIN = 88
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FILES = {
    "serif_bold": "SourceSerif4-Semibold.ttf",
    "serif": "SourceSerif4-Regular.ttf",
    "serif_italic": "SourceSerif4-It.ttf",
    "sans": "SourceSans3-Regular.ttf",
    "sans_bold": "SourceSans3-Semibold.ttf",
}
PALETTE = {
    "paper": "#f7f6f2",
    "ink": "#14161a",
    "ink2": "#474c55",
    "ink3": "#646973",
    "accent": "#b4232c",
    "hairline": "#d9d5cc",
    "up": "#0b7a46",
    "down": "#c32a1f",
}
# Every colour that carries text or data, all drawn on the paper colour. The tests check each pair.
TEXT_COLOURS = ("ink", "ink2", "ink3", "accent", "up", "down")
HEADLINE_SIZES = (104, 96, 88, 80, 74, 68, 62, 56, 52)
HEADLINE_LEADING = 1.1
HEADLINE_LINES = 4  # a story headline is set smaller before it runs to a fifth line
HEADLINE_FLOOR = 62  # ... but never smaller than this just to save a line
DEK_SIZES = (46, 42, 38)  # the summary is set as large as its whole sentences allow
DEK_LEADING = 1.36
DEK_GAP = 34  # between the headline and the summary
DEK_BUDGET = 260  # characters of summary a card carries at most
ACCENT_BAR = 20  # the full-bleed bar at the top edge: what marks a card as Morrow Brief at grid size
COVER_LEAD_SIZES = (88, 80, 74, 68, 62, 56, 50, 46)
COVER_ROW_SIZES = (38, 36, 34, 32, 30)
COVER_ROW_LEADING = 1.16
COVER_ROW_PAD = 14  # between a rule and the row's text, above and below
COVER_ROW_META = 32  # the section and outlet line under a row's headline
COVER_ROW_META_SIZE = 22
COVER_LEAD_RATIO = 1.6  # the lead stays at least this much larger than the rows under it


def rgb(name: str) -> tuple[int, int, int]:
    value = PALETTE[name].lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _channel(value: int) -> float:
    scaled = value / 255
    return scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4


def contrast_ratio(foreground: str, background: str = "paper") -> float:
    """WCAG contrast ratio between two palette colours."""
    def luminance(name: str) -> float:
        red, green, blue = (_channel(value) for value in rgb(name))
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@lru_cache(maxsize=None)
def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / FONT_FILES[role]), size)


def text_width(text: str, face: ImageFont.FreeTypeFont, tracking: float = 0) -> float:
    return face.getlength(text) + tracking * max(len(text) - 1, 0)


def wrap(text: str, face: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and face.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def clamp_lines(lines: list[str], max_lines: int, face: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Keep at most max_lines, ending the last kept line with an ellipsis if text was dropped."""
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    last = kept[-1].rstrip(" ,;:-")
    while last and face.getlength(last + "…") > max_width:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    kept[-1] = last.rstrip(" ,;:-") + "…"
    return kept


def fit_line(text: str, face: ImageFont.FreeTypeFont, max_width: float, tracking: float = 0) -> str:
    """Shorten a single line until it fits, ending with an ellipsis. For outlet-supplied names and labels."""
    if text_width(text, face, tracking) <= max_width:
        return text
    while text and text_width(text.rstrip(" ,;:-·") + "…", face, tracking) > max_width:
        text = text.rsplit(" ", 1)[0] if " " in text else text[:-1]
    return text.rstrip(" ,;:-·") + "…"


class Canvas:
    """A page with a small text API. Records what it draws so the tests can check the layout."""

    def __init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH, HEIGHT), rgb("paper"))
        self.draw = ImageDraw.Draw(self.image)
        self.boxes: list[dict] = []

    def text(self, xy, text, role, size, colour, tracking: float = 0, anchor: str = "left", name: str = "") -> float:
        """Draw one line with its top at xy[1]. Returns the line's width."""
        face = font(role, size)
        width = text_width(text, face, tracking)
        left = xy[0] if anchor == "left" else xy[0] - width
        if tracking:
            cursor = left
            for char in text:
                self.draw.text((cursor, xy[1]), char, font=face, fill=rgb(colour))
                cursor += face.getlength(char) + tracking
        else:
            self.draw.text((left, xy[1]), text, font=face, fill=rgb(colour))
        self.boxes.append({
            "name": name or text[:24],
            "left": left,
            "right": left + width,
            "top": xy[1],
            "bottom": xy[1] + size * 1.2,
            "colour": colour,
        })
        return width

    def block(self, xy, lines, role, size, colour, leading: float, name: str = "") -> float:
        """Draw wrapped lines. Returns the y just below the block."""
        y = xy[1]
        for line in lines:
            self.text((xy[0], y), line, role, size, colour, name=name)
            y += size * leading
        return y

    def rule(self, y: float, colour: str = "hairline", weight: int = 2, left: float = MARGIN, right: float = WIDTH - MARGIN):
        self.draw.rectangle([left, y, right, y + weight - 1], fill=rgb(colour))

    def triangle(self, x: float, y: float, size: float, direction: str, colour: str) -> None:
        if direction == "up":
            points = [(x, y + size), (x + size, y + size), (x + size / 2, y)]
        elif direction == "down":
            points = [(x, y), (x + size, y), (x + size / 2, y + size)]
        else:
            points = [(x, y + size * 0.4), (x + size, y + size * 0.4), (x + size, y + size * 0.6), (x, y + size * 0.6)]
        self.draw.polygon(points, fill=rgb(colour))

    def metrics(self, **extra) -> dict:
        return {
            "size": self.image.size,
            "colours": sorted({box["colour"] for box in self.boxes}),
            "min_left": min(box["left"] for box in self.boxes),
            "max_right": max(box["right"] for box in self.boxes),
            "max_bottom": max(box["bottom"] for box in self.boxes),
            **extra,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path, format="PNG", optimize=True)


def _date_label(date_iso: str) -> str:
    day = dt.date.fromisoformat(date_iso)
    return f"{day:%a} {day.day} {day:%b} {day.year}".upper()


def _masthead(canvas: Canvas, date_iso: str) -> float:
    """Accent bar on the top edge, wordmark left, date right, a double rule under both. Returns the y below it."""
    canvas.draw.rectangle([0, 0, WIDTH, ACCENT_BAR - 1], fill=rgb("accent"))
    canvas.text((MARGIN, 84), feed.BRAND, "serif_bold", 50, "ink", name="wordmark")
    canvas.text((WIDTH - MARGIN, 104), _date_label(date_iso), "sans_bold", 24, "ink3", tracking=2.5,
                anchor="right", name="date")
    canvas.rule(168, "ink", 5)
    canvas.rule(180, "ink", 1)
    return 181


def _footer(canvas: Canvas, right_text: str) -> None:
    canvas.rule(HEIGHT - 150, "hairline", 2)
    site_width = canvas.text((MARGIN, HEIGHT - 122), feed.SITE_SHORT, "sans_bold", 27, "ink2", name="site")
    right_text = fit_line(right_text, font("sans", 27), WIDTH - 2 * MARGIN - site_width - 48)
    canvas.text((WIDTH - MARGIN, HEIGHT - 122), right_text, "sans", 27, "ink3", anchor="right", name="footer_right")


def _fit_headline(title: str, max_width: float, max_height: float, sizes: tuple[int, ...] = HEADLINE_SIZES,
                  prefer_lines: int = 0, floor: int = 0) -> tuple[int, list[str]]:
    """The largest size at which the whole headline fits. With prefer_lines, a size no smaller than
    `floor` that keeps the headline to that many lines wins over a larger one that needs more."""
    fitting = []
    for size in sizes:
        face = font("serif_bold", size)
        lines = wrap(title, face, max_width)
        if len(lines) * size * HEADLINE_LEADING <= max_height and all(face.getlength(line) <= max_width for line in lines):
            fitting.append((size, lines))
    if fitting:
        compact = [item for item in fitting if len(item[1]) <= prefer_lines and item[0] >= floor]
        return compact[0] if compact else fitting[0]
    size = sizes[-1]
    face = font("serif_bold", size)
    max_lines = max(int(max_height // (size * HEADLINE_LEADING)), 1)
    return size, clamp_lines(wrap(title, face, max_width), max_lines, face, max_width)


def _coverage_block(canvas: Canvas, story: dict, top: float) -> None:
    """The card's signature: how many outlets reported the story, and which."""
    inner_width = WIDTH - 2 * MARGIN
    names = feed.outlet_names(story)
    if story["coverage"] <= 1:
        canvas.text((MARGIN, top + 8), "SOURCE", "sans_bold", 24, "ink3", tracking=3, name="coverage_label")
        source = fit_line(story["source"], font("serif_bold", 58), inner_width)
        canvas.text((MARGIN, top + 46), source, "serif_bold", 58, "ink", name="coverage_names")
        return
    numeral = str(story["coverage"])
    numeral_width = canvas.text((MARGIN, top - 26), numeral, "serif_bold", 150, "accent", name="coverage_numeral")
    text_left = MARGIN + numeral_width + 34
    canvas.text((text_left, top + 8), "OUTLETS REPORTED THIS", "sans_bold", 26, "ink3", tracking=3,
                name="coverage_label")
    face = font("sans", 34)
    listing = ", ".join(names) if len(names) > 1 else f"First: {story['source']}"
    hidden = story["coverage"] - len(names)
    if len(names) > 1 and hidden > 0:
        listing += f" +{hidden}"
    lines = clamp_lines(wrap(listing, face, WIDTH - MARGIN - text_left), 2, face, WIDTH - MARGIN - text_left)
    canvas.block((text_left, top + 52), lines, "sans", 34, "ink2", 1.25, name="coverage_names")
    assert inner_width > 0


def _fit_summary(parts: list[str], max_width: float, max_height: float) -> tuple[int, list[str]]:
    """Whole sentences only: as many as fit, then the largest size they fit at. No sentence is ever cut."""
    for count in range(len(parts), 0, -1):
        text = " ".join(parts[:count])
        for size in DEK_SIZES:
            face = font("serif", size)
            lines = wrap(text, face, max_width)
            fits_height = len(lines) * size * DEK_LEADING <= max_height
            if fits_height and all(face.getlength(line) <= max_width for line in lines):
                return size, lines
    return DEK_SIZES[-1], []


def render_story_card(story: dict, date_iso: str, path: Path | None = None) -> dict:
    """One story: kicker, headline, summary, and the outlet count as the signature element."""
    canvas = Canvas()
    inner_width = WIDTH - 2 * MARGIN
    y = _masthead(canvas, date_iso) + 54
    kicker = " · ".join(part for part in (story["section"], story["tag"]) if part).upper()
    if kicker:
        kicker = fit_line(kicker, font("sans_bold", 28), inner_width, 3)
        canvas.text((MARGIN, y), kicker, "sans_bold", 28, "accent", tracking=3, name="kicker")
        y += 62

    coverage_top = HEIGHT - 150 - 178
    content_limit = coverage_top - 60
    # The same rule as the captions: whole sentences, and an outlet's cut-off fragment is left out.
    parts = feed.sentences(feed.fit_dek(story["dek"], DEK_BUDGET, cut=False))
    smallest = font("serif", DEK_SIZES[-1])
    reserve = 0.0
    if parts:
        reserve = DEK_GAP + len(wrap(parts[0], smallest, inner_width)) * DEK_SIZES[-1] * DEK_LEADING
    size, lines = _fit_headline(story["title"], inner_width, content_limit - y - reserve,
                                prefer_lines=HEADLINE_LINES, floor=HEADLINE_FLOOR)
    if not parts or size < HEADLINE_FLOOR:
        # A long headline gets the room before the summary does, and a card with no summary gives
        # the headline one more line before it is set smaller.
        size, lines = _fit_headline(story["title"], inner_width, content_limit - y,
                                    prefer_lines=HEADLINE_LINES + (0 if parts else 1), floor=HEADLINE_FLOOR)
    y = canvas.block((MARGIN, y), lines, "serif_bold", size, "ink", HEADLINE_LEADING, name="headline")
    dek_size, dek_lines = _fit_summary(parts, inner_width, content_limit - y - DEK_GAP)
    if dek_lines:
        y = canvas.block((MARGIN, y + DEK_GAP), dek_lines, "serif", dek_size, "ink2", DEK_LEADING, name="dek")
    content_bottom = y

    canvas.rule(coverage_top - 34, "hairline", 2)
    _coverage_block(canvas, story, coverage_top)
    _footer(canvas, f"Headline: {story['source']}")
    if path:
        canvas.save(path)
    return canvas.metrics(
        headline_size=size,
        headline_lines=len(lines),
        dek_size=dek_size,
        dek_lines=len(dek_lines),
        dek_text=" ".join(dek_lines),
        overlaps=content_bottom > coverage_top - 34,
    )


def render_cover_card(stories: list[dict], markets: list[dict], date_iso: str, outlet_count: int,
                      path: Path | None = None) -> dict:
    """The digest cover: the lead story set large, the rest as a numbered list, the market tape below."""
    canvas = Canvas()
    inner_width = WIDTH - 2 * MARGIN
    lead, rest = stories[0], stories[1:]
    tape_height = 132 if markets else 0
    list_bottom = HEIGHT - 150 - tape_height - 16
    text_left = MARGIN + 64
    row_width = WIDTH - MARGIN - text_left

    # The lead: kicker, then the headline as large as the space above the list allows.
    y = _masthead(canvas, date_iso) + 50
    outlets = f"{lead['coverage']} OUTLETS" if lead["coverage"] > 1 else lead["source"].upper()
    kicker = " · ".join(part for part in ("THE LEAD", lead["section"].upper(), outlets) if part)
    kicker = fit_line(kicker, font("sans_bold", 26), inner_width, 3)
    canvas.text((MARGIN, y), kicker, "sans_bold", 26, "accent", tracking=3, name="lead_kicker")
    y += 58

    # Each row is as tall as its own headline needs. Nothing is cut if any size avoids it. After that
    # the rows are set as large as they can be while the lead stays clearly larger (COVER_LEAD_RATIO);
    # when no size keeps that ratio, the size that leaves the lead largest wins.
    lead_title = " ".join(lead["title"].split())
    best = None
    for size in COVER_ROW_SIZES:
        face = font("serif_bold", size)
        rows = []
        for story in rest:
            lines = clamp_lines(wrap(story["title"], face, row_width), 2, face, row_width)
            height = 2 * COVER_ROW_PAD + len(lines) * size * COVER_ROW_LEADING + COVER_ROW_META
            rows.append((story, lines, height))
        top = list_bottom - sum(height for _, _, height in rows)
        fitted_size, fitted_lines = _fit_headline(lead["title"], inner_width, top - 30 - y, COVER_LEAD_SIZES)
        rows_whole = all(" ".join(lines) == " ".join(story["title"].split()) for story, lines, _ in rows)
        balanced = fitted_size >= COVER_LEAD_RATIO * size
        rank = (" ".join(fitted_lines) == lead_title, rows_whole, balanced, size if balanced else fitted_size)
        if best is None or rank > best[0]:
            best = (rank, size, rows, top, fitted_size, fitted_lines)
    (lead_whole, rows_whole, _, _), title_size, rows, rows_top, lead_size, lead_lines = best
    clipped = not (lead_whole and rows_whole)

    lead_bottom = canvas.block((MARGIN, y), lead_lines, "serif_bold", lead_size, "ink", HEADLINE_LEADING,
                               name="lead_title")
    overlaps = lead_bottom > rows_top

    y = rows_top
    for number, (story, lines, height) in enumerate(rows, 2):
        canvas.rule(y, "hairline", 2)
        row_top = y + COVER_ROW_PAD
        canvas.text((MARGIN, row_top - 6), str(number), "serif_bold", 48, "accent", name=f"numeral_{number}")
        bottom = canvas.block((text_left, row_top), lines, "serif_bold", title_size, "ink", COVER_ROW_LEADING,
                              name=f"title_{number}")
        outlets = f"{story['coverage']} OUTLETS" if story["coverage"] > 1 else story["source"].upper()
        meta = " · ".join(part for part in (story["section"].upper(), outlets) if part)
        meta = fit_line(meta, font("sans_bold", COVER_ROW_META_SIZE), row_width, 2)
        canvas.text((text_left, bottom + 4), meta, "sans_bold", COVER_ROW_META_SIZE, "ink3", tracking=2,
                    name=f"meta_{number}")
        y += height

    if markets:
        canvas.rule(y, "ink", 2)
        shown = markets[:4]
        column = inner_width / len(shown)
        for index, quote in enumerate(shown):
            left = MARGIN + index * column
            colour = quote["dir"] if quote["dir"] in ("up", "down") else "ink2"
            name = fit_line(quote["name"].upper(), font("sans_bold", 22), column - 20, 1.5)
            canvas.text((left, y + 22), name, "sans_bold", 22, "ink3", tracking=1.5,
                        name=f"quote_name_{index}")
            canvas.triangle(left, y + 70, 22, quote["dir"], colour)
            canvas.text((left + 32, y + 56), f"{quote['pct']:.2f}%", "sans_bold", 40, colour, name=f"quote_pct_{index}")

    count_word = {3: "Three", 4: "Four", 5: "Five", 6: "Six"}.get(len(stories), str(len(stories)))
    _footer(canvas, f"{count_word} stories, read across {outlet_count} outlets")
    if path:
        canvas.save(path)
    return canvas.metrics(rows=len(stories), lead_size=lead_size, lead_lines=len(lead_lines),
                          title_size=title_size, clipped=clipped, overlaps=overlaps)


def render_post_cards(post: dict, edition: dict, out_dir: Path) -> list[Path]:
    """Render the cards a post needs. A card that already exists is left alone, so it never changes."""
    by_id = {story["id"]: story for story in edition["stories"]}
    stories = [by_id[story_id] for story_id in post["story_ids"] if story_id in by_id]
    written: list[Path] = []
    for relative in post["cards"]:
        path = out_dir / relative
        if path.exists():
            continue
        if path.stem == "digest":
            render_cover_card(stories, edition["markets"], post["date"], feed.outlet_total(edition["stories"]), path)
        elif path.stem in by_id:
            render_story_card(by_id[path.stem], post["date"], path)
        else:
            continue
        written.append(path)
    return written
