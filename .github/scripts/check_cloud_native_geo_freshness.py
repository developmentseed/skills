#!/usr/bin/env python3
"""Check tracked-sources.yaml for the cloud-native-geo skill against live registries.

Detection only: this never edits the skill or the manifest. When a tracked package has
shipped a newer release than `last_recorded_version`, it opens (or updates) a single
GitHub issue listing what's changed, for a human to review and fold into the skill.

Run locally with no GITHUB_TOKEN to just print the report (used for local verification).
Run in CI (GITHUB_TOKEN + GITHUB_REPOSITORY set, `gh` on PATH) to also file the issue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "skills/cloud-native-geo/references/tracked-sources.yaml"
ISSUE_TITLE = "cloud-native-geo: dependency freshness check"
REQUEST_TIMEOUT = 15


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "cloud-native-geo-freshness-check"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.load(resp)


def latest_pypi(package: str) -> str:
    return fetch_json(f"https://pypi.org/pypi/{package}/json")["info"]["version"]


def latest_npm(package: str) -> str:
    return fetch_json(f"https://registry.npmjs.org/{package}/latest")["version"]


def latest_github_tag(repo: str) -> str:
    tags = fetch_json(f"https://api.github.com/repos/{repo}/tags?per_page=1")
    if not tags:
        raise ValueError(f"no tags found for {repo}")
    return tags[0]["name"]


FETCHERS = {
    "pypi": latest_pypi,
    "npm": latest_npm,
    "github-tags": latest_github_tag,
}


def check_entry(entry: dict) -> dict | None:
    registry = entry["registry"]
    fetcher = FETCHERS.get(registry)
    if fetcher is None:
        print(f"  skip {entry['name']}: unsupported registry {registry!r}", file=sys.stderr)
        return None

    try:
        latest = fetcher(entry["package"])
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
        print(f"  warn {entry['name']}: could not check ({exc})", file=sys.stderr)
        return None

    recorded = str(entry["last_recorded_version"])
    if latest != recorded:
        return {
            "name": entry["name"],
            "recorded": recorded,
            "latest": latest,
            "docs_url": entry["docs_url"],
        }
    return None


def build_issue_body(drifted: list[dict]) -> str:
    lines = [
        f"Weekly check found **{len(drifted)}** package(s) tracked by the `cloud-native-geo` "
        "skill with a newer release than what's recorded in "
        "`skills/cloud-native-geo/references/tracked-sources.yaml`.",
        "",
        "Review whether the skill's guidance still holds, update the prose if the new "
        "release changes anything user-facing, then update `last_recorded_version` / "
        "`last_checked` for each row below as part of that PR.",
        "",
        "| Package | Recorded | Latest | Docs |",
        "|---|---|---|---|",
    ]
    for d in drifted:
        lines.append(f"| {d['name']} | {d['recorded']} | {d['latest']} | {d['docs_url']} |")
    return "\n".join(lines)


def file_or_update_issue(body: str) -> None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("\n(No GITHUB_REPOSITORY set — skipping issue creation, report only.)")
        return

    existing = subprocess.run(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--search", f'"{ISSUE_TITLE}" in:title',
            "--json", "number",
        ],
        capture_output=True, text=True, check=True,
    )
    numbers = [i["number"] for i in json.loads(existing.stdout or "[]")]

    if numbers:
        number = numbers[0]
        subprocess.run(
            ["gh", "issue", "edit", str(number), "--repo", repo, "--body", body],
            check=True,
        )
        print(f"Updated existing issue #{number}")
    else:
        subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", repo,
                "--title", ISSUE_TITLE,
                "--body", body,
            ],
            check=True,
        )
        print("Filed a new freshness-check issue")


def main() -> int:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    print(f"Checking {len(manifest)} tracked sources...")

    drifted = [result for entry in manifest if (result := check_entry(entry)) is not None]

    if not drifted:
        print("Everything matches the recorded versions. Nothing to do.")
        return 0

    print(f"\n{len(drifted)} package(s) have newer releases than recorded:")
    for d in drifted:
        print(f"  - {d['name']}: {d['recorded']} -> {d['latest']}")

    file_or_update_issue(build_issue_body(drifted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
