---
name: session-kickoff
description: Morning start for Claude Code users who run several sessions at once. Reads the focus list in today's daily note and, for each open item that links a handoff note, starts a Claude Code session in that note's project, asking it to read the note and say what to do next. Sessions run in the background and appear together in `claude agents`. Skips notes a session already works from, so it's safe to re-run. The morning half of /session-handoffs. Use for /session-kickoff, "start my day", "kick off today's focus", or "open a session per handoff".
---

# Session kickoff

Starts one Claude Code session per handoff note in today's focus list, so each piece of work starts from its note instead of from memory. Each session is named after the item, starts in the project the note belongs to, and gets one question:

> Can you open `<note>` and tell me what I should do next? End with one plain line, no formatting: Next: <one step> · Needs me: yes/no · Time: <estimate>

The sessions answer and wait for you. That last line lets `--digest` (step 4) list every answer in one table. They run in the background: run `claude agents` in any terminal to see them all with their status, Enter to open one, ← to go back to the list. This skill only starts them: it never waits on a session, and skips a note that a session already works from, so running it again starts only what's missing.

## When to use this

In the morning, in a fresh session started where a note with no project should open (e.g. `~/code`). The evening before, /session-handoffs writes the list.

## Requirements

- Claude Code with background sessions (`claude --bg`); `python3` (standard library only).
- A daily note with a focus list. The skill reads a `session-kickoff daily note:` line in your `~/.claude/CLAUDE.md` or memory, for example:
  `session-kickoff daily note: ~/notes/daily/{date}.md, heading "## Today's Focus"`
  The heading matches whatever else the line holds, such as an emoji (`## 🎯 Today's Focus`). Without one, it uses the file on your `session-handoffs daily note:` line and the heading "Today's Focus"; with neither, it asks for the note.
- Items that link their handoff note by path or `[[wikilink]]`, as /session-handoffs writes them, for example:
  `- [ ] **Release 0.12** — ~/.claude/projects/-Users-me-code-app/handoff_2026-10-01_release.md`

## Arguments

- `--dry-run`: show what would open, open nothing.
- `--only N ...`: open only these items (their numbers in the report).
- `--digest`: open nothing; list what each item's session answered (step 4).
- `--date YYYY-MM-DD`: read that day's note. Defaults to today.

## How it works

### 1. Find the list

Fill `{date}` with the day. If the note doesn't exist, or its focus list has no open item with a note, say so and offer to use the previous daily note's `session-handoffs` heading instead (last evening's "For Tomorrow" list). Don't copy items between notes.

### 2. Open the sessions

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/kickoff.py" "<daily note>" --heading "<heading>" [--dry-run] [--only N ...]
```

Run it with the sandbox off (`dangerouslyDisableSandbox: true`): inside it, `claude agents --json --all` reports running sessions as failed, and starting background sessions is blocked. Inside the sandbox, or if it can't see the sessions, it stops with an error rather than open duplicates: say so and stop. The same goes for `--digest` (step 4).

It prints one TSV row per open item: item, status, name, dir, note, title.

| status | meaning |
|---|---|
| `opened` | `claude --bg -n <name>` runs in `dir` with the question |
| `would open` | the same, under `--dry-run` |
| `open in <session>` | a session already works from this note: switch to that one. It's running, or a background session that finished (`claude attach` reopens it; `claude rm` it to have a fresh one started). It works from the note if its first prompt names it, it wrote or edited the note (itself or through a subagent), or the note is a /session-handoffs snapshot of it. If several do, the newest is shown. The session running this skill counts only through its first prompt, not through notes it has edited. A later item with a note an earlier one opened shows the earlier session |
| `no note` | the item links no handoff note: it's the user's to pick up |
| `missing` | the linked note doesn't exist, or can't be read |
| `superseded` | the note opens with a SUPERSEDED banner: point the item at the note that replaced it |
| `failed: …` | the session didn't start, with `claude`'s error. The other items still open |

A status ending in ` · carried Nd` means the date in the note's file name is N working days (3 or more) before today: the item keeps getting carried forward. It still opens. In the report, ask whether to drop, delegate or do it today. Undated notes are never flagged, and a newly dated note starts the count again.

### 3. Report

Show a short table: item, status, session name, title. End with: run `claude agents` to open them, or `/session-kickoff --digest` in a few minutes to see their answers in one table. Nothing is pending after this; re-run the skill any time to start what's missing.

### 4. Digest (`--digest`)

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/kickoff.py" "<daily note>" --heading "<heading>" --digest [--only N ...]
```

Like step 2, run it with the sandbox off: it lists sessions the same way. It starts nothing and never waits on a session. It prints one TSV row per open item: item, state, name, answer. The session is the one an `open in <session>` row names, found the same way, so a closed, failed or `claude rm`-ed session doesn't count. It's shown even when the note has since been superseded or renamed. `answer` is the `Next:` line of the session's answer to the latest request, else that answer's first line, or `(no reply yet)`. The question asks for a `Next:` line, and a background task's notification isn't a request, so this stays the first answer until you ask the session something else. `state` is the session's state in `claude agents` (`working`, `blocked`, `done`…, `-` for an interactive one), or `no session`, `no note`, `missing`, `superseded`.

Show the table with `Needs me: yes` and `blocked` rows first: those are the sessions to open.

## Limits

- The focus list runs from its heading to the next heading of the same or a higher level, or a `---` rule; subheadings inside it are fine, code blocks are skipped. An item is a top-level list line (`- `, `- [ ] ` or `1. `). Checked (`[x]`) and cancelled (`[-]`) items and nested lines are skipped; other marks such as `[/]` count as open.
- An item's note is its first link to a `.md` file whose name contains "handoff", or a dated one in a `handoff/` or `handoffs/` directory, outside `memory/`. That's /session-handoffs' rule, except that notes in temp dirs and git worktrees count here. A wikilink is found as Obsidian finds it: by its folder if it names one, in any case. Paths with spaces aren't recognised.
- A note under `~/.claude/projects/<dir>/` opens in that project, found through `~/.claude.json`. A snapshot (`…_snapshot-<sid8>.md`) opens in the project of the session it describes. Any other note (a vault note, say) opens where this skill runs.
- The session check reads transcripts, which are not a documented interface. Reading a note doesn't count as working from it, because a /session-handoffs run reads every note: a session started without naming the note, which only read it, isn't seen, and nor is one that edited it through the shell.
- /session-handoffs counts a background session as running only while its process runs. One that has answered and stopped shows as closed in the evening wrap-up, though kickoff reports it as `open in <session>` (`claude attach` reopens it).
- Sessions start in your default permission mode.
