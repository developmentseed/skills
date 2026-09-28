---
name: session-handoffs
description: End-of-day wrap-up for Claude Code users who run several sessions at once. Reads every session's transcript to see which ones left a current handoff note, lists the notes under "For Tomorrow" in your daily note, and on request asks one session to refresh its note or writes one from its transcript. Never waits on another session; safe to re-run. Use for /session-handoffs, "wrap up my sessions", "handoff notes for all sessions", or "end of day handoffs".
---

# Session handoffs

Collects the handoff notes your Claude Code sessions wrote today into one list, so tomorrow starts from a note instead of from memory. It only reads, never waits on another session, and gives the same answer when run again, so closing it early loses nothing.

## When to use this

At the end of a day with several Claude Code sessions, or the next morning. Run it in a fresh session.

## Requirements

- **Claude Code.** It reads Claude Code's local session registry and transcripts; `--ask` uses the `SendMessage` tool.
- `python3` (standard library only) for the check script.
- Optional: a daily note. Add one line to your `~/.claude/CLAUDE.md` naming the file and the heading, for example:
  `session-handoffs daily note: ~/notes/daily/{date}.md, heading "## For Tomorrow"`
  Without it, the list is printed instead.

## Arguments

- `--date YYYY-MM-DD`: the day to wrap up. Defaults to 5 hours ago, so a run shortly after midnight still covers the evening; the next morning, pass yesterday.
- `--dry-run`: show the report, write nothing.
- `--ask NAME ...`: ask these running sessions to refresh their note (step 4).
- `--from-transcript NAME|SID8 ...`: write a snapshot note for these sessions from their transcripts (step 5).

## How it works

### 1. Check

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/handoff_status.py" [--date YYYY-MM-DD]
```

It reads the registry and transcripts (read-only), leaves out this session, and prints one TSV row per note worth starting from (one row per session without one):

| verdict | meaning |
|---|---|
| `fresh` | running, has a note, little work since |
| `stale` | running, did more than 30 tool calls or subagent file edits after its note |
| `none` | running, 30+ tool calls, no note |
| `closed` | no longer running, left a note |
| `closed-stale` | no longer running, worked on after its note |
| `closed-none` | no longer running, 30+ tool calls, no note |

Sessions with no note and under 30 tool calls (a quick question, an earlier run of this skill) are left out. If the script fails (it reads Claude Code internals, which can change), say so and stop.

### 2. Write the list

Only this session writes the daily note. With `--dry-run`, skip this step.

- Find the `session-handoffs daily note:` line in the user's CLAUDE.md or memory and fill in `{date}` with the day being wrapped up. If there is none, print the list instead.
- Add one line per row that has a path, under that heading, after the items already there and before the next heading. Skip a path already in the note. Change nothing else in the note.
  - `` - [ ] **<title>** `<path>` ``, with ` (out of date)` after the title for `stale` and `closed-stale` rows and ` (snapshot)` for snapshots.
- Keep titles to a few words: take the `title` column (the note's first heading, else its file name) and drop a leading "Handoff"/"Handoff —"/"Handoff:" label, dates, and "(written …)" or "START HERE" parts: "Handoff — S2 drain + storage budget, Monday 28 Sep (written Fri 25 Sep ~10:30Z)" becomes "S2 drain + storage budget".

### 3. Report and offer

Show a short table: session, verdict, title, path. For `stale`, `none`, `closed-stale` and `closed-none` sessions, offer the next step, without doing it unasked:

- a running session: `--ask <name>`, since the session itself writes the best note. If its `last_active` is over an hour ago, say that waking it re-reads its whole context, which costs more.
- a closed session, or one that stays busy: `--from-transcript <name or sid8>`.

Nothing is pending after this: re-run the skill any time to pick up new notes.

### 4. `--ask NAME`: one request, no waiting

1. Load `ListAgents` and `SendMessage` with ToolSearch (`select:ListAgents,SendMessage`) and call `ListAgents`. Ask only local interactive sessions whose row says idle. For a busy one, say so and offer `--from-transcript`: a message to a busy session is read between its tool calls, in the middle of its task.
2. Send one `SendMessage` with the request below, and no `notify_when_idle`. Don't wait for anything. If the result says the message is held for approval, tell the user.
3. Re-run step 1 later to pick up the note.

The request is plain text (an `@path` or a `/command` inside it does nothing). Its first line is the preview shown in that terminal. Fill in `<me>` and `<date>`:

```text
End-of-day handoff request from <me> (/session-handoffs): please make sure the work in this session has a current handoff note.
- If the note you are working from (your own, or the one you resumed from) is still current, do nothing.
- Otherwise update that note with Edit, changing only what changed, or write a new one named handoff_<date>_<topic>.md in the directory that holds your memory/ directory (~/.claude/projects/<project>/). Never in a git worktree, the session scratchpad or /tmp: those get deleted. Don't edit notes about other work.
- Make it self-contained for a fresh session with no context: one-line status; current state; ordered next steps starting with a concrete first action; decisions waiting on the user; traps; branches, PRs, worktrees and paths; how to resume.
- Write from what you already know: at most a quick git status or gh pr view. Link PRs and issues, don't paste them.
- Update your project memory's line for this work in place so it points at the note. Add one short line only if there is none.
- Do nothing else: no other work, approve nothing. If a write is denied, say so and stop. No need to reply: <me> reads your note on its next run.
```

### 5. `--from-transcript NAME|SID8`: a snapshot from the transcript

1. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/handoff_status.py" --digest '<name or sid8>'`, with the same `--date`. It prints the session's latest note, the snapshot path (in this session's project directory), and a compact log of its day: the user's prompts, Claude's messages, messages from other sessions, and one line per tool call, without tool output and with secrets masked.
2. Read the latest note if there is one. Then write the snapshot at the printed path, replacing it if it already exists, opening with:
   `> Snapshot written by /session-handoffs from <name or sid8>'s transcript at <HH:MM>. That session has not reviewed it. Its own last note: <path, or none>.`
   Follow the same checklist as the request in step 4, and say what was still in progress. Write only what the log shows. Never copy secrets, tokens or credentials; link PRs and issues.
3. Don't edit that session's own note or memory: it may still be working and writing to them.
4. Add one line to this session's project memory pointing at the snapshot, so a future session finds it; on a re-run, replace that line.
5. Re-run step 1: the snapshot now counts for the session it describes. Add it to the list (step 2).

## Limits

- The check relies on Claude Code's local session registry and transcript format, which are not a documented interface.
- Only Write, Edit and NotebookEdit calls are seen. A note written through the shell isn't detected.
- A note is a `.md` file whose name contains "handoff", outside `memory/`, temp dirs and git worktrees. It is listed if it still exists, doesn't open with a SUPERSEDED banner (a line starting with the word, or a quoted `>` line containing it, after any frontmatter), and any date in its name falls between the day wrapped up and 3 days after it; otherwise the session's latest usable note is listed.
- A session that stays busy keeps its last note in the list until it finishes; a snapshot fills the gap.
- The check reads `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`.
- An asked session's writes may trigger a permission prompt in its own terminal.
