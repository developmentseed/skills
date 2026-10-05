#!/usr/bin/env python3
"""Compact saved Gmail search_threads results into one line per thread.

Usage: compact_threads.py [--since EPOCH] page1.json [page2.json ...]

The account is read from the threads' viewUrl (authuser=...). ME means the
last message carries Gmail's SENT label, so send-as aliases count. --since
keeps only GitHub reasons from messages at or after that time (the CC reason
repeats on every later email in a thread).
"""

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path

REASON = re.compile(r"([a-z_]+)@noreply\.github\.com")
REPO = re.compile(r"^(?:Re: )?\[([^\]]+)\]")
ACCOUNT = re.compile(r"authuser=([^&#]+)")
GITHUB = "notifications@github.com"


def at(m):
    return datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone()


def clean(s, n):
    return " ".join(html.unescape(s or "").split())[:n]


def line(t, since):
    msgs = [m for m in t.get("messages") or [] if m.get("date")]
    if not msgs:
        return None
    first, last = msgs[0], msgs[-1]
    sender = (last.get("sender") or "").lower()
    recent = [m for m in msgs if at(m).timestamp() >= since]
    reasons = sorted({r for m in recent for r in REASON.findall(" ".join(m.get("ccRecipients") or []))})
    subject = clean(first.get("subject") or last.get("subject"), 100)
    repo = REPO.match(subject) if GITHUB in sender else None
    labels = {x for m in msgs for x in m.get("labelIds") or []}
    when = at(last)
    flags = [f for f, on in (("ME", "SENT" in (last.get("labelIds") or [])), ("UNREAD", "UNREAD" in labels)) if on]
    return when, "\t".join([
        when.strftime("%a %d %H:%M"),
        f"{t.get('messageCount', len(msgs))}msg",
        ",".join(flags) or "-",
        sender,
        ",".join(reasons) or "-",
        repo.group(1) if repo else "-",
        subject,
        clean(last.get("snippet"), 160),
        t.get("viewUrl", ""),
        ",".join(m["id"] for m in recent if "id" in m) or "-",
    ])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=0)
    p.add_argument("files", nargs="+")
    a = p.parse_args(argv)
    threads = {t.get("id"): t for f in a.files for t in json.loads(Path(f).read_text()).get("threads") or []}.values()
    account = next((m.group(1) for t in threads if (m := ACCOUNT.search(t.get("viewUrl", "")))), "unknown")
    rows = [r for t in threads if (r := line(t, a.since))]
    print(f"# account: {account}")
    print("date\tmsgs\tflags\tlast_sender\tgithub_reasons\trepo\tsubject\tsnippet\turl\tin_window_ids")
    for _, r in sorted(rows, key=lambda r: r[0], reverse=True):
        print(r)


if __name__ == "__main__":
    main()
