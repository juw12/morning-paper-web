"""Morning Paper portfolio-briefing waitlist tally (standard library only).

Counts waitlist sign-ups against the success line and keeps a public
tracking issue up to date. Runs in GitHub Actions and locally.

    python scripts/waitlist_tally.py                 # print the tally
    python scripts/waitlist_tally.py --update        # also rewrite the tracking issue
    python scripts/waitlist_tally.py --welcome 12    # thank the author of issue 12 (once)

Token: GITHUB_TOKEN, or `gh auth token` when run locally.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone

REPO = os.environ.get("GITHUB_REPOSITORY", "juw12/morrow")
OWNER = REPO.split("/")[0]
WAITLIST_LABEL = "waitlist"
TRACKER_LABEL = "waitlist-tally"
TITLE_PREFIX = "portfolio briefing waitlist"
GOAL = 50          # sign-ups that mean "build it"
STOP_BELOW = 15    # fewer than this by the deadline means "stop"
START = date(2026, 11, 8)
DEADLINE = date(2026, 11, 22)  # 14 days
JOIN_URL = f"https://github.com/{REPO}/issues/new?template=portfolio-briefing.yml"
WELCOME_MARKER = "<!-- morning-paper-waitlist-welcome -->"
WELCOME_TEXT = WELCOME_MARKER + """
Thanks for joining the Morning Paper portfolio-briefing waitlist. You'll hear back here when the \
first briefings go out.

Meanwhile today's free edition is at https://juw12.github.io/morrow/ \
(markets, IDX catalysts and the news before the IDX opens). Not investment advice."""
PAY_ANSWERS = ("yes", "maybe", "no")


def parse_field(body, heading_pattern):
    """The answer under a '### <question>' heading of an issue form, or None if skipped."""
    section = re.search(rf"###[^\n]*{heading_pattern}[^\n]*\n+(.*?)(?=\n###|\Z)", body or "", re.I | re.S)
    if not section:
        return None
    answer = section.group(1).strip()
    return None if not answer or answer == "_No response_" else answer


def parse_pay(body):
    answer = (parse_field(body, r"pay a small monthly fee") or "").lower()
    return answer if answer in PAY_ANSWERS else None


def is_waitlist_issue(issue):
    labels = {label["name"] if isinstance(label, dict) else label for label in issue.get("labels", [])}
    if TRACKER_LABEL in labels or issue.get("pull_request"):
        return False
    return WAITLIST_LABEL in labels or (issue.get("title") or "").lower().startswith(TITLE_PREFIX)


def tally(issues, owner=OWNER):
    """Count sign-ups. The repo owner's own test issues are listed but not counted."""
    counts = {"signups": 0, "unanswered": 0, **{answer: 0 for answer in PAY_ANSWERS}}
    markets = {}
    entries = []
    for issue in issues:
        if not is_waitlist_issue(issue):
            continue
        author = (issue.get("user") or {}).get("login", "")
        counted = author.lower() != owner.lower()
        pay = parse_pay(issue.get("body"))
        market = parse_field(issue.get("body"), r"which markets") or "unanswered"
        if counted:
            counts["signups"] += 1
            counts[pay or "unanswered"] += 1
            markets[market] = markets.get(market, 0) + 1
        entries.append({"number": issue["number"], "pay": pay or "unanswered", "market": market,
                        "counted": counted, "state": issue.get("state", "open")})
    return {"counts": counts, "markets": markets,
            "entries": sorted(entries, key=lambda entry: entry["number"])}


def decision(signups, today):
    if signups >= GOAL:
        return f"Success line met ({signups} of {GOAL} sign-ups). Next: get a licensed market-data quote and build it."
    if today <= DEADLINE:
        days_left = (DEADLINE - today).days
        return f"Running: {signups} of {GOAL} sign-ups, {days_left} day(s) left (ends {DEADLINE.isoformat()})."
    if signups >= STOP_BELOW:
        return f"Missed ({signups} sign-ups). Rework the pitch and run 14 more days."
    return f"Missed ({signups} sign-ups, under {STOP_BELOW}). Stop; keep the Morning Paper free and personal."


def render(result, today, now=None):
    counts = result["counts"]
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    lines = [
        "Live tally of the Morning Paper portfolio-briefing waitlist, updated automatically by "
        f"`.github/workflows/waitlist.yml`. Join: {JOIN_URL}",
        "",
        f"**{decision(counts['signups'], today)}**",
        "",
        "| would pay later | count |",
        "| --- | ---: |",
        f"| Yes | {counts['yes']} |",
        f"| Maybe | {counts['maybe']} |",
        f"| No | {counts['no']} |",
        f"| Unanswered | {counts['unanswered']} |",
        f"| **Sign-ups** | **{counts['signups']}** |",
        "",
    ]
    if result["markets"]:
        lines.append("Markets: " + ", ".join(f"{name} {count}" for name, count in sorted(result["markets"].items())))
        lines.append("")
    lines += [
        f"Success line: {GOAL} sign-ups between {START.isoformat()} and {DEADLINE.isoformat()}. "
        f"{STOP_BELOW}-{GOAL - 1} means rework the pitch; under {STOP_BELOW} means stop.",
        "",
    ]
    if result["entries"]:
        lines.append("Sign-ups: " + ", ".join(
            f"#{entry['number']} ({entry['pay']}{'' if entry['counted'] else ', test - not counted'})"
            for entry in result["entries"]))
        lines.append("")
    lines.append(f"_Updated {now.isoformat().replace('+00:00', 'Z')}._")
    return "\n".join(lines)


# ---------- GitHub API ----------
def token():
    value = os.environ.get("GITHUB_TOKEN")
    if value:
        return value
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def api(method, path, payload=None):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "morning-paper-waitlist"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def all_issues():
    issues, page = [], 1
    while True:
        batch = api("GET", f"/repos/{REPO}/issues?state=all&per_page=100&page={page}")
        issues += batch
        if len(batch) < 100:
            return issues
        page += 1


def welcome(number):
    comments = api("GET", f"/repos/{REPO}/issues/{number}/comments?per_page=100")
    if any(WELCOME_MARKER in (comment.get("body") or "") for comment in comments):
        return False
    api("POST", f"/repos/{REPO}/issues/{number}/comments", {"body": WELCOME_TEXT})
    return True


def update_tracker(body):
    trackers = api("GET", f"/repos/{REPO}/issues?labels={TRACKER_LABEL}&state=open")
    if trackers:
        api("PATCH", f"/repos/{REPO}/issues/{trackers[0]['number']}", {"body": body})
        return trackers[0]["number"]
    created = api("POST", f"/repos/{REPO}/issues",
                  {"title": "Portfolio briefing waitlist: live tally", "body": body, "labels": [TRACKER_LABEL]})
    return created["number"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="rewrite the tracking issue")
    parser.add_argument("--welcome", type=int, help="thank the author of this issue number (once)")
    args = parser.parse_args()
    if args.welcome:
        issue = api("GET", f"/repos/{REPO}/issues/{args.welcome}")
        if is_waitlist_issue(issue):
            print("welcomed" if welcome(args.welcome) else "already welcomed", args.welcome)
    result = tally(all_issues())
    body = render(result, datetime.now(timezone.utc).date())
    print(body)
    if args.update:
        print("tracker issue:", update_tracker(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
