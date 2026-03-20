import json
import argparse
import os
from datetime import datetime

# Mapping GitHub reaction types to emojis
REACTION_MAP = {
    "THUMBS_UP": "👍",
    "THUMBS_DOWN": "👎",
    "LAUGH": "😄",
    "HOORAY": "🎉",
    "CONFUSED": "😕",
    "HEART": "❤️",
    "ROCKET": "🚀",
    "EYES": "👀"
}

def format_date(date_str):
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return date_str

def format_reactions(reaction_groups):
    if not reaction_groups:
        return ""

    parts = []
    for group in reaction_groups:
        count = group.get('users', {}).get('totalCount', 0)
        if count > 0:
            content = group.get('content')
            emoji = REACTION_MAP.get(content, content)
            parts.append(f"{emoji} {count}")

    if not parts:
        return ""

    return f"**Reactions:** {', '.join(parts)}"

def format_author(author_data):
    login = author_data.get('login', 'unknown')
    name = author_data.get('name')
    if name:
        return f"@{login} ({name})"
    return f"@{login}"

def issue_to_markdown(data, include_comments=False, is_single=True):
    title = data.get('title', 'Untitled Issue')
    body = data.get('body', '')
    author = format_author(data.get('author', {}))
    created_at = format_date(data.get('createdAt', ''))
    url = data.get('url', '')
    reactions = format_reactions(data.get('reactionGroups', []))

    # Single issue gets top-level # Title, multi-issue gets ## Title
    h1 = "#" if is_single else "##"
    h2 = "##" if is_single else "###"
    h3 = "###" if is_single else "####"

    md = [
        f"{h1} {title}",
        "",
        f"- **Author:** {author}",
        f"- **Created:** {created_at}",
        f"- **URL:** {url}",
        "",
        f"{h2} Description",
        "",
        body.strip(),
        "",
    ]

    if reactions:
        md.append(reactions)
        md.append("")

    if include_comments:
        md.append(f"{h2} Comments")
        md.append("")
        comments = data.get('comments', [])
        if not comments:
            md.append("_No comments yet._")
        else:
            for comment in comments:
                c_author = format_author(comment.get('author', {}))
                c_date = format_date(comment.get('createdAt', ''))
                c_body = comment.get('body', '')
                c_reactions = format_reactions(comment.get('reactionGroups', []))

                md.append(f"{h3} {c_author} commented on {c_date}")
                md.append("")
                md.append(c_body.strip())
                md.append("")
                if c_reactions:
                    md.append(c_reactions)
                    md.append("")
                md.append("---")
        md.append("")

    return "\n".join(md)

def main():
    parser = argparse.ArgumentParser(description='Convert GitHub Issue JSON to Markdown')
    parser.add_argument('json_file', help='Path to the JSON file containing issue data')
    parser.add_argument('--output', '-o', help='Output Markdown file path')
    parser.add_argument('--comments', action='store_true', help='Include comments in the output')

    args = parser.parse_args()

    with open(args.json_file, 'r') as f:
        data_list = json.load(f)

    if not isinstance(data_list, list):
        data_list = [data_list]

    is_single = len(data_list) == 1

    full_md = []
    if not is_single:
        full_md = ["# GitHub Issues Export", ""]
        # Table of Contents
        full_md.append("## Table of Contents")
        for i, data in enumerate(data_list):
            title = data.get('title', 'Untitled Issue')
            anchor = title.lower().replace(' ', '-').replace('"', '').replace('\'', '')
            # Simple anchor cleaning, may need more for robust GFM headers
            full_md.append(f"{i+1}. [{title}](#{anchor})")
        full_md.append("")
        full_md.append("---")
        full_md.append("")

    for i, data in enumerate(data_list):
        full_md.append(issue_to_markdown(data, include_comments=args.comments, is_single=is_single))
        if i < len(data_list) - 1:
            full_md.append("\n---\n")

    output_path = args.output
    if not output_path:
        # Generate default filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"{timestamp}_github_export.md"

    with open(output_path, 'w') as f:
        f.write("\n".join(full_md))

    print(f"Successfully exported to: {output_path}")

if __name__ == "__main__":
    main()
