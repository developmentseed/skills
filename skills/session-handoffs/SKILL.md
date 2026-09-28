---
name: session-handoffs
description: End-of-day wrap-up for Claude Code users who run several sessions at once. Checks which running sessions already left a handoff note today, asks only the others to write one (never mid-task), and lists every note under the "For Tomorrow" heading of your daily note. Use for /session-handoffs, "wrap up my sessions", "handoff notes for all sessions", or "end of day handoffs".
---

# Session handoffs

Gets every Claude Code session running on this machine to leave a self-contained handoff note, so tomorrow starts from a note instead of from memory, and collects the links in one list.

## When to use this

At the end of a day with several Claude Code sessions open, before you close them. Run it in a fresh session: that session coordinates and doesn't write a handoff itself.

## Requirements

- **Claude Code only.** It uses the `ListAgents` and `SendMessage` tools (local cross-session messaging), which other agents don't have.
- `python3` (standard library only) for the check script.
- Optional: a daily note. Add one line to your `~/.claude/CLAUDE.md` naming the file and the heading, for example:
  `session-handoffs daily note: ~/notes/daily/{date}.md, heading "## For Tomorrow"`
  Without it, the list is printed instead.

## Arguments

- `--dry-run`: show the table and the request, send nothing, write nothing.
- `--only NAME ...`: ask exactly these sessions, whatever the check says.
- `--date YYYY-MM-DD`: defaults to today. After midnight, pass the previous day, or every session looks like it has no handoff.

## How it works

### 1. List the running sessions

Load the tools with ToolSearch (`select:ListAgents,SendMessage`) and call `ListAgents`. Its first line gives this session's own name. Keep only local interactive peer sessions. Drop this session, subagents and teammates, `claude -p` / headless workers (a running workflow's workers show up here), and cloud or Remote Control rows (they can't be subscribed to and nothing reports back from them).

### 2. Check who already has a handoff

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/handoff_status.py" --self '<own name>' --live '<name>' '<name>' ...
```

Quote each name. Add `--date` if one was given.

The script reads Claude Code's local session registry and transcripts (read-only) and prints one TSV row per handoff note written that day:

| verdict | meaning | action |
|---|---|---|
| `fresh` | running, wrote a handoff, little work since | don't message it; list its note |
| `stale` | running, wrote one, then did a lot more (over 10 tool calls) | ask for an update |
| `none` | running, no usable handoff that day (none written, the write failed, or the note sits in a temp dir or worktree) | ask for one |
| `unknown` | running, but not found in the registry | ask for one |
| `closed` | no longer running, left a handoff | list its note |
| `closed-none` | no longer running, worked that day, no handoff | report only: nobody to ask |

Show the table. If the script fails (it reads Claude Code internals, which can change), treat every running session as `none`. With `--dry-run`, also show the request below, then stop.

### 3. Ask, without interrupting

Sessions to ask: `stale`, `none` and `unknown`, or exactly the `--only` names.

1. In one parallel block, send each of them a pure subscription: `SendMessage` with `notify_when_idle: true` and no `message`. It costs the peer nothing, and an idle peer's notice comes back at once. If the result says no subscription was made (older version, session gone, messages refused), send the request right away only if its `ListAgents` row said idle; otherwise record `not asked (<reason>)`.
2. Send the request, again with `notify_when_idle: true`, only when a notice says the peer is idle. A notice that it exited, is unavailable, or that the subscription expired means record it and send nothing. Never send the request to a busy session: it would read it between tool calls, in the middle of its task.
3. Send each peer the request once, plus at most one follow-up (step 4). Ask peers only for their note and memory line, nothing else.

The request is plain text: an `@path` or a `/command` inside a message does nothing. Its first line is the preview shown in that terminal, so keep it a full sentence. Fill in `<me>` and `<date>`:

```text
End-of-day handoff request from <me> (/session-handoffs): please make sure today's work in this session has a handoff note, then reply.
- If a handoff note that THIS session wrote today is still current, don't touch it: just reply.
- Otherwise write one, or update your own with Edit, changing only what changed. Never rewrite a whole note, never edit a note another session wrote.
- Name new notes handoff_<date>_<topic>.md and save them in the directory that holds your memory/ directory (~/.claude/projects/<project>/). Never in a git worktree, the session scratchpad or /tmp: those get deleted.
- Make it self-contained for a fresh session with no context: one-line status; current state; ordered next steps starting with a concrete first action; decisions waiting on the user; traps; branches, PRs, worktrees and paths; how to resume.
- Write from what you already know: at most a quick git status or gh pr view. Link PRs and issues, don't paste them.
- If your project memory has a line about this work, update it in place to point at the note. Add one short line only if there is none.
- Then reply with SendMessage to "<me>", one line per piece of work, with no | inside a field:
  HANDOFF | high or normal | <short title> | <absolute path> | <first action tomorrow>
  or: NONE | <reason>
```

### 4. Collect

A peer is done when its reply arrives, or when its second idle notice arrives with no reply (record `no reply`). For each `HANDOFF` line, the path must exist and must not be under `/tmp`, `/private/tmp`, `/var/folders`, a `.claude/worktrees/` directory or any other git worktree. If it fails that, send one follow-up asking the peer to move the note.

If a send result or a `[Cross-session delivery notice]` says a message was held or refused, record `held`.

### 5. Write the list

Only this session writes the daily note: several sessions writing at once would clash.

- Find the `session-handoffs daily note:` line in the user's CLAUDE.md or memory and fill in `{date}`. If there is none, print the list instead.
- Insert under that heading, before the next heading: `high` items at the top of the list, `normal` items after the items already there. Skip a path already in the note.
- Add the `fresh` and `closed` notes right after step 2, then each reply as it arrives:
  `` - [ ] **<title>:** <first action>. Handoff: `<path, with ~ for the home directory>` ``
  For notes nobody replied about, use the note's first heading as the title and "continue from the handoff" as the action. Append ` (important)` to the title of `high` items.
- Change nothing else in the note.

### 6. Report

One table: session → `fresh` / `updated` / `written` / `NONE` / `no reply` / `held` / `busy, not asked`, with the note path, followed by the `closed-none` sessions.

Keep this session open until every peer is done: closing it drops the pending subscriptions. Sessions still busy when the user stops are `busy, not asked`; ask them later with `--only <name>`.

## Limits

- The check relies on Claude Code's local session registry and transcript format, which are not a documented interface. When it can't match a session, that session is simply asked.
- Only Write and Edit tool calls are seen (the session's own and its subagents'). A note written through the shell isn't detected, so that session gets asked and just replies with the path.
- A note counts as a handoff when its file name contains "handoff", ends in `.md`, isn't under `memory/`, any date in its name is the day being checked, and it still exists outside temp dirs and `.claude/worktrees/`.
- The check reads `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`.
- Each peer's write may trigger a permission prompt in its own terminal.
