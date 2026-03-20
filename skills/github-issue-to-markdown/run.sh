#!/bin/bash

# Get the directory of the script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OUTPUT_DIR="$DIR/output"
TEMP_JSON="$DIR/temp_issue.json"

mkdir -p "$OUTPUT_DIR"

if [[ "$1" == "--auth" ]]; then
    gh auth login
    exit 0
fi

# Default values
LIMIT=5
INCLUDE_COMMENTS="false"
USERNAME=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --user) USERNAME="$2"; shift ;;
        --limit) LIMIT="$2"; shift ;;
        --comments) INCLUDE_COMMENTS="true" ;;
        -*) echo "Unknown option: $1"; exit 1 ;;
        *) ISSUE_REF="$1" ;;
    esac
    shift
done

if [[ -n "$USERNAME" ]]; then
    echo "Switching to GitHub account: $USERNAME"
    gh auth switch --user "$USERNAME"
    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to switch to account '$USERNAME'. Make sure it is logged in."
        exit 1
    fi
fi

if [[ -z "$ISSUE_REF" ]]; then
    echo "Usage: $0 [--user USERNAME] [--limit LIMIT] [--comments] <ISSUE_URL_OR_SEARCH_URL>"
    exit 1
fi

# Check authentication
if ! gh auth status >/dev/null 2>&1; then
    echo "Error: Not authenticated with GitHub. Run '$0 --auth' to login."
    exit 1
fi

echo "Fetching data..."

# Determine if it's a search URL or a single issue
if [[ "$ISSUE_REF" == *"/issues?"* ]]; then
    # Search URL
    # Extract the query part after "q="
    QUERY=$(echo "$ISSUE_REF" | sed -n 's/.*q=\([^&]*\).*/\1/p' | python3 -c "import sys, urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))")

    # Extract owner and repo from URL
    REPO=$(echo "$ISSUE_REF" | sed -E 's|https://github.com/([^/]+/[^/]+)/issues.*|\1|')

    echo "Searching issues in $REPO with query: $QUERY (Limit: $LIMIT)"

    # Get issue numbers from search
    ISSUE_NUMBERS=$(gh issue list -R "$REPO" --search "$QUERY" --limit "$LIMIT" --json number -q '.[].number')

    if [[ -z "$ISSUE_NUMBERS" ]]; then
        echo "No issues found matching the query."
        exit 0
    fi

    # Fetch full data for each issue and combine into a JSON list
    echo "[" > "$TEMP_JSON"
    FIRST=true
    for NUM in $ISSUE_NUMBERS; do
        if [ "$FIRST" = true ]; then
            FIRST=false
        else
            echo "," >> "$TEMP_JSON"
        fi
        gh issue view -R "$REPO" "$NUM" --json title,body,author,createdAt,comments,reactionGroups,url >> "$TEMP_JSON"
    done
    echo "]" >> "$TEMP_JSON"
else
    # Single Issue
    gh issue view "$ISSUE_REF" --json title,body,author,createdAt,comments,reactionGroups,url > "$TEMP_JSON"
    FETCH_STATUS=$?
    if [[ $FETCH_STATUS -ne 0 ]]; then
        echo "Error: Failed to fetch data for $ISSUE_REF. Make sure the URL is correct and you have access."
        rm -f "$TEMP_JSON"
        exit 1
    fi
    # Wrap in array for consistent processing in python script
    sed -i '' 's/^/[/; s/$/]/' "$TEMP_JSON" || sed -i 's/^/[/; s/$/]/' "$TEMP_JSON"
fi

echo "Converting to Markdown..."
PY_ARGS=("$TEMP_JSON" "--output" "$OUTPUT_DIR/issue_export.md")
if [[ "$INCLUDE_COMMENTS" == "true" ]]; then
    PY_ARGS+=("--comments")
fi

python3 "$DIR/scripts/export_issue.py" "${PY_ARGS[@]}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
if command -v jq >/dev/null 2>&1; then
    FIRST_TITLE=$(jq -r '.[0].title' "$TEMP_JSON" | sed 's/[^a-zA-Z0-9]/_/g' | cut -c1-50)
    COUNT=$(jq '. | length' "$TEMP_JSON")
    if [ "$COUNT" -gt 1 ]; then
        FILENAME="${TIMESTAMP}_search_result_${COUNT}_issues.md"
    else
        FILENAME="${TIMESTAMP}_${FIRST_TITLE}.md"
    fi
else
    FILENAME="${TIMESTAMP}_github_export.md"
fi

mv "$OUTPUT_DIR/issue_export.md" "$OUTPUT_DIR/$FILENAME"
rm -f "$TEMP_JSON"

echo "Done! File saved to: $OUTPUT_DIR/$FILENAME"
