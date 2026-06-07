# Path A — Curation Prompt (claude-sonnet-4-6)

You receive the full text of a Claude Code session. Extract a **single durable artifact** if one is clearly present: a decision, runbook, spec, gotcha, or devlog-snippet. If the session is exploratory debugging, venting, or low-signal, return **exactly** `null` (lowercase, no quotes, no JSON).

## Artifact types

- **decision** — an architectural or tech-stack choice made with clear reasoning
- **runbook** — a repeatable procedure: steps to deploy, debug, or recover
- **gotcha** — a non-obvious constraint, footgun, or env-specific quirk that bit the user
- **spec** — a well-formed requirement or design doc produced during the session
- **devlog-snippet** — a meaningful progress note worth keeping (rare — only when there is no better type)

There is **no generic fallback**. If the session doesn't clearly fit one of these five, return `null`.

## Output format

Return **valid JSON only** — no prose, no markdown fences.

When returning an artifact:
```json
{
  "title": "Short human title (max 80 chars, no | ]] [[ # `)",
  "type": "decision|runbook|gotcha|spec|devlog-snippet",
  "body": "<the artifact itself — the runbook steps, the decision rationale, the gotcha description>",
  "source_links": ["https://github.com/org/repo/pull/123"],
  "tags": ["topic1", "topic2"]
}
```

When no artifact is warranted:
```
null
```

## Rules

1. Body is the **artifact itself** — not a transcript recap or summary.
2. Source links: include only URLs explicitly mentioned in the session. Leave empty array if none.
3. Tags: 2–5 lowercase topic tags derived from content. Never include `claude-code` or `curated` (added by the capture tool).
4. Title must not contain `|`, `]]`, `[[`, `#`, or backtick.
5. If uncertain between returning null and an artifact, return null — this path's value is precision, not recall. A non-deterministic null is retried once before the session is dropped, so a genuinely durable artifact still gets a second chance; reserve artifacts for genuinely reusable content.
