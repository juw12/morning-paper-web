"""Scheduling, freezing, payloads and delivery, with a fake HTTP client. Nothing here touches the network."""
import contextlib
import datetime as dt
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import requests

import helpers
from helpers import FakeHttp, FakeResponse, edition_from, real_edition, story

import social_feed as feed
import social_post as post_module

WIB = post_module.WIB
TOKEN = "123456789:AAExampleBotTokenThatMustNeverLeak"
API_KEY = "buffer-key-that-must-never-leak"
ENV = {
    "TELEGRAM_BOT_TOKEN": TOKEN,
    "TELEGRAM_CHAT_ID": "@morrowbrief",
    "BUFFER_API_KEY": API_KEY,
    "MORROW_BUFFER_CHANNELS": "ig-1, th-1 x-1",
}
CHANNELS = [
    {"id": "personal-ig", "displayName": "Juwen personal", "service": "instagram", "isDisconnected": False},
    {"id": "ig-1", "displayName": "Morrow Brief", "service": "instagram", "isDisconnected": False},
    {"id": "th-1", "displayName": "Morrow Brief", "service": "threads", "isDisconnected": False},
    {"id": "x-1", "displayName": "Morrow Brief", "service": "twitter", "isDisconnected": False},
    {"id": "li-1", "displayName": "Juwen", "service": "linkedin", "isDisconnected": False},
]
IMAGE_BASE = "https://raw.githubusercontent.com/juw12/morrow/abc123/"


def at(hour: int, minute: int = 0, day: int = 14) -> dt.datetime:
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=WIB)


