"""Run: python3 -m unittest discover -s skills/inbox-actions/scripts"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import compact_threads

URL = "https://mail.google.com/mail/?authuser=you@example.org#all/"
SINCE = 1790812800  # 2026-10-01T00:00:00Z


def msg(i, day, reason=None, labels=(), sender="notifications@github.com"):
    return {
        "id": f"m{i}",
        "date": f"2026-{day}T09:00:00Z",
        "sender": sender,
        "subject": "Re: [example-org/example-repo] Fix it (PR #1)",
        "snippet": f"snippet {i}",
        "ccRecipients": [f"{reason}@noreply.github.com"] if reason else [],
        "labelIds": list(labels),
    }


class CompactThreadsTest(unittest.TestCase):
    def run_on(self, *threads):
        with tempfile.TemporaryDirectory() as d:
            page = Path(d, "p.json")
            page.write_text(json.dumps({"threads": list(threads)}))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                compact_threads.main(["--since", str(SINCE), str(page), str(page)])
        account, header, *rows = out.getvalue().splitlines()
        return account, [dict(zip(header.split("\t"), r.split("\t"))) for r in rows]

    def test_dedup_and_in_window_reasons_only(self):
        t = {"id": "t1", "viewUrl": URL + "t1",
             "messages": [msg(1, "09-30", "author"), msg(2, "10-01", "mention", ["UNREAD"])]}
        account, [row] = self.run_on(t)
        self.assertEqual(account, "# account: you@example.org")
        self.assertEqual(
            (row["flags"], row["github_reasons"], row["in_window_ids"], row["repo"]),
            ("UNREAD", "mention", "m2", "example-org/example-repo"),
        )

    def test_me_from_sent_label(self):
        t = {"id": "t2", "viewUrl": URL + "t2",
             "messages": [msg(1, "10-01", labels=["SENT"], sender="alias@example.net")]}
        self.assertEqual(self.run_on(t)[1][0]["flags"], "ME")

    def test_sent_before_window_has_no_in_window_ids(self):
        t = {"id": "t3", "viewUrl": URL + "t3",
             "messages": [msg(1, "09-28", labels=["SENT"], sender="you@example.org")]}
        row = self.run_on(t)[1][0]
        self.assertEqual((row["flags"], row["in_window_ids"]), ("ME", "-"))


if __name__ == "__main__":
    unittest.main()
