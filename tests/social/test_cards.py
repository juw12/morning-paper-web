"""The cards: gate 5 (1080 x 1350 PNG, readable colours) and a layout that stays inside its margins."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import helpers
from helpers import edition_from, real_edition, story

import social_cards as cards
import social_feed as feed

LONG_TITLE = ("Regulators on three continents open parallel inquiries into the largest chip supply agreement "
              "ever signed, as rivals warn of shortages lasting well into the next decade and beyond " * 2)[:300]
LONG_NAME = "The Extremely Long Named International Gazette of Record and Commerce"


def assert_inside_the_page(test: unittest.TestCase, metrics: dict) -> None:
    test.assertEqual(metrics["size"], (1080, 1350))
    test.assertFalse(metrics["overlaps"], metrics)
    test.assertGreaterEqual(metrics["min_left"], cards.MARGIN - 0.5, metrics)
    test.assertLessEqual(metrics["max_right"], cards.WIDTH - cards.MARGIN + 0.5, metrics)
    test.assertLessEqual(metrics["max_bottom"], cards.HEIGHT - cards.MARGIN + 0.5, metrics)
    test.assertLessEqual(set(metrics["colours"]), set(cards.TEXT_COLOURS), metrics)


class PaletteTest(unittest.TestCase):
    def test_gate_5_every_text_colour_reads_on_paper(self):
        for colour in cards.TEXT_COLOURS:
            with self.subTest(colour=colour):
                self.assertGreaterEqual(cards.contrast_ratio(colour), 4.5)

    def test_contrast_matches_the_known_extremes(self):
        cards.PALETTE["_white"], cards.PALETTE["_black"] = "#ffffff", "#000000"
        try:
            self.assertAlmostEqual(cards.contrast_ratio("_black", "_white"), 21.0, places=2)
            self.assertAlmostEqual(cards.contrast_ratio("_white", "_white"), 1.0, places=5)
        finally:
            del cards.PALETTE["_white"], cards.PALETTE["_black"]

    def test_one_accent_and_no_purple(self):
        for name, value in cards.PALETTE.items():
            red, green, blue = cards.rgb(name)
            self.assertFalse(blue > red > green and blue - green > 40, f"{name} {value} reads as purple")


class StoryCardTest(unittest.TestCase):
    def test_every_story_on_todays_page_fits(self):
        edition = real_edition()
        for item in edition["stories"]:
            with self.subTest(title=item["title"][:40]):
                assert_inside_the_page(self, cards.render_story_card(item, edition["date"]))

    def test_a_300_character_headline_still_fits(self):
        edition = edition_from([
            story(1, "space", 12, kind="lead", title=LONG_TITLE, dek=LONG_TITLE, source=LONG_NAME,
                  related=[{"source": f"{LONG_NAME} {n}", "title": "t", "url": f"https://example.com/r{n}"}
                           for n in range(1, 8)]),
            story(2, "ai", 4, title=LONG_TITLE, dek=LONG_TITLE, source=LONG_NAME, tag="A Remarkably Long Topic Label " * 3),
            story(3, "ai", 1, title=LONG_TITLE, dek="", source=LONG_NAME),
        ])
        self.assertEqual(len(edition["stories"]), 3)
        for item in edition["stories"]:
            with self.subTest(coverage=item["coverage"]):
                metrics = cards.render_story_card(item, edition["date"])
                assert_inside_the_page(self, metrics)
                self.assertGreaterEqual(metrics["headline_size"], cards.HEADLINE_SIZES[-1])

    def test_todays_long_lead_headline_stays_within_four_lines(self):
        edition = real_edition()
        lead = next(item for item in edition["stories"] if item["is_lead"])
        metrics = cards.render_story_card(lead, edition["date"])
        assert_inside_the_page(self, metrics)
        self.assertLessEqual(metrics["headline_lines"], cards.HEADLINE_LINES)
        self.assertGreaterEqual(metrics["headline_size"], cards.HEADLINE_FLOOR)

    def test_a_short_headline_is_set_large(self):
        edition = edition_from([story(1, "ai", 3, title="Nvidia tops forecasts", dek="A short summary.")])
        metrics = cards.render_story_card(edition["stories"][0], edition["date"])
        assert_inside_the_page(self, metrics)
        self.assertEqual(metrics["headline_size"], cards.HEADLINE_SIZES[0])
        self.assertEqual(metrics["dek_lines"], 1)

    def test_no_summary_on_todays_cards_is_cut(self):
        edition = real_edition()
        with_summary = 0
        for item in edition["stories"]:
            with self.subTest(title=item["title"][:40]):
                text = cards.render_story_card(item, edition["date"])["dek_text"]
                self.assertFalse(text.endswith(("\u2026", "...")), text)
                if text:
                    with_summary += 1
                    self.assertTrue(item["dek"].startswith(text), text)
                    if text != " ".join(item["dek"].split()):
                        # Shorter than the outlet's summary, so it must stop at the end of a sentence.
                        self.assertRegex(text, r"[.!?][\"'\u201d\u2019)]*$")
        self.assertGreater(with_summary, 0)

    def test_an_outlets_cut_off_fragment_is_left_off_the_card(self):
        whole = "Nvidia poured tens of billions into AI startups under Huang."
        edition = edition_from([
            story(1, "ai", 3, title="Founders brace for smaller checks", dek=f"{whole} Without him, VCs are bracing for\u2026"),
            story(2, "ai", 2, title="A story whose only sentence is cut", dek="Regulators said on Friday that the inquiry would\u2026"),
        ])
        first, second = (cards.render_story_card(item, edition["date"]) for item in edition["stories"])
        self.assertEqual(first["dek_text"], whole)
        self.assertEqual(second["dek_lines"], 0)
        for metrics in (first, second):
            assert_inside_the_page(self, metrics)

    def test_a_short_summary_is_set_larger_than_a_long_one(self):
        long_summary = " ".join(["The company said the change takes effect next quarter."] * 4)
        edition = edition_from([
            story(1, "ai", 3, title="Nvidia tops forecasts again", dek="A short summary."),
            story(2, "ai", 2, title="Nvidia tops forecasts again", dek=long_summary),
        ])
        short, long = (cards.render_story_card(item, edition["date"]) for item in edition["stories"])
        self.assertEqual(short["dek_size"], cards.DEK_SIZES[0])
        self.assertGreaterEqual(long["dek_lines"], 3)
        self.assertLessEqual(long["dek_size"], short["dek_size"])
        self.assertIn(long["dek_size"], cards.DEK_SIZES)

    def test_gate_5_the_saved_card_is_a_png_of_the_right_size(self):
        edition = real_edition()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cards" / "one.png"
            cards.render_story_card(edition["stories"][0], edition["date"], path)
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1080, 1350))
                self.assertEqual(image.getpixel((4, 4)), cards.rgb("accent"))
                self.assertEqual(image.getpixel((cards.WIDTH - 5, cards.ACCENT_BAR - 1)), cards.rgb("accent"))
                self.assertEqual(image.getpixel((4, cards.ACCENT_BAR + 8)), cards.rgb("paper"))
            self.assertLess(path.stat().st_size, 1_000_000)


class CoverCardTest(unittest.TestCase):
    def test_todays_cover_fits(self):
        edition = real_edition()
        digest = feed.pick_digest(edition["stories"])
        metrics = cards.render_cover_card(digest, edition["markets"], edition["date"], feed.outlet_total(edition["stories"]))
        assert_inside_the_page(self, metrics)
        self.assertEqual(metrics["rows"], 5)
        self.assertFalse(metrics["clipped"], "a headline on today's cover was cut")
        self.assertGreaterEqual(metrics["lead_size"], 56)
        self.assertGreaterEqual(metrics["title_size"], 30)
        self.assertGreaterEqual(metrics["lead_size"], cards.COVER_LEAD_RATIO * metrics["title_size"])

    def test_a_short_lead_is_set_large_on_the_cover(self):
        edition = edition_from([story(n, "ai", 6 - n, title=f"Nvidia tops forecasts {n}") for n in range(1, 6)])
        metrics = cards.render_cover_card(edition["stories"], edition["markets"], edition["date"], 9)
        assert_inside_the_page(self, metrics)
        self.assertEqual(metrics["lead_size"], cards.COVER_LEAD_SIZES[0])
        self.assertEqual(metrics["title_size"], cards.COVER_ROW_SIZES[0])
        self.assertFalse(metrics["clipped"])

    def test_long_titles_three_stories_and_no_markets_still_fit(self):
        edition = edition_from(
            [story(n, section, 3, title=LONG_TITLE, source=LONG_NAME)
             for n, section in ((1, "ai"), (2, "space"), (3, "robotics"), (4, "big_tech"), (5, "technology"))],
            markets=False,
        )
        for count in (3, 5):
            with self.subTest(count=count):
                metrics = cards.render_cover_card(edition["stories"][:count], [], edition["date"], 40)
                assert_inside_the_page(self, metrics)
                self.assertTrue(metrics["clipped"])

    def test_long_market_names_stay_in_their_column(self):
        edition = real_edition()
        markets = [dict(quote, name="A Very Long Index Name Indeed (Composite)") for quote in edition["markets"]]
        metrics = cards.render_cover_card(feed.pick_digest(edition["stories"]), markets, edition["date"], 15)
        assert_inside_the_page(self, metrics)


class PostCardsTest(unittest.TestCase):
    def test_a_digest_gets_a_cover_and_one_card_per_story_and_they_never_change(self):
        edition = real_edition()
        post = feed.digest_post(feed.pick_digest(edition["stories"]), edition["markets"], edition["date"])
        with tempfile.TemporaryDirectory() as folder:
            out_dir = Path(folder)
            written = cards.render_post_cards(post, edition, out_dir)
            self.assertEqual(len(written), 6)
            self.assertEqual([path.relative_to(out_dir).as_posix() for path in written], post["cards"])
            before = {path: path.read_bytes() for path in written}
            (out_dir / post["cards"][1]).write_bytes(b"already sent")
            self.assertEqual(cards.render_post_cards(post, edition, out_dir), [])
            self.assertEqual((out_dir / post["cards"][1]).read_bytes(), b"already sent")
            self.assertEqual((out_dir / post["cards"][0]).read_bytes(), before[written[0]])

    def test_fit_line_never_exceeds_the_width(self):
        face = cards.font("sans_bold", 28)
        for text in ("SHORT", "A LABEL THAT GOES ON FOR A VERY LONG TIME " * 4, "ONEVERYLONGWORDWITHOUTANYSPACES" * 5):
            fitted = cards.fit_line(text, face, 400, 3)
            self.assertLessEqual(cards.text_width(fitted, face, 3), 400)
            self.assertTrue(fitted)
        self.assertEqual(cards.fit_line("SHORT", face, 400, 3), "SHORT")


if __name__ == "__main__":
    unittest.main()