def alert_edition() -> dict:
    """Five digest stories plus six more that three or more outlets report."""
    stories = [story(1, "space", 6, kind="lead")]
    stories += [story(n, section, 5) for n, section in ((2, "ai"), (3, "ai"), (4, "big_tech"), (5, "big_tech"))]
    stories += [story(n, "robotics", 4) for n in (6, 7)]
    stories += [story(n, "technology", 3) for n in (8, 9, 10, 11)]
    stories += [story(12, "markets_news", 2), story(13, "markets_news", 1)]
    return edition_from(stories)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.edition = alert_edition()
        self.state = post_module.empty_state()

    def freeze_next(self, now: dt.datetime) -> dict | None:
        post, _ = post_module.plan(self.edition, self.state, now)
        if post:
            post_module.freeze(self.state, post, now)
        return post

    def test_page_without_a_date_posts_nothing(self):
        post, reason = post_module.plan({**self.edition, "date": ""}, self.state, at(8))
        self.assertIsNone(post)
        self.assertIn("no readable date", reason)

    def test_stale_page_posts_nothing(self):
        post, reason = post_module.plan(self.edition, self.state, at(8, day=15))
        self.assertIsNone(post)
        self.assertIn("stale page", reason)

    def test_nothing_outside_the_window(self):
        for moment in (at(5, 59), at(22, 0), at(23, 30), at(0, 10)):
            post, reason = post_module.plan(self.edition, self.state, moment)
            self.assertIsNone(post, moment)
            self.assertIn("outside", reason)
        self.assertIsNotNone(post_module.plan(self.edition, self.state, at(6, 0))[0])
        self.assertIsNotNone(post_module.plan(self.edition, self.state, at(21, 59))[0])

    def test_the_day_is_judged_in_jakarta_time(self):
        utc_evening_before = dt.datetime(2026, 11, 13, 23, 30, tzinfo=dt.timezone.utc)
        post, _ = post_module.plan(self.edition, self.state, utc_evening_before)
        self.assertEqual(post["id"], "digest-2026-11-14")

    def test_first_post_of_the_day_is_the_digest_and_there_is_only_one(self):
        first = self.freeze_next(at(7))
        self.assertEqual(first["kind"], "digest")
        self.assertEqual(len(first["story_ids"]), 5)
        later = [self.freeze_next(at(7) + dt.timedelta(minutes=100 * step)) for step in range(1, 6)]
        self.assertTrue(all(item is None or item["kind"] == "alert" for item in later))
        digests = [item for item in self.state["posts"].values() if item["kind"] == "digest"]
        self.assertEqual(len(digests), 1)

    def test_a_thin_page_gets_no_digest(self):
        thin = edition_from([story(1, "ai", 3), story(2, "ai", 2)])
        post, reason = post_module.plan(thin, self.state, at(8))
        self.assertIsNone(post)
        self.assertIn("a digest needs 3", reason)

    def test_alerts_wait_ninety_minutes(self):
        self.freeze_next(at(7))
        post, reason = post_module.plan(self.edition, self.state, at(8, 29))
        self.assertIsNone(post)
        self.assertIn("alerts wait 90", reason)
        post, _ = post_module.plan(self.edition, self.state, at(8, 30))
        self.assertEqual(post["kind"], "alert")

    def test_at_most_four_alerts_a_day_and_never_a_repeat(self):
        frozen = [self.freeze_next(at(7) + dt.timedelta(minutes=91 * step)) for step in range(0, 9)]
        alerts = [item for item in frozen if item and item["kind"] == "alert"]
        self.assertEqual(len(alerts), post_module.MAX_ALERTS_PER_DAY)
        posted = [story_id for item in frozen if item for story_id in item["story_ids"]]
        self.assertEqual(len(posted), len(set(posted)), "gate 4: a story was posted twice")
        post, reason = post_module.plan(self.edition, self.state, at(21, 30))
        self.assertIsNone(post)
        self.assertIn("4 alerts are used", reason)

    def test_alert_needs_three_outlets(self):
        edition = edition_from([story(n, "ai", 2) for n in range(1, 4)] + [story(n, "space", 2) for n in range(4, 9)])
        state = post_module.empty_state()
        digest, _ = post_module.plan(edition, state, at(7))
        post_module.freeze(state, digest, at(7))
        post, reason = post_module.plan(edition, state, at(10))
        self.assertIsNone(post)
        self.assertIn("3 or more outlets", reason)

    def test_freeze_refuses_a_story_already_posted_today(self):
        digest = self.freeze_next(at(7))
        by_id = {item["id"]: item for item in self.edition["stories"]}
        repeat = feed.story_post(by_id[digest["story_ids"][0]], self.edition["date"])
        with self.assertRaises(ValueError):
            post_module.freeze(self.state, repeat, at(9))

    def test_freezing_twice_changes_nothing(self):
        post, _ = post_module.plan(self.edition, self.state, at(7))
        first = post_module.freeze(self.state, post, at(7))
        again = post_module.freeze(self.state, post, at(7, 30))
        self.assertIs(first, again)
        self.assertEqual(first["created_at"], "2026-11-14T00:00:00+00:00")
        self.assertEqual(set(first["targets"]), set(post_module.TARGETS))


class PayloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        edition = real_edition()
        cls.digest = feed.digest_post(feed.pick_digest(edition["stories"]), edition["markets"], edition["date"])
        cls.alert = feed.story_post(edition["stories"][7], edition["date"])

    def test_required_buffer_fields(self):
        for target in ("instagram", "threads", "x"):
            payload = post_module.buffer_input(self.digest, target, "channel-9", IMAGE_BASE)
            self.assertEqual(payload["channelId"], "channel-9")
            self.assertEqual(payload["mode"], "shareNow")
            self.assertEqual(payload["schedulingType"], "automatic")
            self.assertIs(payload["needsApproval"], False)
            self.assertTrue(payload["assets"])
            for asset in payload["assets"]:
                self.assertTrue(asset["image"]["url"].startswith(IMAGE_BASE + "cards/2026-11-14/"))
                self.assertTrue(asset["image"]["metadata"]["altText"])

    def test_instagram_digest_is_a_carousel_and_an_alert_a_single_post(self):
        digest = post_module.buffer_input(self.digest, "instagram", "c", IMAGE_BASE)
        self.assertEqual(len(digest["assets"]), 6)
        self.assertEqual(digest["metadata"]["instagram"], {"type": "carousel", "shouldShareToFeed": True})
        alert = post_module.buffer_input(self.alert, "instagram", "c", IMAGE_BASE)
        self.assertEqual(len(alert["assets"]), 1)
        self.assertEqual(alert["metadata"]["instagram"]["type"], "post")

    def test_threads_carries_one_image(self):
        payload = post_module.buffer_input(self.digest, "threads", "c", IMAGE_BASE)
        self.assertEqual(len(payload["assets"]), 1)
        self.assertEqual(payload["text"], self.digest["threads"])
        self.assertNotIn("metadata", payload)

    def test_x_digest_is_one_thread_with_the_cover_on_the_first_post(self):
        payload = post_module.buffer_input(self.digest, "x", "c", IMAGE_BASE)
        thread = payload["metadata"]["twitter"]["thread"]
        self.assertEqual([item["text"] for item in thread], self.digest["x"])
        self.assertEqual(payload["text"], thread[0]["text"])
        self.assertEqual(len(thread[0]["assets"]), 1)
        self.assertTrue(all(item["assets"] == [] for item in thread[1:]))
        self.assertNotIn("metadata", post_module.buffer_input(self.alert, "x", "c", IMAGE_BASE))

    def test_unknown_target_is_refused(self):
        with self.assertRaises(ValueError):
            post_module.buffer_input(self.digest, "linkedin", "c", IMAGE_BASE)

    def test_only_the_digest_notifies_on_telegram(self):
        digest = post_module.telegram_fields(self.digest, "@chat")
        alert = post_module.telegram_fields(self.alert, "@chat")
        self.assertEqual(digest["disable_notification"], "false")
        self.assertEqual(alert["disable_notification"], "true")
        self.assertEqual(digest["parse_mode"], "HTML")
        self.assertEqual(digest["caption"], self.digest["telegram"])

    def test_only_listed_connected_channels_are_used(self):
        normal = [{"id": c["id"], "name": c["displayName"], "service": c["service"], "disconnected": c["isDisconnected"]}
                  for c in CHANNELS]
        chosen = post_module.allowed_channels(normal, {"ig-1", "th-1", "x-1"})
        self.assertEqual(chosen, {"instagram": "ig-1", "threads": "th-1", "x": "x-1"})
        self.assertEqual(post_module.allowed_channels(normal, set()), {})
        self.assertEqual(post_module.allowed_channels(normal, {"li-1"}), {})
        normal[1]["disconnected"] = True
        self.assertNotIn("instagram", post_module.allowed_channels(normal, {"ig-1", "th-1", "x-1"}))


