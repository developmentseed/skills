#!/usr/bin/env bash
set -euo pipefail

# Capture where the caller is BEFORE cd-ing to the skill dir: when installed
# as a plugin, "next to the script" is a versioned cache directory — exports
# there are stranded on every version bump and deleted by cache cleanups
CALLER_PWD="$(pwd)"
cd "$(dirname "$0")"

# --- Output directory ---
# Default: ./output under the directory you ran from. Override with
# GH_ISSUE_OUTPUT_DIR for a fixed home that survives everything.
OUTPUT_DIR="${GH_ISSUE_OUTPUT_DIR:-$CALLER_PWD/output}"
mkdir -p "$OUTPUT_DIR"

# --- Auth shortcut ---
if [[ "${1:-}" == "--auth" ]]; then
    gh auth login
    exit 0
fi

# --- Parse arguments ---
LIMIT=5
INCLUDE_COMMENTS="false"
ISSUE_REF=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --limit) LIMIT="$2"; shift ;;
        --comments) INCLUDE_COMMENTS="true" ;;
        -*) echo "Unknown option: $1"; exit 1 ;;
        *) ISSUE_REF="$1" ;;
    esac
    shift
done

if [[ -z "$ISSUE_REF" ]]; then
    echo "Usage: $0 [--limit LIMIT] [--comments] <ISSUE_URL_OR_SEARCH_URL>"
    exit 1
fi

# --- Check authentication ---
if ! gh auth status >/dev/null 2>&1; then
    echo "Error: Not authenticated with GitHub. Run '$0 --auth' to login."
    exit 1
fi

CURRENT_USER=$(gh api user --jq '.login' 2>/dev/null || echo "unknown")

# Never switch gh accounts here; the user controls account state.
access_help() {
    echo "Currently authenticated as: $CURRENT_USER"
    echo "If this repo needs a different account, set GH_TOKEN yourself and re-run:"
    echo '  export GH_TOKEN=$(gh auth token --user <login>)'
}

echo "Fetching data (as $CURRENT_USER)..."

TEMP_JSON="$(mktemp)"
trap 'rm -f "$TEMP_JSON"' EXIT

FIELDS="title,body,author,createdAt,comments,reactionGroups,url"

# --- Determine if it's a search URL or a single issue ---
if [[ "$ISSUE_REF" == *"/issues?"* ]]; then
    if ! command -v jq >/dev/null 2>&1; then
        echo "Error: jq is required for search-URL export."
        exit 1
    fi

    # Search URL — extract query part after "q="
    QUERY=$(echo "$ISSUE_REF" | sed -n 's/.*q=\([^&]*\).*/\1/p' | python3 -c "import sys, urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))")

    # Extract owner and repo from URL
    REPO=$(echo "$ISSUE_REF" | sed -E 's|https://github.com/([^/]+/[^/]+)/issues.*|\1|')

    echo "Searching issues in $REPO with query: $QUERY (Limit: $LIMIT)"

    # Get issue numbers from search
    if ! ISSUE_NUMBERS=$(gh issue list -R "$REPO" --search "$QUERY" --limit "$LIMIT" --json number -q '.[].number'); then
        echo "Error: Failed to search issues in $REPO."
        access_help
        exit 1
    fi

    if [[ -z "$ISSUE_NUMBERS" ]]; then
        echo "No issues found matching the query."
        exit 0
    fi

    # Fetch full data for each issue; jq -s slurps the concatenated objects into one array
    for NUM in $ISSUE_NUMBERS; do
        gh issue view -R "$REPO" "$NUM" --json "$FIELDS"
    done | jq -s '.' > "$TEMP_JSON"
else
    # Single issue — the python script accepts a bare object, no array wrapping needed
    if ! gh issue view "$ISSUE_REF" --json "$FIELDS" > "$TEMP_JSON"; then
        echo "Error: Failed to fetch data for $ISSUE_REF. Make sure the URL is correct and you have access."
        access_help
        exit 1
    fi
fi

echo "Converting to Markdown..."
PY_ARGS=("$TEMP_JSON" "--output" "$OUTPUT_DIR/issue_export.md")
if [[ "$INCLUDE_COMMENTS" == "true" ]]; then
    PY_ARGS+=("--comments")
fi

python3 scripts/export_issue.py "${PY_ARGS[@]}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
if command -v jq >/dev/null 2>&1; then
    FIRST_TITLE=$(jq -r 'if type == "array" then .[0].title else .title end' "$TEMP_JSON" | sed 's/[^a-zA-Z0-9]/_/g' | cut -c1-50)
    COUNT=$(jq 'if type == "array" then length else 1 end' "$TEMP_JSON")
    if [ "$COUNT" -gt 1 ]; then
        FILENAME="${TIMESTAMP}_search_result_${COUNT}_issues.md"
    else
        FILENAME="${TIMESTAMP}_${FIRST_TITLE}.md"
    fi
else
    FILENAME="${TIMESTAMP}_github_export.md"
fi

mv "$OUTPUT_DIR/issue_export.md" "$OUTPUT_DIR/$FILENAME"

echo "Done! File saved to: $OUTPUT_DIR/$FILENAME"
