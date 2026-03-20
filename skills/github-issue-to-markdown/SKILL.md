---
name: github-issue-to-markdown
description: Exports a GitHub Issue (including comments and private issues) to a clean Markdown file using the GitHub CLI (`gh`). Use when asked to archive, export, or save a GitHub issue.
---

# GitHub Issue to Markdown

Fetches GitHub issues (including from private repos) using the `gh` CLI and converts them into structured Markdown files with metadata, description, and threaded comments.

## Prerequisites

1. **GitHub CLI (`gh`)**: Must be installed. See [cli.github.com](https://cli.github.com/).
2. **Authentication**: You must be logged in via `gh auth login`. The skill will check for you and prompt if not authenticated.
3. **Multiple accounts**: If you use more than one GitHub account (e.g. work and personal), `gh` supports multiple logins. Use the `--user` flag to specify which account to use for a given export.

## Usage

**Export a single issue:**
```bash
./run.sh "https://github.com/owner/repo/issues/123"
```

**Export with comments:**
```bash
./run.sh --comments "https://github.com/owner/repo/issues/123"
```

**Export search results:**
```bash
./run.sh "https://github.com/owner/repo/issues?q=is:issue+state:open"
```

**Options:**
- `--limit N`: Maximum number of issues to export from search results (default: 5)
- `--comments`: Include comments in the output (off by default)
- `--user USERNAME`: Use a specific authenticated GitHub account
- `--auth`: Run `gh auth login` interactively

## Output

Exports are saved to an `output/` folder (gitignored) as timestamped Markdown files with:
- Metadata (title, author, date, URL)
- Issue description
- Threaded comments with author attribution and timestamps (if `--comments` used)
- Emoji reactions on issues and comments

## Agent Instructions

When a user asks to export an issue:

### If `gh` is available and authenticated:
1. Check access. If the repo is private or access is denied, ask which GitHub account to use.
2. Use the `--user` flag to switch accounts if needed.
3. Always use `--comments` unless the user specifically says not to, comments often contain the most important context.

### If in a restricted environment (Claude web) or `gh` is unavailable:
1. Guide the user to run locally:
   ```bash
   gh issue view "ISSUE_URL" --json title,body,author,createdAt,comments,reactionGroups,url
   ```
2. Process pasted JSON into the standard Markdown format.

## How it Works

1. Checks `gh` authentication status
2. Uses `gh issue view --json` to fetch issue data (title, body, author, comments, reactions)
3. A Python script (`scripts/export_issue.py`) converts the JSON to structured Markdown
4. Output is saved with a timestamped filename

## Packaging for Claude

To zip this skill for upload to Claude web:
```bash
zip -r github-issue-to-markdown.zip github-issue-to-markdown/ -x "*/.venv/*" "*/output/*" "*/.env" "*/__pycache__/*" "*/.DS_Store"
```