class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="morrow-social-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        edition = real_edition()
        self.state = post_module.empty_state()
        post, _ = post_module.plan(edition, self.state, at(7))
        self.frozen = post_module.freeze(self.state, post, at(7))
        for card in post["cards"]:
            path = self.folder / card
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x89PNG fake")
        self.http = FakeHttp(CHANNELS)

    def run_deliver(self, env=None, now=None, **options) -> list[str]:
        options.setdefault("image_bases", [IMAGE_BASE])
        return post_module.deliver(self.state, self.folder, ENV if env is None else env, now or at(7, 5),
                                   http=self.http, sleep=lambda seconds: None, **options)

    def statuses(self) -> dict:
        return {name: entry["status"] for name, entry in self.frozen["targets"].items()}

    def assert_no_secret(self, *texts: str) -> None:
        for text in (*texts, json.dumps(self.state)):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(API_KEY, text)
            self.assertNotIn(TOKEN.split(":")[1], text)

    def test_without_credentials_nothing_is_sent_and_every_target_is_skipped(self):
        log = self.run_deliver(env={})
        self.assertEqual(self.http.calls, [])
        self.assertEqual(set(self.statuses().values()), {"skipped"})
        self.assertEqual(len(log), 4)
        self.assertEqual(self.run_deliver(env=ENV), [], "a skipped target must stay final when secrets arrive later")
        self.assertEqual(self.http.calls, [])

    def test_everything_configured_delivers_once_to_the_listed_channels(self):
        log = self.run_deliver()
        self.assertEqual(set(self.statuses().values()), {"delivered"})
        self.assertEqual(self.http.count("sendPhoto"), 1)
        self.assertEqual(self.http.count("createPost"), 3)
        sent_to = [kwargs["json"]["variables"]["input"]["channelId"]
                   for _, kwargs in self.http.calls if "createPost" in (kwargs.get("json") or {}).get("query", "")]
        self.assertEqual(sorted(sent_to), ["ig-1", "th-1", "x-1"])
        self.assertNotIn("personal-ig", json.dumps(sent_to))
        self.assertEqual(self.frozen["targets"]["telegram"]["ref"], "telegram:7")
        self.assertEqual(self.frozen["targets"]["x"]["ref"], "buffer:post-1")
        calls_before = len(self.http.calls)
        self.assertEqual(self.run_deliver(now=at(7, 40)), [])
        self.assertEqual(len(self.http.calls), calls_before, "a delivered post must never be sent again")
        self.assert_no_secret(*log)

    def test_telegram_photo_and_caption(self):
        self.run_deliver(env={**ENV, "BUFFER_API_KEY": ""})
        url, kwargs = next(call for call in self.http.calls if "sendPhoto" in call[0])
        self.assertEqual(kwargs["data"]["chat_id"], "@morrowbrief")
        self.assertEqual(kwargs["data"]["caption"], self.frozen["telegram"])
        self.assertEqual(kwargs["files"]["photo"][0], "digest.png")
        self.assertEqual(self.statuses()["instagram"], "skipped")

    def test_a_refused_send_is_retried_then_given_up_after_three_attempts(self):
        self.http.telegram = [FakeResponse(400, {"ok": False, "description": f"Bad Request: chat not found bot{TOKEN}"})]
        env = {**ENV, "BUFFER_API_KEY": ""}
        outcomes = []
        for minutes in (5, 35, 65, 95):
            log = self.run_deliver(env=env, now=at(7, 0) + dt.timedelta(minutes=minutes))
            outcomes.append(self.statuses()["telegram"])
            self.assert_no_secret(*log)
        self.assertEqual(outcomes, ["failed", "failed", "gave_up", "gave_up"])
        self.assertEqual(self.http.count("sendPhoto"), 3)
        self.assertEqual(self.frozen["targets"]["telegram"]["attempts"], 3)
        self.assertIn("chat not found", self.frozen["targets"]["telegram"]["detail"])

    def test_a_failed_send_that_later_works_is_delivered_once(self):
        self.http.create = [FakeResponse(429, {"errors": [{"message": "slow down"}]}),
                            FakeResponse(200, {"data": {"createPost": {"post": {"id": "post-2"}}}})]
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": "x-1"})
        self.assertEqual(self.statuses()["x"], "failed")
        self.assertIn("rate limit", self.frozen["targets"]["x"]["detail"])
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": "x-1"}, now=at(7, 35))
        self.assertEqual(self.statuses()["x"], "delivered")
        self.assertEqual(self.frozen["targets"]["x"]["attempts"], 2)
        self.assertNotIn("detail", self.frozen["targets"]["x"])

    def test_a_timeout_on_send_is_unconfirmed_and_never_retried(self):
        self.http.telegram = [requests.exceptions.ReadTimeout("timed out")]
        self.http.create = [requests.exceptions.ReadTimeout("timed out")]
        self.run_deliver()
        self.assertEqual(set(self.statuses().values()), {"unconfirmed"})
        calls_before = len(self.http.calls)
        self.assertEqual(self.run_deliver(now=at(7, 35)), [])
        self.assertEqual(len(self.http.calls), calls_before, "an unconfirmed send must not be repeated")

    def test_a_server_error_on_send_is_unconfirmed(self):
        self.http.telegram = [FakeResponse(502, None)]
        self.http.create = [FakeResponse(503, None)]
        self.run_deliver()
        self.assertEqual(set(self.statuses().values()), {"unconfirmed"})

    def test_a_connection_that_never_opened_is_safe_to_retry(self):
        self.http.telegram = [requests.exceptions.ConnectionError("refused")]
        self.http.organizations = [requests.exceptions.ConnectTimeout("no route")]
        self.run_deliver()
        self.assertEqual(set(self.statuses().values()), {"failed"})

    def test_a_wrong_api_key_fails_without_leaking_it(self):
        self.http.organizations = [FakeResponse(401, {"errors": [{"message": f"bad key {API_KEY}"}]})]
        log = self.run_deliver(env={**ENV, "TELEGRAM_BOT_TOKEN": ""})
        self.assertEqual(self.statuses()["instagram"], "failed")
        self.assertEqual(self.statuses()["telegram"], "skipped")
        self.assertEqual(self.http.count("createPost"), 0)
        self.assert_no_secret(*log)

    def test_a_buffer_error_message_is_recorded(self):
        self.http.create = [FakeResponse(200, {"data": {"createPost": {
            "__typename": "MutationError", "message": "Instagram needs an image"}}})]
        self.run_deliver()
        self.assertEqual(self.statuses()["instagram"], "failed")
        self.assertIn("Instagram needs an image", self.frozen["targets"]["instagram"]["detail"])

    def test_a_post_older_than_three_hours_expires_unsent(self):
        log = self.run_deliver(now=at(10, 1))
        self.assertEqual(self.http.calls, [])
        self.assertEqual(set(self.statuses().values()), {"expired"})
        self.assertEqual(len(log), 4)

    def test_an_empty_allowlist_posts_to_no_buffer_channel(self):
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": ""})
        self.assertEqual(self.http.count("createPost"), 0)
        self.assertEqual(self.http.count("organizations"), 0)
        self.assertEqual(self.statuses()["telegram"], "delivered")
        self.assertEqual({self.statuses()[name] for name in ("instagram", "threads", "x")}, {"skipped"})

    def test_a_personal_channel_that_is_not_listed_is_never_used(self):
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": "th-1"})
        used = [kwargs["json"]["variables"]["input"]["channelId"]
                for _, kwargs in self.http.calls if "createPost" in (kwargs.get("json") or {}).get("query", "")]
        self.assertEqual(used, ["th-1"])
        self.assertEqual(self.statuses()["instagram"], "skipped")
        self.assertEqual(self.statuses()["x"], "skipped")

    def test_cards_that_are_not_public_yet_hold_the_buffer_posts_back(self):
        self.http.images = [FakeResponse(404, None, {"Content-Type": "text/plain"})]
        self.run_deliver()
        self.assertEqual(self.http.count("createPost"), 0)
        self.assertEqual(self.statuses()["x"], "failed")
        self.assertIn("not reachable", self.frozen["targets"]["x"]["detail"])
        self.assertEqual(self.statuses()["telegram"], "delivered")

    def test_the_second_image_url_is_used_when_the_first_is_down(self):
        self.http.images = [FakeResponse(404, None), FakeResponse(200, None, {"Content-Type": "image/png"})]
        self.run_deliver(image_bases=["https://first.example/", "https://second.example/"])
        payloads = [kwargs["json"]["variables"]["input"] for _, kwargs in self.http.calls
                    if "createPost" in (kwargs.get("json") or {}).get("query", "")]
        self.assertTrue(payloads)
        for payload in payloads:
            self.assertTrue(payload["assets"][0]["image"]["url"].startswith("https://second.example/cards/"))

    def test_a_short_telegram_rate_limit_is_waited_out(self):
        self.http.telegram = [FakeResponse(429, {"ok": False, "parameters": {"retry_after": 5}}),
                              FakeResponse(200, {"ok": True, "result": {"message_id": 99}})]
        self.run_deliver(env={**ENV, "BUFFER_API_KEY": ""})
        self.assertEqual(self.statuses()["telegram"], "delivered")
        self.assertEqual(self.frozen["targets"]["telegram"]["ref"], "telegram:99")

    def test_a_long_telegram_rate_limit_is_left_for_the_next_run(self):
        self.http.telegram = [FakeResponse(429, {"ok": False, "parameters": {"retry_after": 600}})]
        self.run_deliver(env={**ENV, "BUFFER_API_KEY": ""})
        self.assertEqual(self.statuses()["telegram"], "failed")
        self.assertEqual(self.http.count("sendPhoto"), 1)

    def test_a_missing_card_file_is_not_sent(self):
        (self.folder / self.frozen["cards"][0]).unlink()
        self.run_deliver(env={**ENV, "BUFFER_API_KEY": ""})
        self.assertEqual(self.statuses()["telegram"], "failed")
        self.assertEqual(self.http.count("sendPhoto"), 0)

    def test_a_run_delivers_what_it_claimed_and_clears_the_claim(self):
        self.assertEqual(post_module.claim(self.state, "run-1"), 4)
        self.assertEqual(set(self.statuses().values()), {"sending"})
        self.run_deliver(run_id="run-1")
        self.assertEqual(set(self.statuses().values()), {"delivered"})
        self.assertEqual(self.http.count("sendPhoto"), 1)
        self.assertEqual(self.http.count("createPost"), 3)
        for entry in self.frozen["targets"].values():
            self.assertNotIn("claim", entry)

    def test_a_claim_left_by_a_run_that_died_is_never_sent_again(self):
        # Run 1 claimed, sent, and died before it could save "delivered". Run 2 must not send again.
        post_module.claim(self.state, "run-1")
        self.assertEqual(post_module.claim(self.state, "run-2"), 0, "a second run must not take over a claim")
        log = self.run_deliver(run_id="run-2", now=at(7, 35))
        self.assertEqual(self.http.calls, [])
        self.assertEqual(set(self.statuses().values()), {"unconfirmed"})
        self.assertEqual(len(log), 4)
        self.assertIn("never recorded the result", self.frozen["targets"]["x"]["detail"])
        self.assertEqual(self.run_deliver(run_id="run-3", now=at(8, 5)), [])
        self.assertEqual(self.http.calls, [])

    def test_a_claim_is_not_sent_by_a_deliver_without_a_run_id(self):
        post_module.claim(self.state, "run-1")
        self.run_deliver()
        self.assertEqual(self.http.calls, [])
        self.assertEqual(set(self.statuses().values()), {"unconfirmed"})

    def test_a_failed_target_is_claimed_again_and_a_finished_one_is_left_alone(self):
        self.http.create = [FakeResponse(429, {"errors": [{"message": "slow down"}]})]
        post_module.claim(self.state, "run-1")
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": "x-1"}, run_id="run-1")
        self.assertEqual(self.statuses(), {
            "telegram": "delivered", "instagram": "skipped", "threads": "skipped", "x": "failed"})
        self.http.create = [FakeResponse(200, {"data": {"createPost": {"post": {"id": "post-2"}}}})]
        self.assertEqual(post_module.claim(self.state, "run-2"), 1)
        self.assertEqual(self.frozen["targets"]["x"]["claim"], "run-2")
        self.run_deliver(env={**ENV, "MORROW_BUFFER_CHANNELS": "x-1"}, run_id="run-2", now=at(7, 35))
        self.assertEqual(self.statuses()["x"], "delivered")
        self.assertEqual(self.http.count("sendPhoto"), 1)


class StateTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="morrow-social-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_a_corrupt_state_file_stops_the_run(self):
        path = self.folder / "state.json"
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            post_module.load_state(path)

    def test_state_round_trip_and_missing_file(self):
        path = self.folder / "state.json"
        self.assertEqual(post_module.load_state(path), post_module.empty_state())
        state = post_module.empty_state()
        post_module.day_record(state, "2026-11-14")["used"].append("abc")
        post_module.save_state(path, state)
        self.assertEqual(post_module.load_state(path), state)

    def test_old_days_and_cards_are_pruned(self):
        state = post_module.empty_state()
        for date in ("2026-11-01", "2026-11-10", "2026-11-14"):
            post_module.day_record(state, date)
            state["posts"][f"digest-{date}"] = {"date": date}
            (self.folder / "cards" / date).mkdir(parents=True)
        post_module.prune(state, self.folder, dt.date(2026, 11, 14))
        self.assertEqual(sorted(state["days"]), ["2026-11-10", "2026-11-14"])
        self.assertEqual(sorted(state["posts"]), ["digest-2026-11-10", "digest-2026-11-14"])
        self.assertEqual(sorted(item.name for item in (self.folder / "cards").iterdir()), ["2026-11-10", "2026-11-14"])

    def test_scrub_hides_secrets(self):
        text = post_module.scrub(f"failed https://api.telegram.org/bot{TOKEN}/sendPhoto with {API_KEY}", [TOKEN, API_KEY])
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(API_KEY, text)
        self.assertNotIn("AAExample", post_module.scrub(f"bot{TOKEN}", []))


