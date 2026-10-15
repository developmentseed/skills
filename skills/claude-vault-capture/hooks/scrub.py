"""Secret scrubber — pure stdlib, no network, no subprocess.

Exports:
    scrub(text: str) -> tuple[str, dict[str, int]]
        Returns (redacted_text, counts_by_rule).
    scrub_output(text: str) -> str
        scrub() plus a random-token pass, for model-written text only.

Design:
- Idempotent: scrub(scrub(x)) == scrub(x)
- Deterministic: same input → same output
- Fail-safe: re.error on a rule → skip that rule, log to scrub-failures.md
- All patterns compiled with re.MULTILINE
"""

import re
import os
import sys
import math
import datetime
import pathlib
from collections import Counter

from scrub_rules import RULES


def _failures_path() -> pathlib.Path:
    env = os.environ.get("SCRUB_FAILURES_PATH")
    if env:
        return pathlib.Path(env)
    # Derived from this file's location so the checkout can live anywhere.
    return (
        pathlib.Path(__file__).resolve().parent.parent
        / "eval"
        / "state"
        / "scrub-failures.md"
    )


def _log_failure(rule_name: str, exc: Exception) -> None:
    fp = _failures_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}\t{rule_name}\t{exc}\n"
    try:
        with open(fp, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # log failure is itself non-fatal


def _compile_rules():
    """Compile all rules; a failed rule is logged and skipped.

    The probe subn validates the replacement template now, since a bad group
    reference would otherwise raise on every scrub call.
    """
    compiled = []
    for rule in RULES:
        try:
            pat = re.compile(rule["pattern"], re.MULTILINE)
            pat.subn(rule["replacement"], "")
            compiled.append((rule, pat))
        except (re.error, IndexError, KeyError) as exc:
            _log_failure(rule["name"], exc)
            # stderr lands in hooks.log (the hook redirects it there)
            print(f"SCRUB_RULE_FAILED: {rule['name']}: {exc}", file=sys.stderr)
    return compiled


# Module-level compilation so it happens once on import.
_COMPILED = _compile_rules()


def scrub(text: str) -> tuple[str, dict[str, int]]:
    """Apply all rules to *text* and return (redacted, counts_by_rule)."""
    counts: dict[str, int] = {rule["name"]: 0 for rule in RULES}
    result = text
    for rule, pat in _COMPILED:
        result, n = pat.subn(rule["replacement"], result)
        counts[rule["name"]] += n
    return result, counts


# Model output only: a 24+ char run mixing upper, lower and digits at >= 4.5
# bits/char looks random, i.e. a secret no rule knows that the model repeated.
# Hex (git SHAs, UUIDs, digests) stays under 4 bits, and `-`, `_`, `/` and `.`
# end a run, so slugs, file names, paths and module names survive. Zero hits on
# 12 MB of local assistant text, 274 curator replies included.
_RANDOM_RUN_RE = re.compile(r"(?<![A-Za-z0-9+])[A-Za-z0-9+]{24,}={0,2}")


def _looks_random(s: str) -> bool:
    if not (re.search(r"[a-z]", s) and re.search(r"[A-Z]", s) and re.search(r"\d", s)):
        return False
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values()) >= 4.5


def scrub_output(text: str) -> str:
    """scrub(), then redact random-looking runs; for model output only."""
    return _RANDOM_RUN_RE.sub(
        lambda m: "<redacted:high_entropy>" if _looks_random(m[0]) else m[0],
        scrub(text)[0],
    )
