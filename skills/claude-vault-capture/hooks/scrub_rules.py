r"""Pattern/replacement definitions for scrub.py.

Each rule is applied as `pattern.subn(replacement, text)` with re.MULTILINE.
Cross-line patterns use [\s\S] rather than re.DOTALL.
"""

RULES = [
    {
        "name": "private_key",
        "pattern": r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "replacement": "<redacted:private_key>",
    },
    {
        "name": "token_prefix",
        # Vendor-prefixed sk- keys (sk-proj-…, sk-or-v1-…) can contain `-` anywhere.
        # Bare sk- keys must be dash-free, so hyphenated prose ("risk-averse-approach")
        # never matches.
        "pattern": (
            r"sk-ant-[A-Za-z0-9_\-]+"
            r"|(?<![A-Za-z0-9])sk-(?:proj|svcacct|admin|or-v1|lf)-[A-Za-z0-9_\-]{16,}"
            r"|(?<![A-Za-z0-9])sk-[A-Za-z0-9_]{16,}"
            r"|github_pat_[A-Za-z0-9_]+"
            r"|gh[pousr]_[A-Za-z0-9]{36,}"  # fixed length, so "highs_and_lows" survives
            r"|xox[baprs]-[0-9]+-[A-Za-z0-9\-]+"
            r"|AKIA[0-9A-Z]{16}"
            r"|AIza[0-9A-Za-z\-_]{35}"
        ),
        "replacement": "<redacted:token_prefix>",
    },
    {
        "name": "jwt",
        "pattern": r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
        "replacement": "<redacted:jwt>",
    },
    {
        "name": "env_var",
        # Only the value is replaced; 'pre' (prefix, key, spacing) is kept.
        # Anchors at line start or after whitespace/quote/paren/colon, so
        # `export KEY=…` and `[USER]: KEY=…` match. Quoted values are consumed
        # whole; unquoted ones stop before a trailing comment and never start with
        # '=' (so `MAX_TOKENS == 3000` is a comparison, not an assignment).
        "pattern": (
            r"(?:^|(?<=[\s:;\"'`(]))"
            r"(?P<pre>(?:export[ \t]+|set[ \t]+|env[ \t]+)?"
            r"(?P<k>[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|CREDENTIAL|API)[A-Z0-9_]*)"
            r"[ \t]*=[ \t]*)"
            r"(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#=][^\s#]*)"
        ),
        "replacement": r"\g<pre><redacted:env_var>",
    },
    {
        "name": "aws_secret",
        # ~/.aws/credentials (lowercase keys, missed by env_var) and the JSON that
        # `aws sts` prints ("SecretAccessKey": "…"). Scoped (?i:…) because a
        # non-leading global (?i) is an error.
        "pattern": (
            r"(?P<pre>(?i:aws_secret_access_key|aws_session_token|secretaccesskey"
            r"|sessiontoken)\"?[ \t]*[=:][ \t]*)"
            r"(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)"
        ),
        "replacement": r"\g<pre><redacted:aws_secret>",
    },
    {
        "name": "bearer",
        # The lookahead keeps prose ("expects a Bearer token") intact.
        "pattern": (
            r"(?i)(?:authorization[:\s=]+bearer[:\s]+|bearer[:\s]+)"
            r"(?!(?:token|tokens|auth|authentication|header|scheme)\b)[A-Za-z0-9_\-\.=]+"
        ),
        "replacement": "<redacted:bearer>",
    },
    {
        "name": "basic_auth_url",
        # Any scheme (postgres://, redis://, mongodb+srv://…); the user, possibly
        # empty, is kept and the password is replaced.
        "pattern": r"([A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)[^@/\s]+(@)",
        "replacement": r"\g<1><redacted:basic_auth_url>\g<2>",
    },
]
