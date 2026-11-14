"""Morrow Brief: the Telegram bot.

    python scripts/social_bot.py poll --feed data/feed.json --listen 240
    python scripts/social_bot.py set-webhook --url https://<worker>.workers.dev
    python scripts/social_bot.py delete-webhook

The bot keeps no state and no list of users. Every fixed reply is pre-rendered in feed.json by
`social_post.py build`; only /find is computed here. `bot/worker.js` gives the same answers from a
Cloudflare Worker (instant, through a webhook); `poll` is the fallback that needs no extra account.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

import social_feed as feed

TELEGRAM_API = "https://api.telegram.org"
LONG_POLL_SECONDS = 25
MAX_CLOSING_ROUNDS = 5
NOT_READY = f'Today\'s edition is not ready yet. Read the latest at <a href="{feed.SITE_URL}">{feed.SITE_SHORT}</a>.'


def command_of(text: str) -> tuple[str, str]:
    """Split '/Find@MorrowBriefBot nvidia chips' into ('/find', 'nvidia chips')."""
    head, _, rest = text.strip().partition(" ")
    return head.split("@", 1)[0].lower(), rest.strip()


def reply_for(feed_data: dict, text: str, private: bool = True) -> str | None:
    """The bot's whole behaviour: message text in, HTML reply out. None means stay silent."""
    text = (text or "").strip()
    if not text.startswith("/"):
        # In a private chat any message gets the menu. In a group the bot only answers commands.
        return (feed_data.get("bot") or {}).get("/help", NOT_READY) if private and text else None
    replies = feed_data.get("bot") or {}
    if not replies:
        return NOT_READY
    command, argument = command_of(text)
    if command == "/find":
        return feed.search_reply(feed_data.get("stories") or [], argument)
    if command in replies:
        return replies[command]
    if command in feed.SECTION_COMMANDS.values() or command == "/tape":
        return "Nothing under that heading in today's edition. Try /today."
    return replies["/help"]


def scrub(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***", text)[:300]


def call(http, token: str, method: str, payload: dict, timeout: int = 40) -> tuple[int, dict]:
    response = http.post(f"{TELEGRAM_API}/bot{token}/{method}", json=payload, timeout=timeout)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body


def answer(http, token: str, feed_data: dict, update: dict) -> str | None:
    """Reply to one update. Returns a log line, or None when there was nothing to answer."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    reply = reply_for(feed_data, message.get("text") or "", chat.get("type") == "private")
    if reply is None or "id" not in chat:
        return None
    status, body = call(http, token, "sendMessage", {
        "chat_id": chat["id"],
        "text": reply,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    })
    command = command_of(message.get("text") or "")[0] or "text"
    if status == 200 and body.get("ok"):
        return f"answered {command}"
    return f"could not answer {command}: {scrub(str(body.get('description') or status), token)}"


def poll(http, token: str, feed_data: dict, listen_seconds: int, clock=time.monotonic) -> list[str]:
    """Answer pending messages for about listen_seconds, then acknowledge them so they never repeat."""
    log: list[str] = []
    offset: int | None = None
    closing_rounds = 0
    deadline = clock() + listen_seconds
    while True:
        remaining = deadline - clock()
        wait = max(0, min(LONG_POLL_SECONDS, int(remaining)))
        payload = {"timeout": wait, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            status, body = call(http, token, "getUpdates", payload, timeout=wait + 20)
        except requests.exceptions.RequestException as error:
            log.append(f"Telegram unreachable ({type(error).__name__}), stopping")
            return log
        if status == 409:
            log.append("a webhook is set, so the Worker answers and polling is not needed")
            return log
        if status != 200 or not body.get("ok"):
            log.append("getUpdates failed: " + scrub(str(body.get("description") or status), token))
            return log
        updates = body.get("result") or []
        for update in updates:
            # Move the offset first: an update that cannot be answered is skipped, never retried forever.
            offset = update["update_id"] + 1
            try:
                line = answer(http, token, feed_data, update)
            except requests.exceptions.RequestException as error:
                line = f"could not answer: {type(error).__name__}"
            if line:
                log.append(line)
        if remaining <= 0:
            # Telegram forgets an update only when a later call carries a higher offset. So the run ends
            # on a call that returned nothing new; a few extra rounds are allowed to drain late arrivals.
            if not updates:
                return log
            if closing_rounds >= MAX_CLOSING_ROUNDS:
                # Still busy: acknowledge what was answered and leave the rest for the next run.
                # Whatever this call returns has not been answered, so it is not acknowledged.
                try:
                    call(http, token, "getUpdates", {"timeout": 0, "limit": 1, "offset": offset,
                                                     "allowed_updates": ["message"]})
                except requests.exceptions.RequestException:
                    pass
                return log
            closing_rounds += 1


def command_poll(args) -> int:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set, nothing to do")
        return 0
    path = Path(args.feed)
    feed_data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    lines = poll(requests, token, feed_data, args.listen)
    answered = sum(line.startswith("answered") for line in lines)
    for line in [line for line in lines if not line.startswith("answered")]:
        print(line)
    print(f"{answered} messages answered")
    return 0


def command_set_webhook(args) -> int:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    secret = (os.environ.get("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not token or not secret:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET first.")
        return 1
    if not args.url.startswith("https://"):
        print("The webhook URL must start with https://")
        return 1
    status, body = call(requests, token, "setWebhook", {
        "url": args.url,
        "secret_token": secret,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    })
    print("webhook set" if status == 200 and body.get("ok")
          else "setWebhook failed: " + scrub(str(body.get("description") or status), token))
    return 0 if body.get("ok") else 1


def command_delete_webhook(_args) -> int:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first.")
        return 1
    status, body = call(requests, token, "deleteWebhook", {"drop_pending_updates": False})
    print("webhook removed" if status == 200 and body.get("ok")
          else "deleteWebhook failed: " + scrub(str(body.get("description") or status), token))
    return 0 if body.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    polling = commands.add_parser("poll")
    polling.add_argument("--feed", default="data/feed.json")
    polling.add_argument("--listen", type=int, default=240, help="seconds to keep answering")
    polling.set_defaults(run=command_poll)
    hook = commands.add_parser("set-webhook")
    hook.add_argument("--url", required=True)
    hook.set_defaults(run=command_set_webhook)
    unhook = commands.add_parser("delete-webhook")
    unhook.set_defaults(run=command_delete_webhook)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
