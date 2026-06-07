r"""Pattern/sentinel definitions for scrub.py.

All patterns are compiled with re.MULTILINE so ^ and $ match every line.
Cross-line patterns use [\s\S] explicitly — not re.DOTALL — so future flag
changes cannot silently regress them.
"""

RULES = [
    {
        "name": "private_key",
        "pattern": r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "sentinel": "<redacted:private_key>",
    },
    {
        "name": "token_prefix",
        "pattern": (
            r"sk-ant-[A-Za-z0-9_\-]+"
            r"|sk-[A-Za-z0-9]+"
            r"|gh[pousr]_[A-Za-z0-9]+"
            r"|xox[baprs]-[0-9]+-[A-Za-z0-9\-]+"
            r"|AKIA[0-9A-Z]{16}"
            r"|AIza[0-9A-Za-z\-_]{35}"
        ),
        "sentinel": "<redacted:token_prefix>",
    },
    {
        "name": "jwt",
        "pattern": r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
        "sentinel": "<redacted:jwt>",
    },
    {
        "name": "env_var",
        # Only the value is replaced; key name is kept for context.
        # [^\s#]+ means trailing comments survive intact.
        # ^ anchored per-line via re.MULTILINE.
        "pattern": (
            r"^[ \t]*(?P<k>[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|CREDENTIAL|API)[A-Z0-9_]*)"
            r"[ \t]*=[ \t]*(?P<v>[^\s#]+)"
        ),
        "sentinel": "<redacted:env_var>",
        "replace_value_only": True,  # only group 'v' is replaced; 'k' is kept
    },
    {
        "name": "bearer",
        "pattern": r"(?i)(?:authorization[:\s=]+bearer[:\s]+|bearer[:\s]+)[A-Za-z0-9_\-\.=]+",
        "sentinel": "<redacted:bearer>",
    },
    {
        "name": "basic_auth_url",
        # User is kept; password (after ':') is replaced.
        "pattern": r"(https?://[^:/\s]+:)[^@/\s]+(@)",
        "sentinel": "<redacted:basic_auth_url>",
        "replace_group": True,  # group(1) + sentinel + group(2)
    },
]
