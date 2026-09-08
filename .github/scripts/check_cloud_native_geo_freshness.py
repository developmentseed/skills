#!/usr/bin/env python3
"""Check tracked-sources.yaml for the cloud-native-geo skill against live registries.

Detection only: this never edits the skill or the manifest. When a tracked package has
shipped a newer release than `last_recorded_version`, it opens (or updates) a single
GitHub issue listing what's changed, for a human to review and fold into the skill.

Run locally with no GITHUB_REPOSITORY set to just print the report (used for local
verification). Run in CI (GITHUB_REPOSITORY + GITHUB_TOKEN set, `gh` on PATH) to also
open, update, or close the tracking issue.
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
    """Latest release tag for a repo.

    Prefers /releases/latest, which GitHub actually defines as "the newest release".
    The /tags endpoint is NOT ordered by date or semver -- e.g. opengeospatial/geoparquet
    returns v1.1.0 before v1.1.0+p1 -- so tags[0] is only a fallback for repos that tag
    without cutting releases.
    """
    try:
        return fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")["tag_name"]
    except (urllib.error.HTTPError, KeyError):
        pass

    tags = fetch_json(f"https://api.github.com/repos/{repo}/tags?per_page=100")
    if not tags:
        raise ValueError(f"no releases or tags found for {repo}")
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


def find_open_issue(repo: str) -> int | None:
    """Number of the open tracking issue, or None.

    Filters titles locally rather than via `--search`: GitHub's search index lags behind
    writes, so a search-based lookup can miss an issue this job just created and open a
    duplicate.
    """
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--limit", "100",
            "--json", "number,title",
        ],
        capture_output=True, text=True, check=True,
    )
    for issue in json.loads(result.stdout or "[]"):
        if issue["title"] == ISSUE_TITLE:
            return issue["number"]
    return None


def sync_issue(body: str | None) -> None:
    """Reconcile the tracking issue with the current state.

    `body` is the report when something drifted, or None when everything matches -- in
    which case an open issue is closed so a stale report doesn't linger after the drift
    has been folded into the skill.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("\n(No GITHUB_REPOSITORY set — skipping issue sync, report only.)")
        return

    number = find_open_issue(repo)

    if body is None:
        if number is None:
            return
        subprocess.run(
            [
                "gh", "issue", "close", str(number),
                "--repo", repo,
                "--comment", "Everything matches the recorded versions again — closing.",
            ],
            check=True,
        )
        print(f"Closed resolved issue #{number}")
        return

    if number is not None:
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
        sync_issue(None)
        return 0

    print(f"\n{len(drifted)} package(s) have newer releases than recorded:")
    for d in drifted:
        print(f"  - {d['name']}: {d['recorded']} -> {d['latest']}")

    sync_issue(build_issue_body(drifted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
