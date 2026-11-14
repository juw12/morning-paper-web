"""The Telegram bot: its replies, and the poller's handling of offsets, webhooks and failures."""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import requests

import helpers
from helpers import FIXTURES, FakeHttp, FakeResponse, real_edition

import social_bot as bot
import social_feed as feed

TOKEN = "123456789:AAExampleBotTokenThatMustNeverLeak"


def load_cases() -> dict:
    return json.loads((FIXTURES / "bot_cases.json").read_text(encoding="utf-8"))


def message(update_id: int, text: str, chat_type: str = "private", chat_id: int = 500) -> dict:
    return {"update_id": update_id, "message": {"text": text, "chat": {"id": chat_id, "type": chat_type}}}


def updates(*items: dict) -> FakeResponse:
    return FakeResponse(200, {"ok": True, "result": list(items)})


SENT = FakeResponse(200, {"ok": True, "result": {"message_id": 1}})
NOTHING_NEW = updates()


def calls_to(http: FakeHttp, method: str) -> list[dict]:
    return [kwargs["json"] for url, kwargs in http.calls if url.endswith("/" + method)]


class ReplyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = load_cases()
        cls.feed = cls.fixture["feed"]

    def test_every_recorded_message_gets_the_recorded_reply(self):
        self.assertGreaterEqual(len(self.fixture["cases"]), 20)
        for case in self.fixture["cases"]:
            with self.subTest(text=case["text"], private=case["private"]):
                self.assertEqual(bot.reply_for(self.feed, case["text"], case["private"]), case["reply"])

    def test_the_fixture_matches_what_the_feed_builder_writes_today(self):
        self.assertEqual(self.feed["bot"], feed.public_feed(real_edition(), [])["bot"])

    def test_every_reply_fits_a_telegram_message_and_has_no_emoji(self):
        for command, reply in self.feed["bot"].items():
            with self.subTest(command=command):
                self.assertLessEqual(feed.visible_length(reply), feed.LIMITS["telegram_message"])
                self.assertFalse(feed.has_emoji(reply))
                self.assertTrue(reply.strip())

    def test_every_section_on_the_page_has_its_command(self):
        sections = {item["section_id"] for item in self.feed["stories"]}
        for section in sections:
            self.assertIn(feed.SECTION_COMMANDS[section], self.feed["bot"])
        for command in ("/start", "/help", "/today", "/tape", "/sources", "/about"):
            self.assertIn(command, self.feed["bot"])

    def test_today_lists_the_five_digest_stories_with_links(self):
        reply = bot.reply_for(self.feed, "/today")
        self.assertEqual(reply.count("\n• "), 5)
        self.assertEqual(reply.count("<a href="), 5)

    def test_find_matches_every_word_and_escapes_the_query(self):
        hit = bot.reply_for(self.feed, "/find nvidia")
        self.assertIn("<a href=", hit)
        self.assertIn("nvidia", hit.lower())
        miss = bot.reply_for(self.feed, "/find zzzzqqq <b>")
        self.assertIn("&lt;b&gt;", miss)
        self.assertNotIn("<b>", miss)

    def test_a_group_is_only_answered_when_it_sends_a_command(self):
        self.assertIsNone(bot.reply_for(self.feed, "hello there", private=False))
        self.assertIsNotNone(bot.reply_for(self.feed, "/today@MorrowBriefBot", private=False))
        self.assertEqual(bot.reply_for(self.feed, "hello there", private=True), self.feed["bot"]["/help"])

    def test_before_the_first_edition_the_bot_says_so(self):
        for empty in ({}, {"bot": {}}):
            self.assertIn("not ready", bot.reply_for(empty, "/today"))
            self.assertIn("not ready", bot.reply_for(empty, "hi"))

    def test_a_section_missing_from_the_page_gets_a_plain_answer(self):
        thin = {"bot": {"/help": "menu", "/today": "today"}, "stories": []}
        self.assertIn("Nothing under that heading", bot.reply_for(thin, "/space"))
        self.assertEqual(bot.reply_for(thin, "/nonsense"), "menu")

    def test_command_of_drops_the_bot_name_and_case(self):
        self.assertEqual(bot.command_of("/Find@MorrowBriefBot  nvidia chips "), ("/find", "nvidia chips"))
        self.assertEqual(bot.command_of("/today"), ("/today", ""))


