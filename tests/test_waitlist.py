import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import waitlist_tally as wt  # noqa: E402

FORM_BODY = """### Which markets do you hold?

{market}

### Roughly how many stocks or funds do you hold?

6-15

### Where would you read it?

_No response_

### Would you pay a small monthly fee for it later?

{pay}

### What should the briefing tell you that you don't get today?

_No response_
"""


def issue(number, pay="Yes", market="IDX only", author="reader", labels=("waitlist",),
          title="Portfolio briefing waitlist", body=None):
    return {"number": number, "title": title, "user": {"login": author}, "state": "open",
            "labels": [{"name": name} for name in labels],
            "body": FORM_BODY.format(pay=pay, market=market) if body is None else body}


class WaitlistTests(unittest.TestCase):
    def test_form_answers(self):
        for answer in ("Yes", "Maybe", "No"):
            self.assertEqual(wt.parse_pay(FORM_BODY.format(pay=answer, market="US only")), answer.lower())
        self.assertIsNone(wt.parse_pay(FORM_BODY.format(pay="_No response_", market="US only")))
        self.assertEqual(wt.parse_field(FORM_BODY.format(pay="Yes", market="Both IDX and US"), "which markets"),
                         "Both IDX and US")
        self.assertIsNone(wt.parse_field(FORM_BODY.format(pay="Yes", market="x"), "where would you read"))

    def test_tally_counts_signups_and_skips_owner_tracker_and_other_issues(self):
        issues = [
            issue(1, "Yes"),
            issue(2, "Maybe", market="US only"),
            issue(3, "Yes", author="juw12"),
            issue(4, labels=("waitlist-tally",), title="Portfolio briefing waitlist: live tally", body="tally"),
            issue(5, labels=("bug",), title="Page is blank", body="blank"),
            issue(6, "No", labels=()),
            issue(7, "_No response_"),
        ]
        result = wt.tally(issues, owner="juw12")
        self.assertEqual(result["counts"], {"signups": 4, "unanswered": 1, "yes": 1, "maybe": 1, "no": 1})
        self.assertEqual(result["markets"], {"IDX only": 3, "US only": 1})
        self.assertEqual([entry["number"] for entry in result["entries"]], [1, 2, 3, 6, 7])
        self.assertFalse(next(entry for entry in result["entries"] if entry["number"] == 3)["counted"])

    def test_decision_follows_the_success_line(self):
        self.assertIn("Running", wt.decision(20, date(2026, 11, 15)))
        self.assertIn("met", wt.decision(50, date(2026, 11, 15)))
        self.assertIn("Rework", wt.decision(15, date(2026, 11, 23)))
        self.assertIn("Stop", wt.decision(14, date(2026, 11, 23)))

    def test_render_mentions_counts_and_deadline(self):
        text = wt.render(wt.tally([issue(9)], owner="juw12"), date(2026, 11, 10))
        self.assertIn("| **Sign-ups** | **1** |", text)
        self.assertIn("2026-11-22", text)
        self.assertIn("#9 (yes)", text)
        self.assertIn("portfolio-briefing.yml", text)


if __name__ == "__main__":
    unittest.main()
