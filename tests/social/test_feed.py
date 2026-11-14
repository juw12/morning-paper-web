"""Parsing, story selection and the text of every post."""
import unittest

import helpers
from helpers import edition_from, real_edition, story

import social_feed as feed

LONG = "An extraordinarily long headline that keeps going well past any sensible length " * 6


def all_texts(post: dict) -> list[str]:
    return [post["telegram"], post["threads"], post["instagram"], *post["x"], *post["alts"]]


def hard_edition() -> dict:
    """Worst-case input: very long titles, summaries and outlet names, with markup characters in them."""
    stories = [
        story(1, "space", 9, kind="lead", title=LONG, dek=LONG * 3, source="The Extremely Long Named Gazette of Record",
              related=[{"source": f"Another Very Long Outlet Name {n}", "title": LONG, "url": f"https://example.com/r{n}"}
                       for n in range(1, 9)]),
        story(2, "ai", 5, title=LONG, dek=LONG * 3, source="A <b>Bold</b> & Co"),
        story(3, "ai", 4, title=LONG, url="https://example.com/" + "p" * 600),
        story(4, "big_tech", 3, title=LONG),
        story(5, "robotics", 3, title=LONG, kind="row"),
        story(6, "markets_news", 3, title=LONG, dek=""),
        story(7, "technology", 1, title=LONG),
    ]
    return edition_from(stories)


class ParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edition = real_edition()

    def test_reads_the_published_page(self):
        edition = self.edition
        self.assertEqual(edition["date"], "2026-11-14")
        self.assertRegex(edition["updated"], r"^\d{1,2}:\d{2}$")
        self.assertEqual(len(edition["stories"]), 32)
        self.assertEqual(feed.outlet_total(edition["stories"]), 15)
        self.assertEqual(len(edition["markets"]), 5)
        self.assertEqual(len({item["id"] for item in edition["stories"]}), 32)

    def test_every_story_is_complete(self):
        for item in self.edition["stories"]:
            self.assertTrue(item["title"] and item["source"] and item["section"], item)
            self.assertTrue(item["url"].startswith("http"), item)
            self.assertIn(item["section_id"], feed.SECTION_COMMANDS, item)
            self.assertGreaterEqual(item["coverage"], 1)

    def test_lead_carries_the_other_outlets(self):
        leads = [item for item in self.edition["stories"] if item["is_lead"]]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["coverage"], 5)
        self.assertEqual(len(feed.outlet_names(leads[0])), 5)

    def test_markets_have_direction_and_size(self):
        for quote in self.edition["markets"]:
            self.assertIn(quote["dir"], ("up", "down", "flat"))
            self.assertGreaterEqual(quote["pct"], 0)
            self.assertTrue(quote["name"])

    def test_page_without_a_date_gives_an_empty_date(self):
        edition = feed.parse_edition("<html><head><title>Morrow</title></head><body></body></html>")
        self.assertEqual(edition["date"], "")
        self.assertEqual(edition["stories"], [])

    def test_emoji_is_removed_from_headlines_and_summaries(self):
        edition = edition_from([story(1, title="\U0001F680 Rocket lifts off \U0001F525\uFE0F today", dek="Big \u2728 day")])
        item = edition["stories"][0]
        self.assertEqual(item["title"], "Rocket lifts off today")
        self.assertEqual(item["dek"], "Big day")

    def test_a_story_shown_twice_is_kept_once_with_the_higher_count(self):
        twice = [story(1, "ai", 2, kind="lead"), story(1, "ai", 4), story(2, "ai", 1)]
        edition = edition_from(twice)
        self.assertEqual(len(edition["stories"]), 2)
        self.assertEqual(edition["stories"][0]["coverage"], 4)