class PollTest(unittest.TestCase):
    def setUp(self):
        self.feed = load_cases()["feed"]
        self.http = FakeHttp()

    def poll(self, listen: int = 0) -> list[str]:
        return bot.poll(self.http, TOKEN, self.feed, listen, clock=lambda: 0.0)

    def test_answers_then_acknowledges_so_nothing_repeats(self):
        self.http.telegram = [
            updates(message(10, "/today"), message(11, "hello", "supergroup")),
            SENT,
            NOTHING_NEW,
        ]
        log = self.poll()
        self.assertEqual(log, ["answered /today"])
        fetches = calls_to(self.http, "getUpdates")
        self.assertEqual(len(fetches), 2)
        self.assertNotIn("offset", fetches[0])
        self.assertEqual(fetches[1]["offset"], 12)
        self.assertEqual(fetches[0]["allowed_updates"], ["message"])

    def test_the_reply_is_html_without_a_link_preview(self):
        self.http.telegram = [updates(message(10, "/today", chat_id=42)), SENT, NOTHING_NEW]
        self.poll()
        sent = calls_to(self.http, "sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["chat_id"], 42)
        self.assertEqual(sent[0]["text"], self.feed["bot"]["/today"])
        self.assertEqual(sent[0]["parse_mode"], "HTML")
        self.assertEqual(sent[0]["link_preview_options"], {"is_disabled": True})

    def test_a_group_message_that_is_not_a_command_gets_no_reply(self):
        self.http.telegram = [updates(message(10, "good morning all", "group")), NOTHING_NEW]
        self.assertEqual(self.poll(), [])
        self.assertEqual(calls_to(self.http, "sendMessage"), [])
        self.assertEqual(calls_to(self.http, "getUpdates")[-1]["offset"], 11)

    def test_a_webhook_means_the_worker_answers_and_polling_stops(self):
        self.http.telegram = [FakeResponse(409, {"ok": False, "description": "Conflict: webhook is active"})]
        log = self.poll()
        self.assertEqual(len(self.http.calls), 1)
        self.assertIn("webhook", log[0])

    def test_a_message_that_cannot_be_answered_is_skipped_not_retried(self):
        blocked = FakeResponse(403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
        self.http.telegram = [updates(message(10, "/today")), blocked, NOTHING_NEW]
        log = self.poll()
        self.assertIn("could not answer /today", log[0])
        self.assertEqual(calls_to(self.http, "getUpdates")[-1]["offset"], 11)
        self.assertEqual(len(calls_to(self.http, "sendMessage")), 1)

    def test_the_token_never_reaches_the_log(self):
        leaky = FakeResponse(401, {"ok": False, "description": f"Unauthorized for bot{TOKEN} at /bot{TOKEN}/getUpdates"})
        self.http.telegram = [leaky]
        log = self.poll()
        self.assertTrue(log)
        self.assertNotIn(TOKEN, " ".join(log))
        self.assertNotIn("AAExample", " ".join(log))
        self.http = FakeHttp()
        self.http.telegram = [updates(message(10, "/today")), leaky, NOTHING_NEW]
        self.assertNotIn("AAExample", " ".join(self.poll()))

    def test_no_network_ends_the_run_quietly(self):
        self.http.telegram = [requests.exceptions.ConnectionError("down")]
        log = self.poll()
        self.assertEqual(len(log), 1)
        self.assertIn("unreachable", log[0])

    def test_a_reply_that_times_out_does_not_stop_the_run(self):
        self.http.telegram = [
            updates(message(10, "/today"), message(11, "/tape")),
            requests.exceptions.ReadTimeout("slow"),
            SENT,
            NOTHING_NEW,
        ]
        log = self.poll()
        self.assertEqual(log, ["could not answer: ReadTimeout", "answered /tape"])
        self.assertEqual(calls_to(self.http, "getUpdates")[-1]["offset"], 12)

    def test_a_busy_chat_cannot_keep_the_run_alive_forever(self):
        # Every call returns one more message, so the run must end by its own limit.
        counter = {"next": 100}

        class Endless(FakeHttp):
            def post(inner, url, **kwargs):
                inner.calls.append((url, kwargs))
                if url.endswith("/getUpdates"):
                    counter["next"] += 1
                    return updates(message(counter["next"], "/today"))
                return SENT

        self.http = Endless()
        log = self.poll()
        fetches = calls_to(self.http, "getUpdates")
        self.assertEqual(len(fetches), bot.MAX_CLOSING_ROUNDS + 2)
        self.assertEqual(len(log), bot.MAX_CLOSING_ROUNDS + 1)
        # The last call acknowledges everything that was answered and asks for at most one more.
        self.assertEqual(fetches[-1]["limit"], 1)
        self.assertEqual(fetches[-1]["offset"], 100 + bot.MAX_CLOSING_ROUNDS + 2)
        self.assertEqual(len(calls_to(self.http, "sendMessage")), bot.MAX_CLOSING_ROUNDS + 1)

    def test_listening_uses_long_polls_until_the_time_is_up(self):
        ticks = iter([0.0, 0.0, 30.0, 61.0, 61.0])
        self.http.telegram = [NOTHING_NEW]
        bot.poll(self.http, TOKEN, self.feed, 60, clock=lambda: next(ticks))
        waits = [payload["timeout"] for payload in calls_to(self.http, "getUpdates")]
        self.assertEqual(waits, [bot.LONG_POLL_SECONDS, bot.LONG_POLL_SECONDS, 0])


class CommandTest(unittest.TestCase):
    def run_main(self, argv: list[str], env: dict) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), contextlib.redirect_stdout(output):
            for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"):
                if name not in env:
                    os.environ.pop(name, None)
            code = bot.main(argv)
        return code, output.getvalue()

    def test_poll_without_a_token_does_nothing_and_succeeds(self):
        code, text = self.run_main(["poll", "--feed", "missing.json", "--listen", "0"], {})
        self.assertEqual(code, 0)
        self.assertIn("not set", text)

    def test_set_webhook_needs_both_secrets_and_https(self):
        code, text = self.run_main(["set-webhook", "--url", "https://example.workers.dev"], {"TELEGRAM_BOT_TOKEN": TOKEN})
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, text)
        code, text = self.run_main(
            ["set-webhook", "--url", "http://example.workers.dev"],
            {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_WEBHOOK_SECRET": "s3cret"},
        )
        self.assertEqual(code, 1)
        self.assertIn("https://", text)

    def test_set_webhook_sends_the_secret_and_only_asks_for_messages(self):
        http = FakeHttp()
        with mock.patch.object(bot, "requests", http):
            code, text = self.run_main(
                ["set-webhook", "--url", "https://example.workers.dev"],
                {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_WEBHOOK_SECRET": "s3cret"},
            )
        self.assertEqual(code, 0)
        self.assertIn("webhook set", text)
        payload = calls_to(http, "setWebhook")[0]
        self.assertEqual(payload["secret_token"], "s3cret")
        self.assertEqual(payload["allowed_updates"], ["message"])
        self.assertNotIn("s3cret", text)


if __name__ == "__main__":
    unittest.main()
