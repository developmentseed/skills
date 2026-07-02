---
name: vault-save
description: Export a Claude-generated markdown document (spec, plan, ADR, runbook, issue, or note) to the user's Obsidian vault with structured frontmatter. Use when the user asks to save, export, or store a document to their vault/notes/Obsidian — e.g. "save this to my vault", "export this spec", "store this plan", "put this in my notes", "add this to Obsidian". Do not write to the vault directly without going through this skill; it handles frontmatter, filename sanitization, collision checking, and confirmation.
---

# vault-save — Export a document to the Obsidian vault

Save a Claude-generated markdown document to `${user_config.vault_dir}/claude-docs/` with structured frontmatter. Works mid-session without waiting for SessionEnd capture.

---

## Step 1 — Identify the document to save

Look through the current conversation for markdown documents Claude generated (specs, plans, ADRs, runbooks, issues, notes). A "document" is a self-contained piece of writing, not a code snippet or a conversational reply.

- If there is exactly one clear candidate, use it.
- If the user specified which document (e.g. "save the spec above"), use that one.
- If there are multiple candidates, list them briefly and ask: "Which document should I save?" — wait for the user to choose before continuing.
- If the document was provided inline in the skill invocation, use that content.

## Step 2 — Infer document metadata

Derive the following fields from the document content and the current working directory.

**type** — choose the best fit:
- `spec` — requirements or feature specification
- `plan` — implementation plan or task breakdown
- `adr` — architecture decision record
- `runbook` — operational procedure or how-to
- `issue` — bug report or GitHub issue draft
- `note` — reference note, research finding, or concept explanation
- `document` — anything that does not fit the above

**title** — use the first H1 heading (`# …`) in the document, or the first H2 if no H1 exists, or ask the user if neither exists. Sanitize: remove `|`, `]]`, `[[`, `#`, and backtick characters; collapse multiple spaces to one; truncate to 120 characters.

**project** — run `git -C <cwd> rev-parse --show-toplevel 2>/dev/null | xargs basename` to get the repo name, falling back to `home` if not in a git repo or the command fails.

**tags** — generate 2–5 topic tags inferred from the document content. Always include `claude-code` and the project name. Use lowercase, hyphenated slugs (e.g. `api-design`, `auth-flow`).

**created** — today's date in YYYY-MM-DD format.

**model** — the current model ID (e.g. `claude-sonnet-4-6`).

**Step 2c — Infer `summary`**: Write one sentence (≤ 140 characters) describing what this document is. Prose, no markdown. Sanitize same as title: remove `|`, `]]`, `[[`, `#`, backticks, control characters; collapse whitespace. Self-check the character count before proceeding — if it exceeds 140 chars, shorten it until it fits.

Example — too long (145 chars):
> "Specification for the vault-save refactor that moves exports from Inbox/auto to claude-docs and adds summary and description frontmatter fields."

Shortened to ≤ 140:
> "Specification for vault-save refactor: moves exports to claude-docs/ and adds summary and description frontmatter."

**Step 2d — Infer `description`**: Write 1–3 short paragraphs expanding on the summary. Rules for writing the YAML literal block scalar:
- Start the value with `description: |`
- Every content line must be indented by exactly 2 spaces
- Blank lines between paragraphs must be completely empty (no spaces)
- Never include a line that is exactly `---` — it would be misread as a YAML document separator
- The block ends when indentation returns to zero (i.e., the next YAML key or the closing `---`)

Example:
```
description: |
  This plan documents the /vault-save refactor, moving exports from Inbox/auto/
  to a top-level claude-docs/ folder for clarity.

  The refactor also adds summary (≤140 chars) and description (literal block)
  to frontmatter, making saved documents self-describing in Obsidian.
```

## Step 3 — Generate the filename

1. Take the sanitized title from Step 2.
2. NFKD-normalize, lowercase, replace every character outside `[a-z0-9]` with `-`, collapse consecutive hyphens, strip leading/trailing hyphens. Truncate to 60 characters.
3. Assemble: `YYYY-MM-DD-<slug>.md`
4. Check whether `${user_config.vault_dir}/claude-docs/<filename>` already exists. If it does, append `-2`, `-3`, etc. until the path is free.

## Step 4 — Write the file

Write the complete file to `${user_config.vault_dir}/claude-docs/<filename>` with this exact structure:

```
---
title: <sanitized title>
summary: <one sentence, ≤140 chars, sanitized>
description: |
  <paragraph 1, indented 2 spaces>

  <paragraph 2, indented 2 spaces>
type: <type>
project: <project>
tags: [<tag1>, <tag2>, ...]
source: claude-code-export
created: <YYYY-MM-DD>
model: <model-id>
---

<document body — verbatim content, preserving all headings, code blocks, and lists>
```

Do not add a `## Referenced in` section — it is appended later (if at all) by an Inbox-triage extension when the document is linked from a daily/weekly note.

## Step 5 — Confirm

Report the saved location to the user:

```
Saved to claude-docs/<filename>
```

If the write fails for any reason, report the error and do not retry silently.