class CommandTest(unittest.TestCase):
    """The commands the workflow runs, end to end on the real page, in a temporary folder."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="morrow-social-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.page = str(helpers.FIXTURES / "edition.html")

    def run_command(self, *arguments: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(post_module.main(list(arguments)), 0)
        return output.getvalue()

    def test_build_freezes_one_digest_and_a_second_run_adds_nothing(self):
        out = str(self.folder / "data")
        first = self.run_command("build", "--page", self.page, "--out", out, "--now", "2026-11-14T08:00:00+07:00")
        self.assertIn("frozen digest-2026-11-14", first)
        state = json.loads((self.folder / "data" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(list(state["posts"]), ["digest-2026-11-14"])
        for card in state["posts"]["digest-2026-11-14"]["cards"]:
            self.assertTrue((self.folder / "data" / card).is_file(), card)
        public = json.loads((self.folder / "data" / "feed.json").read_text(encoding="utf-8"))
        self.assertEqual(public["posts"][0]["id"], "digest-2026-11-14")
        self.assertNotIn("targets", public["posts"][0])
        self.assertIn("/today", public["bot"])
        second = self.run_command("build", "--page", self.page, "--out", out, "--now", "2026-11-14T10:00:00+07:00")
        self.assertIn("no new post", second)
        again = json.loads((self.folder / "data" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(again, state)

    def test_build_with_a_run_id_claims_and_only_that_run_delivers(self):
        out = str(self.folder / "data")
        first = self.run_command("build", "--page", self.page, "--out", out, "--run", "101-1",
                                 "--now", "2026-11-14T08:00:00+07:00")
        self.assertIn("4 targets claimed by run 101-1", first)
        state = json.loads((self.folder / "data" / "state.json").read_text(encoding="utf-8"))
        targets = state["posts"]["digest-2026-11-14"]["targets"]
        self.assertEqual({entry["status"] for entry in targets.values()}, {"sending"})
        self.assertEqual({entry["claim"] for entry in targets.values()}, {"101-1"})
        public = json.loads((self.folder / "data" / "feed.json").read_text(encoding="utf-8"))
        self.assertNotIn("101-1", json.dumps(public))
        # The next run starts from the saved state, as it would after run 101 died.
        text = self.run_command("deliver", "--out", out, "--run", "102-1", "--now", "2026-11-14T08:30:00+07:00")
        self.assertEqual(text.count("unconfirmed, will not retry"), 4)

    def test_build_on_a_stale_page_posts_nothing(self):
        out = str(self.folder / "data")
        text = self.run_command("build", "--page", self.page, "--out", out, "--now", "2026-11-15T08:00:00+07:00")
        self.assertIn("stale page", text)
        state = json.loads((self.folder / "data" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["posts"], {})

    def test_preview_writes_posts_payloads_and_cards(self):
        out = self.folder / "preview"
        self.run_command("preview", "--page", self.page, "--out", str(out))
        self.assertIn("## digest-2026-11-14", (out / "preview.md").read_text(encoding="utf-8"))
        payloads = json.loads((out / "payloads.json").read_text(encoding="utf-8"))
        self.assertEqual(set(payloads["digest-2026-11-14"]), {"telegram", "instagram", "threads", "x"})
        self.assertEqual(len(list((out / "cards" / "2026-11-14").glob("*.png"))), 7)


if __name__ == "__main__":
    unittest.main()
