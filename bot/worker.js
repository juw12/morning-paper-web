// Morrow Brief: the Telegram bot as a Cloudflare Worker (free plan).
//
// Telegram calls this Worker for every message (a webhook). The Worker reads the day's pre-rendered
// replies from feed.json on the repo's data branch and answers in the HTTP response itself, so it
// holds no bot token, no database and no list of users. Its only secret is WEBHOOK_SECRET, which
// Telegram sends back in a header so nobody else can call it.
//
// scripts/social_bot.py gives the same answers; tests/social/fixtures/bot_cases.json keeps the two in step.

export const FEED_URL = "https://raw.githubusercontent.com/juw12/morrow/social-data/feed.json";
const SITE_URL = "https://juw12.github.io/morrow/";
const NOT_READY = `Today's edition is not ready yet. Read the latest at <a href="${SITE_URL}">juw12.github.io/morrow</a>.`;
const SECTION_COMMANDS = ["/ai", "/bigtech", "/robotics", "/space", "/tech", "/markets", "/tape"];
const MESSAGE_LIMIT = 4096;

const escapeText = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttribute = (text) => escapeText(text).replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
const link = (url, label) => `<a href="${escapeAttribute(url)}">${escapeText(label)}</a>`;
const codePoints = (text) => Array.from(text).length;

const NAMED_ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'" };

function visibleLength(html) {
  const text = html.replace(/<[^>]+>/g, "").replace(/&(amp|lt|gt|quot|#x27);/g, (entity) => NAMED_ENTITIES[entity]);
  return codePoints(text);
}

// Cut at a word boundary and end with an ellipsis; never longer than the limit.
export function truncate(text, limit) {
  if (codePoints(text) <= limit) return text;
  const words = text.split(" ");
  while (words.length > 1) {
    words.pop();
    const candidate = words.join(" ").replace(/[ ,;:\-—–]+$/, "") + "…";
    if (codePoints(candidate) <= limit) return candidate;
  }
  // A single word that does not fit: cut inside it.
  const letters = Array.from(words[0]).slice(0, Math.max(limit - 1, 0));
  return letters.length ? letters.join("") + "…" : "";
}

function ranked(stories) {
  return [...stories].sort(
    (a, b) => Number(!a.is_lead) - Number(!b.is_lead) || b.coverage - a.coverage || a.order - b.order,
  );
}

function storyLine(story) {
  const extra = story.coverage > 1 ? ` +${story.coverage - 1}` : "";
  return `• ${link(story.url, truncate(story.title, 120))} (${escapeText(story.source)}${extra})`;
}

function listReply(heading, stories) {
  const build = (shown) => [`<b>${escapeText(heading)}</b>`, "", ...shown.map(storyLine)].join("\n");
  let shown = stories;
  let text = build(shown);
  while (visibleLength(text) > MESSAGE_LIMIT && shown.length) {
    shown = shown.slice(0, -1);
    text = build(shown);
  }
  return text;
}

export function searchReply(stories, query) {
  const words = (query.toLowerCase().match(/[a-z0-9]+/g) || []).filter((word) => word.length > 1);
  if (!words.length) return "Send /find and a word, for example: /find nvidia";
  const hits = ranked(stories).filter((story) => {
    const haystack = [story.title, story.dek, story.tag, story.source].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
  if (!hits.length) return `Nothing on “${escapeText(query.trim())}” in today's edition. Try /today.`;
  const noun = hits.length === 1 ? "story" : "stories";
  return listReply(`${hits.length} ${noun} on “${query.trim()}”`, hits.slice(0, 6));
}

// The bot's whole behaviour: message text in, HTML reply out. null means stay silent.
export function replyFor(feed, text, isPrivate = true) {
  const message = (text || "").trim();
  const replies = (feed && feed.bot) || {};
  if (!message.startsWith("/")) {
    // In a private chat any message gets the menu. In a group the bot only answers commands.
    return isPrivate && message ? replies["/help"] || NOT_READY : null;
  }
  if (!Object.keys(replies).length) return NOT_READY;
  const spaceAt = message.indexOf(" ");
  const head = spaceAt === -1 ? message : message.slice(0, spaceAt);
  const argument = spaceAt === -1 ? "" : message.slice(spaceAt + 1).trim();
  const command = head.split("@")[0].toLowerCase();
  if (command === "/find") return searchReply(feed.stories || [], argument);
  if (replies[command]) return replies[command];
  if (SECTION_COMMANDS.includes(command)) return "Nothing under that heading in today's edition. Try /today.";
  return replies["/help"];
}

async function loadFeed() {
  // Cloudflare keeps the feed for two minutes, so a busy chat does not hammer GitHub.
  const response = await fetch(FEED_URL, { cf: { cacheTtl: 120, cacheEverything: true } });
  if (!response.ok) return {};
  return response.json();
}

const empty = (status = 200) => new Response(null, { status });

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("Morrow Brief bot", { status: 200 });
    // With no secret configured the Worker answers nobody, so a half-finished setup is never open.
    if (!env || !env.WEBHOOK_SECRET) return empty(503);
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return empty(403);
    let update;
    try {
      update = await request.json();
    } catch {
      return empty(400);
    }
    const message = update && update.message;
    if (!message || typeof message.text !== "string" || !message.chat) return empty();
    let feed = {};
    try {
      feed = await loadFeed();
    } catch {
      feed = {};
    }
    const reply = replyFor(feed, message.text, message.chat.type === "private");
    if (reply === null) return empty();
    // Answering inside the webhook response: Telegram runs this as a sendMessage call.
    return Response.json({
      method: "sendMessage",
      chat_id: message.chat.id,
      text: reply,
      parse_mode: "HTML",
      link_preview_options: { is_disabled: true },
    });
  },
};
