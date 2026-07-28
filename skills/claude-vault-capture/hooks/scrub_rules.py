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
        # sk- consumes _ and - too: modern OpenAI keys are sk-proj-…/sk-svcacct-…,
        # and a charset stopping at the first dash used to redact only the public
        # "sk-proj" prefix while the whole key body stayed in clear.
        "pattern": (
            r"sk-ant-[A-Za-z0-9_\-]+"
            r"|sk-[A-Za-z0-9_\-]{4,}"
            r"|github_pat_[A-Za-z0-9_]+"
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
        # Matches at line start OR after whitespace/quote/paren/colon — the
        # transcript renderer prefixes first lines with '[USER]: ' and shells
        # write 'export KEY=…', both of which a ^-only anchor silently missed.
        # Quoted values are consumed whole so `KEY="two words"` cannot leak
        # past the first space; the bare [^\s#]+ branch still leaves trailing
        # comments intact.
        "pattern": (
            r"(?:^|(?<=[\s:;\"'`(]))(?:export[ \t]+|set[ \t]+|env[ \t]+)?"
            r"(?P<k>[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|CREDENTIAL|API)[A-Z0-9_]*)"
            r"[ \t]*=[ \t]*(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)"
        ),
        "sentinel": "<redacted:env_var>",
        "replace_value_only": True,  # only group 'v' is replaced; 'k' is kept
    },
    {
        "name": "aws_secret",
        # ~/.aws/credentials uses lowercase keys and `=` or `:` — the env_var
        # rule requires an UPPERCASE key, so the 40-char AWS secret (the half
        # that actually grants access, unlike the AKIA id) escaped it.
        "pattern": (
            r"(?i)(?P<k>aws_secret_access_key|aws_session_token)"
            r"[ \t]*[=:][ \t]*(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)"
        ),
        "sentinel": "<redacted:aws_secret>",
        "replace_value_only": True,
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