class SelectionTest(unittest.TestCase):
    def test_digest_is_five_stories_lead_first_two_per_section(self):
        edition = real_edition()
        digest = feed.pick_digest(edition["stories"])
        self.assertEqual(len(digest), 5)
        self.assertTrue(digest[0]["is_lead"])
        self.assertTrue(digest[0]["title"].startswith("SpaceX launches Starship"))
        for section in {item["section_id"] for item in digest}:
            self.assertLessEqual(sum(item["section_id"] == section for item in digest), feed.MAX_PER_SECTION)
        counts = [item["coverage"] for item in digest[1:]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_alerts_need_three_outlets_and_skip_used_stories(self):
        edition = edition_from([story(1, "ai", 4), story(2, "ai", 3), story(3, "space", 2), story(4, "space", 1)])
        ids = [item["id"] for item in edition["stories"]]
        candidates = feed.alert_candidates(edition["stories"], set())
        self.assertEqual([item["id"] for item in candidates], ids[:2])
        self.assertEqual([item["id"] for item in feed.alert_candidates(edition["stories"], {ids[0]})], [ids[1]])

    def test_todays_page_has_no_alert_outside_the_digest(self):
        edition = real_edition()
        used = {item["id"] for item in feed.pick_digest(edition["stories"])}
        self.assertEqual(feed.alert_candidates(edition["stories"], used), [])


class TextTest(unittest.TestCase):
    def test_x_counts_a_link_as_23_and_wide_characters_as_2(self):
        self.assertEqual(feed.x_length("abc"), 3)
        self.assertEqual(feed.x_length("see https://example.com/" + "a" * 200), 4 + 23)
        self.assertEqual(feed.x_length("\u6f22\u5b57"), 4)

    def test_telegram_length_ignores_tags_and_links(self):
        self.assertEqual(feed.visible_length('<b>Hi</b> <a href="https://example.com/long">there</a> &amp; you'), 14)

    def test_truncate_cuts_at_a_word_and_never_exceeds_the_limit(self):
        text = "one two three four five six"
        for limit in range(0, len(text) + 2):
            cut = feed.truncate(text, limit)
            self.assertLessEqual(len(cut), limit)
            if cut and cut != text:
                self.assertTrue(cut.endswith("\u2026"))
                self.assertTrue(text.startswith(cut[:-1]))
            if len(cut) > len("one\u2026") and cut != text:
                self.assertEqual(text[len(cut) - 1], " ", cut)
        self.assertEqual(feed.truncate(text, len(text)), text)

    def test_truncate_cuts_inside_a_single_word_that_cannot_fit(self):
        self.assertEqual(feed.truncate("one two", 3), "on\u2026")
        self.assertEqual(feed.truncate("a" * 50, 10), "a" * 9 + "\u2026")
        self.assertEqual(feed.truncate("abc def", 1), "")
        self.assertEqual(feed.truncate("abc def", 0), "")

    def test_sentences_do_not_break_on_abbreviations(self):
        text = "SpaceX flew today (Nov. 13) from Texas. The U.S. Navy watched. Acme Inc. said it was pleased."
        self.assertEqual(feed.sentences(text), [
            "SpaceX flew today (Nov. 13) from Texas.",
            "The U.S. Navy watched.",
            "Acme Inc. said it was pleased.",
        ])
        self.assertEqual(feed.sentences("No full stop here"), ["No full stop here"])

    def test_a_summary_is_kept_as_whole_sentences(self):
        first = "OpenAI is launching a wallet for its agents this week."
        dek = f"{first} ChatGPT Wallet is rolling out\u2026"
        self.assertEqual(feed.fit_dek(dek, 500), first)
        self.assertEqual(feed.fit_dek(dek, len(first)), first)
        self.assertEqual(feed.fit_dek(dek, len(first) - 1, cut=False), "")
        cut = feed.fit_dek(dek, len(first) - 1)
        self.assertTrue(cut.endswith("\u2026") and len(cut) <= len(first) - 1, cut)
        self.assertEqual(feed.fit_dek("Short and whole.", 200), "Short and whole.")
        self.assertEqual(feed.fit_dek("A summary with no full stop that the outlet cut off\u2026", 200, cut=False), "")
        self.assertEqual(feed.fit_dek(first, feed.MIN_DEK - 1), "")
        self.assertEqual(feed.fit_dek("", 500), "")
        for room in range(0, 130):
            self.assertLessEqual(len(feed.fit_dek(dek, room)), room)
            self.assertLessEqual(feed.x_length(feed.fit_dek(dek, room, feed.x_length)), room)

    def test_outlet_phrase_states_only_what_the_page_shows(self):
        edition = edition_from([
            story(1, "ai", 5, kind="lead", source="CNBC",
                  related=[{"source": name, "title": "t", "url": f"https://example.com/{name}"}
                           for name in ("Reuters", "Wired", "Ars Technica", "Axios")]),
            story(2, "ai", 3, source="The Verge"),
            story(3, "ai", 1, source="Wired"),
        ])
        lead, counted, single = edition["stories"]
        self.assertEqual(feed.outlets_phrase(lead, 2), "5 outlets: CNBC, Reuters +3")
        self.assertEqual(feed.outlets_phrase(lead, 9), "5 outlets: CNBC, Reuters, Wired, Ars Technica, Axios")
        self.assertEqual(feed.outlets_phrase(counted), "3 outlets, first: The Verge")
        self.assertEqual(feed.outlets_phrase(single), "via Wired")


class PostTest(unittest.TestCase):
    def posts(self, edition: dict) -> list[dict]:
        digest_stories = feed.pick_digest(edition["stories"])
        posts = [feed.digest_post(digest_stories, edition["markets"], edition["date"])]
        posts += [feed.story_post(item, edition["date"]) for item in edition["stories"]]
        return posts

    def test_gate_1_every_text_fits_its_platform_on_todays_page(self):
        for post in self.posts(real_edition()):
            self.assertEqual(feed.post_problems(post), [], post["id"])

    def test_gate_1_every_text_fits_its_platform_on_worst_case_input(self):
        for post in self.posts(hard_edition()):
            self.assertEqual(feed.post_problems(post), [], post["id"])
            self.assertLessEqual(feed.visible_length(post["telegram"]), 1024)
            self.assertLessEqual(len(post["threads"]), 500)
            self.assertLessEqual(len(post["instagram"]), 2200)
            for text in post["x"]:
                self.assertLessEqual(feed.x_length(text), 280)
            for alt in post["alts"]:
                self.assertLessEqual(len(alt), 400)

    def test_gate_2_every_post_names_its_outlet_and_links_to_it(self):
        for edition in (real_edition(), hard_edition()):
            by_id = {item["id"]: item for item in edition["stories"]}
            for post in self.posts(edition):
                for story_id in post["story_ids"]:
                    item = by_id[story_id]
                    source = item["source"]
                    self.assertIn(feed.esc(source), post["telegram"], post["id"])
                    self.assertIn(source, post["instagram"], post["id"])
                    self.assertIn(source, post["threads"], post["id"])
                    self.assertTrue(any(source in text for text in post["x"]), post["id"])
                    self.assertIn(feed.htmllib.escape(item["url"], quote=True), post["telegram"], post["id"])
                    self.assertTrue(any(item["url"] in text for text in post["x"]), post["id"])
                self.assertIn("http", post["threads"])

    def test_gate_3_no_emoji_in_any_text(self):
        edition = edition_from([
            story(n, "ai", 4 - n % 3, title=f"\U0001F4A5 Loud headline {n} \u2757", dek="Wow \U0001F62E")
            for n in range(1, 7)
        ])
        for post in self.posts(edition) + self.posts(real_edition()):
            for text in all_texts(post):
                self.assertFalse(feed.has_emoji(text), text)
        for reply in feed.bot_replies(real_edition()).values():
            self.assertFalse(feed.has_emoji(reply), reply)

    def test_markup_in_a_headline_is_escaped_for_telegram(self):
        edition = edition_from([story(1, "ai", 3, title='Chips <script> & "quotes"', source="A <b>Bold</b> & Co")])
        post = feed.story_post(edition["stories"][0], edition["date"])
        self.assertIn("Chips &lt;script&gt; &amp; \"quotes\"", post["telegram"])
        self.assertNotIn("<script>", post["telegram"])
        self.assertIn("A &lt;b&gt;Bold&lt;/b&gt; &amp; Co", post["telegram"])

    def test_digest_shape(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        post = feed.digest_post(stories, edition["markets"], edition["date"])
        self.assertEqual(post["id"], "digest-2026-11-14")
        self.assertEqual(post["kind"], "digest")
        self.assertEqual(len(post["cards"]), 6)
        self.assertEqual(len(post["alts"]), 6)
        self.assertEqual(len(post["x"]), 5)
        self.assertTrue(post["x"][0].startswith("Morrow Brief"))
        self.assertIn("1/5", post["x"][0])
        self.assertIn("5/5", post["x"][4])
        self.assertIn("Markets:", post["telegram"])
        self.assertIn(feed.SITE_URL, post["telegram"])
        self.assertIn(feed.DISCLOSURE, post["instagram"])

    def test_todays_digest_never_cuts_a_headline(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        post = feed.digest_post(stories, edition["markets"], edition["date"])
        for text in (post["telegram"], post["threads"], post["instagram"], *post["x"]):
            self.assertNotIn("\u2026", text)
        for number, item in enumerate(stories):
            self.assertIn(feed.esc(item["title"]), post["telegram"])
            self.assertIn(item["title"], post["instagram"])
            self.assertIn(item["title"], post["x"][number])

    def test_threads_digest_prints_whole_headlines_and_names_the_rest_by_outlet(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        text = feed.digest_threads(stories, edition["date"])
        shown = [item for item in stories if item["title"] in text]
        left_out = [item for item in stories if item["title"] not in text]
        self.assertGreaterEqual(len(shown), feed.MIN_THREADS_STORIES)
        self.assertEqual(shown, stories[:len(shown)])
        self.assertTrue(left_out, "today's five headlines do not fit 500 characters whole")
        footer = text.splitlines()[-1]
        self.assertTrue(footer.startswith(f"+{len(left_out)} more from "), footer)
        for item in left_out:
            self.assertIn(item["source"], footer)
        self.assertTrue(footer.endswith(feed.SITE_URL))
        self.assertNotIn("each linked", text)

    def test_threads_digest_lists_every_story_when_all_fit(self):
        edition = edition_from([story(n, "ai", 6 - n, title=f"Short headline number {n}") for n in range(1, 6)])
        stories = feed.pick_digest(edition["stories"])
        text = feed.digest_threads(stories, edition["date"])
        for item in stories:
            self.assertIn(item["title"], text)
        self.assertNotIn(" more from ", text)
        self.assertIn(f"every story linked to its source: {feed.SITE_URL}", text)

    def test_threads_digest_keeps_every_story_when_headlines_are_too_long(self):
        stories = feed.pick_digest(hard_edition()["stories"])
        text = feed.digest_threads(stories, "2026-11-14")
        self.assertLessEqual(len(text), 500)
        self.assertEqual(sum(line[:2] in ("1.", "2.", "3.", "4.", "5.") for line in text.splitlines()), 5)

    def test_x_thread_carries_a_summary_where_whole_sentences_fit(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        thread = feed.digest_x(stories, edition["date"])
        with_summary = 0
        for item, text in zip(stories, thread):
            self.assertLessEqual(feed.x_length(text), 280)
            middle = text.split("\n\n")[-2] if text.count("\n\n") >= 2 + (item is stories[0]) else ""
            if middle:
                with_summary += 1
                self.assertIn(middle, item["dek"])
                self.assertRegex(middle, r"[.!?]$")
        self.assertGreaterEqual(with_summary, 3)

    def test_telegram_digest_links_every_outlet_the_page_names_for_the_lead(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        text = feed.digest_telegram(stories, edition["markets"], edition["date"])
        lead = stories[0]
        self.assertEqual(len(lead["related"]), 4)
        for item in lead["related"]:
            self.assertIn(feed.link(item["url"], item["source"]), text)
        self.assertLessEqual(feed.visible_length(text), 1024)

    def test_instagram_digest_gives_each_story_a_whole_sentence_summary(self):
        edition = real_edition()
        stories = feed.pick_digest(edition["stories"])
        text = feed.digest_instagram(stories, edition["markets"], edition["date"])
        for item in stories:
            summary = feed.fit_dek(item["dek"], feed.DIGEST_DEK, cut=False)
            self.assertTrue(summary, item["title"])
            self.assertIn(f"   {summary}\n   Reported by", text)

    def test_post_problems_catches_a_bad_post(self):
        edition = real_edition()
        post = feed.story_post(edition["stories"][0], edition["date"])
        self.assertEqual(feed.post_problems(post), [])
        self.assertTrue(feed.post_problems({**post, "x": ["word " * 80 + "https://example.com"]}))
        self.assertTrue(feed.post_problems({**post, "threads": post["threads"] + " \U0001F600"}))
        self.assertTrue(feed.post_problems({**post, "threads": "no link here"}))
        self.assertTrue(feed.post_problems({**post, "telegram": "plain text"}))
        self.assertTrue(feed.post_problems({**post, "alts": []}))


class BotReplyTest(unittest.TestCase):
    def test_every_reply_fits_one_telegram_message(self):
        for edition in (real_edition(), hard_edition()):
            for command, reply in feed.bot_replies(edition).items():
                self.assertLessEqual(feed.visible_length(reply), feed.LIMITS["telegram_message"], command)
                self.assertTrue(reply.strip(), command)

    def test_commands_cover_every_section_on_the_page(self):
        replies = feed.bot_replies(real_edition())
        for command in ("/start", "/help", "/today", "/about", "/tape", "/sources",
                        "/ai", "/bigtech", "/robotics", "/space", "/tech", "/markets"):
            self.assertIn(command, replies)
        self.assertIn("32 stories from 15 outlets", replies["/sources"])

    def test_search(self):
        stories = real_edition()["stories"]
        self.assertIn("Nvidia", feed.search_reply(stories, "nvidia"))
        self.assertIn("Send /find and a word", feed.search_reply(stories, " "))
        missing = feed.search_reply(stories, "zzzz <b>")
        self.assertIn("Nothing on", missing)
        self.assertIn("&lt;b&gt;", missing)

    def test_public_feed_holds_no_delivery_state(self):
        edition = real_edition()
        public = feed.public_feed(edition, [])
        self.assertEqual(public["stats"], {"stories": 32, "outlets": 15})
        self.assertEqual(set(public), {"brand", "site", "date", "updated", "stats", "markets", "stories", "posts", "bot"})


if __name__ == "__main__":
    unittest.main()
