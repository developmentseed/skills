---
name: github-issue-to-markdown
description: Exports a GitHub Issue (including comments and private issues) to a clean Markdown file using the GitHub CLI (`gh`). Use when asked to archive, export, or save a GitHub issue.
---

# GitHub Issue to Markdown

This skill leverages the official GitHub CLI (`gh`) to fetch issue data and converts it into a structured Markdown file.

## Environment & Compatibility

> [!IMPORTANT]
> **Needs an authenticated `gh`.** This skill shells out to the GitHub CLI, so it runs where `gh` is installed and logged in — Claude Code on your own machine is the normal case.
>
> The **claude.ai web sandbox** cannot run an interactive `gh auth login`; there, use the **Copy-Paste Fallback** below.

## Copy-Paste Fallback (for Claude Web)

If you're using Claude on the web or don't have `gh` installed:

1. **Run this command locally** (replace the URL with your issue):
   ```bash
   gh issue view "https://github.com/owner/repo/issues/123" --json title,body,author,createdAt,comments,url
   ```

2. **Copy the JSON output** and paste it into Claude.

3. **Tell Claude**: "Convert this GitHub issue JSON to Markdown using the github-issue-to-markdown format."

**For multiple issues**, run for each issue and paste all JSON objects, or use:
```bash
gh issue list -R owner/repo --limit 5 --json title,body,author,createdAt,comments,url
```

## Prerequisites (running the script yourself)

1.  **GitHub CLI (`gh`)**: Must be installed on your system.
2.  **Authentication**: You must be logged in. Run `./run.sh --auth` if you need to sign in.
3.  **Multiple Accounts**: The script uses whichever account `gh` is currently authenticated as (or `GH_TOKEN` if set). To use a different account for a run, set the token yourself: `export GH_TOKEN=$(gh auth token --user <login>)`.

## Usage

1.  **Export a Single Issue**:
    Provide the full URL of the GitHub issue.
    ```bash
    ./run.sh "https://github.com/owner/repo/issues/123"
    ```

2.  **Export Search Results**:
    Provide a GitHub search URL. By default, it exports the first 5 issues without comments.
    ```bash
    ./run.sh "https://github.com/owner/repo/issues?q=is:issue+state:open"
    ```

3.  **Options**:
    - `--limit N`: Specify the maximum number of issues to export (default: 5).
    - `--comments`: Include comments in the markdown output (off by default).

4.  **Where files land**: `./output/` under the directory you ran the command
    from — not under the skill's own directory. Set `GH_ISSUE_OUTPUT_DIR` to
    send every export to one fixed folder instead:
    ```bash
    export GH_ISSUE_OUTPUT_DIR=~/Documents/github-issue-exports
    ```
    (When a skill is installed as a plugin it runs from a versioned cache
    directory; anything written next to the script is stranded there on the
    next version bump. Hence caller-relative by default.)

## Agent Instructions

When a user asks to export an issue:

### If `gh` is available and authenticated:
1.  **Check the active account**: Run `gh api user --jq '.login'` to see who `gh` is authenticated as.
2.  **Access denied?** Never run `gh auth switch` or `gh auth login` yourself — account state belongs to the user. Instead, tell the user which account is active and ask them to point `GH_TOKEN` at the right one, then re-run:
    ```bash
    export GH_TOKEN=$(gh auth token --user <login>)
    ```

### If in a restricted environment (Claude web) or `gh` is unavailable:
1.  **Detect the limitation**: If `gh` is not installed, not authenticated, or network access is blocked.
2.  **Guide the user**: Provide the exact command they need to run locally:
    ```bash
    gh issue view "ISSUE_URL" --json title,body,author,createdAt,comments,url
    ```
3.  **Process pasted JSON**: When the user pastes JSON, format it into Markdown following the standard output format (metadata header, description, comments with author/timestamp).
4.  **Output format** should match:
    ```markdown
    ## Issue Title

    - **Author:** @username
    - **Created:** YYYY-MM-DD HH:MM:SS
    - **URL:** https://github.com/...

    ### Description

    [issue body]

    ### Comments

    #### @commenter commented on YYYY-MM-DD HH:MM:SS

    [comment body]

    ---
    ```

## How it Works

1.  The skill first checks if `gh` is authenticated.
2.  It uses `gh issue view --json` to fetch the title, body, author, and all comments.
3.  A Python script (`scripts/export_issue.py`) processes the JSON and generates a Markdown file with:
    - Metadata (Title, Author, Date, URL)
    - The original issue description
    - A threaded view of all comments with author attribution and timestamps.
