r"""Pattern/replacement definitions for scrub.py.

Each rule is applied as one `pattern.subn(replacement, text)` — the replacement
is a regex template, so what gets written is readable right here in the table.
All patterns are compiled with re.MULTILINE so ^ and $ match every line.
Cross-line patterns use [\s\S] explicitly — not re.DOTALL — so future flag
changes cannot silently regress them.
"""

RULES = [
    {
        "name": "private_key",
        "pattern": r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "replacement": "<redacted:private_key>",
    },
    {
        "name": "token_prefix",
        # sk- must reach past the vendor segment: modern OpenAI keys are
        # sk-proj-…/sk-svcacct-…, and a charset stopping at the first dash used to
        # redact only the public "sk-proj" prefix while the key body stayed in
        # clear. It does NOT take `-` in the body, and it requires a word boundary
        # plus a 16-char body, because a greedy `sk-[A-Za-z0-9_\-]{4,}` matches
        # inside ordinary hyphenated prose — "risk-averse-approach" became
        # "ri<redacted>" — which silently mangles the archived note.
        "pattern": (
            r"sk-ant-[A-Za-z0-9_\-]+"
            r"|(?<![A-Za-z0-9])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_]{16,}"
            r"|github_pat_[A-Za-z0-9_]+"
            r"|gh[pousr]_[A-Za-z0-9]+"
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
        # Only the value is replaced; the whole pre-value span (group 'pre') is
        # written back verbatim, so key name and spacing survive.
        # Matches at line start OR after whitespace/quote/paren/colon — the
        # transcript renderer prefixes first lines with '[USER]: ' and shells
        # write 'export KEY=…', both of which a ^-only anchor silently missed.
        # Both alternatives are zero-width, so 'pre' still spans the whole match
        # up to the value. Quoted values are consumed whole so `KEY="two words"`
        # cannot leak past the first space; the bare [^\s#]+ branch still leaves
        # trailing comments intact.
        "pattern": (
            r"(?:^|(?<=[\s:;\"'`(]))"
            r"(?P<pre>(?:export[ \t]+|set[ \t]+|env[ \t]+)?"
            # No mandatory leading [A-Z]: with one, the keyword could never start
            # at offset 0 of the name, so the commonest bare forms — PASSWORD=,
            # TOKEN=, SECRET=, PASS= — were never redacted at all.
            r"(?P<k>[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD|CREDENTIAL|API)[A-Z0-9_]*)"
            r"[ \t]*=[ \t]*)"
            r"(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)"
        ),
        "replacement": r"\g<pre><redacted:env_var>",
    },
    {
        "name": "aws_secret",
        # ~/.aws/credentials uses lowercase keys and `=` or `:` — the env_var
        # rule requires an UPPERCASE key, so the 40-char AWS secret (the half
        # that actually grants access, unlike the AKIA id) escaped it.
        # (?i:…) is scoped, not global: a bare (?i) anywhere but position 0 is a
        # hard error in modern Python, and 'pre' has to come first here.
        "pattern": (
            r"(?P<pre>(?i:aws_secret_access_key|aws_session_token)[ \t]*[=:][ \t]*)"
            r"(?P<v>\"[^\"\n]*\"|'[^'\n]*'|[^\s#]+)"
        ),
        "replacement": r"\g<pre><redacted:aws_secret>",
    },
    {
        "name": "bearer",
        "pattern": r"(?i)(?:authorization[:\s=]+bearer[:\s]+|bearer[:\s]+)[A-Za-z0-9_\-\.=]+",
        "replacement": "<redacted:bearer>",
    },
    {
        "name": "basic_auth_url",
        # User is kept; password (after ':') is replaced.
        "pattern": r"(https?://[^:/\s]+:)[^@/\s]+(@)",
        "replacement": r"\g<1><redacted:basic_auth_url>\g<2>",
    },
]
