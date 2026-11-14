// Run with: node --test bot/
// The Worker must give exactly the replies the Python bot gives. Both are checked against
// tests/social/fixtures/bot_cases.json, which tests/social/make_fixtures.py writes from a real edition.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, test } from "node:test";

import worker, { FEED_URL, replyFor, searchReply, truncate } from "./worker.js";

const fixture = JSON.parse(
  readFileSync(new URL("../tests/social/fixtures/bot_cases.json", import.meta.url), "utf8"),
);
const SECRET = "webhook-secret-for-tests";
const realFetch = globalThis.fetch;
let feedRequests = [];

function serveFeed(respond = () => new Response(JSON.stringify(fixture.feed), { status: 200 })) {
  globalThis.fetch = async (url, options) => {
    feedRequests.push({ url: String(url), options });
    return respond();
  };
}

function webhook(update, { secret = SECRET, body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (secret !== null) headers["X-Telegram-Bot-Api-Secret-Token"] = secret;
  return new Request("https://bot.example/", {
    method: "POST",
    headers,
    body: body === undefined ? JSON.stringify(update) : body,
  });
}

const textMessage = (text, type = "private", id = 77) => ({
  update_id: 1,
  message: { message_id: 5, text, chat: { id, type } },
});

beforeEach(() => {
  feedRequests = [];
  serveFeed();
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

test("every recorded message gets the same reply as the Python bot", () => {
  assert.ok(fixture.cases.length >= 20);
  for (const item of fixture.cases) {
    assert.equal(replyFor(fixture.feed, item.text, item.private), item.reply, `message: ${JSON.stringify(item.text)}`);
  }
});

test("before the first edition the bot says so", () => {
  for (const empty of [{}, { bot: {} }, null]) {
    assert.match(replyFor(empty, "/today"), /not ready/);
    assert.match(replyFor(empty, "hi"), /not ready/);
  }
  assert.equal(replyFor({}, "hi", false), null);
});

test("search escapes the query and needs every word", () => {
  const miss = searchReply(fixture.feed.stories, "zzzzqqq <b>");
  assert.ok(miss.includes("&lt;b&gt;"));
  assert.ok(!miss.includes("<b>"));
  const hit = searchReply(fixture.feed.stories, "nvidia");
  assert.ok(hit.includes("<a href="));
  assert.match(searchReply(fixture.feed.stories, "a"), /^Send \/find/);
});

test("truncate cuts at a word and never exceeds the limit", () => {
  const long = "One two three four five six seven eight nine ten";
  for (let limit = 1; limit <= long.length; limit += 1) {
    const cut = truncate(long, limit);
    assert.ok(Array.from(cut).length <= limit, `limit ${limit}: ${cut}`);
  }
  assert.equal(truncate(long, 15), "One two three…");
  assert.equal(truncate(long, long.length), long);
});

test("a browser visit gets a plain page and reads nothing", async () => {
  const response = await worker.fetch(new Request("https://bot.example/"), { WEBHOOK_SECRET: SECRET });
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Morrow Brief/);
  assert.equal(feedRequests.length, 0);
});

test("with no secret configured the Worker answers nobody", async () => {
  for (const env of [{}, undefined, { WEBHOOK_SECRET: "" }]) {
    const response = await worker.fetch(webhook(textMessage("/today")), env);
    assert.equal(response.status, 503);
  }
  assert.equal(feedRequests.length, 0);
});

test("a call without Telegram's secret header is refused", async () => {
  for (const secret of ["wrong", "", null]) {
    const response = await worker.fetch(webhook(textMessage("/today"), { secret }), { WEBHOOK_SECRET: SECRET });
    assert.equal(response.status, 403);
    assert.equal(await response.text(), "");
  }
  assert.equal(feedRequests.length, 0);
});

test("a body that is not JSON is a 400", async () => {
  const response = await worker.fetch(webhook(null, { body: "not json" }), { WEBHOOK_SECRET: SECRET });
  assert.equal(response.status, 400);
});

test("updates that are not text messages are accepted and ignored", async () => {
  const ignored = [
    { update_id: 1 },
    { update_id: 2, edited_message: { text: "/today", chat: { id: 1, type: "private" } } },
    { update_id: 3, message: { photo: [], chat: { id: 1, type: "private" } } },
    { update_id: 4, message: { text: "/today" } },
  ];
  for (const update of ignored) {
    const response = await worker.fetch(webhook(update), { WEBHOOK_SECRET: SECRET });
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "");
  }
  assert.equal(feedRequests.length, 0);
});

test("a command is answered inside the webhook response", async () => {
  const response = await worker.fetch(webhook(textMessage("/today", "private", 4242)), { WEBHOOK_SECRET: SECRET });
  assert.equal(response.status, 200);
  assert.match(response.headers.get("Content-Type"), /application\/json/);
  const payload = await response.json();
  assert.deepEqual(payload, {
    method: "sendMessage",
    chat_id: 4242,
    text: fixture.feed.bot["/today"],
    parse_mode: "HTML",
    link_preview_options: { is_disabled: true },
  });
  assert.equal(feedRequests.length, 1);
  assert.equal(feedRequests[0].url, FEED_URL);
});

test("a group message that is not a command gets no reply", async () => {
  const response = await worker.fetch(webhook(textMessage("good morning", "supergroup")), { WEBHOOK_SECRET: SECRET });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});

test("when the feed cannot be read the bot says the edition is not ready", async () => {
  const failures = [
    () => new Response("missing", { status: 404 }),
    () => new Response("<html>not json</html>", { status: 200 }),
    () => {
      throw new Error("network down");
    },
  ];
  for (const respond of failures) {
    serveFeed(respond);
    const response = await worker.fetch(webhook(textMessage("/today")), { WEBHOOK_SECRET: SECRET });
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.equal(payload.method, "sendMessage");
    assert.match(payload.text, /not ready/);
  }
});

test("the Worker holds no bot token and calls nothing but the feed", () => {
  const source = readFileSync(new URL("./worker.js", import.meta.url), "utf8");
  assert.ok(!source.includes("api.telegram.org"));
  assert.ok(!/BOT_TOKEN/.test(source));
  assert.equal(FEED_URL, "https://raw.githubusercontent.com/juw12/morrow/social-data/feed.json");
});
