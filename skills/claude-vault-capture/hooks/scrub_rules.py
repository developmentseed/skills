r"""Pattern/replacement definitions for scrub.py.

Each rule is applied as `pattern.subn(replacement, text)` with re.MULTILINE.
Cross-line patterns use [\s\S] rather than re.DOTALL.
"""

# A bare (unquoted) value runs until whitespace, a quote, or code punctuation.
_BARE = r"[^\s\"'`,;&()\[\]{}<>$]"

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
            r"|(?:AKIA|ASIA)[0-9A-Z]{16}"
            r"|AIza[0-9A-Za-z\-_]{35}"
            # Stripe keys and webhook secrets, GitLab, Hugging Face, npm, PyPI,
            # Databricks, Google OAuth access tokens, Slack webhooks. The lookbehinds
            # keep identifiers such as hf_hub_download and npm_config_registry.
            r"|(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"
            r"|(?<![A-Za-z0-9])whsec_[A-Za-z0-9]{24,}"
            r"|(?<![A-Za-z0-9])gl(?:pat|dt|rt|ptt|soat)-[A-Za-z0-9_\-]{20,}"
            r"|(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}"
            r"|(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36,}"
            r"|(?<![A-Za-z0-9])pypi-[A-Za-z0-9_\-]{50,}"
            r"|(?<![A-Za-z0-9])dapi[0-9a-f]{32}"
            r"|(?<![A-Za-z0-9])ya29\.[A-Za-z0-9_\-]{20,}"
            r"|https://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_\-]+"
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
    {
        "name": "basic_auth",
        # `Authorization: Basic <base64>` (any quoting), and curl's -u/--user
        # user:password. The user is kept; curl -u with no password is left alone.
        "pattern": (
            r"(?P<pre>(?i:authorization[\"']?[ \t]*[:=][ \t]*[\"']?basic[ \t]+))"
            r"[A-Za-z0-9+/]+=*"
            r"|(?P<cpre>\bcurl\b[^\n]*?[ \t](?:-u|--user)(?:[ \t]+|=)[\"']?[^\s:\"']*:)"
            r"(?!<redacted:)[^\s\"']+"
        ),
        "replacement": r"\g<pre>\g<cpre><redacted:basic_auth>",
    },
    {
        "name": "kv_secret",
        # `key: value` / `key = value` / `"key": "value"` (JSON, YAML, .ini, .npmrc,
        # HTTP headers, kwargs) whose key ENDS in a secret word, any case, plus
        # env-style *_KEY. Ending, so max_tokens and token_type are not keys.
        # Quoted values are redacted unless they are a $/{ reference. Bare values
        # only when they look like a secret (4+ chars with a digit, or a 16+ letter
        # run) and not like code: type names (`token: str`), prose (`Password:
        # **required**`), attribute access (`token=self.token`), or calls and
        # subscripts (`api_key=os.environ[...]`). The digit lookahead is bounded:
        # unbounded, a long digit-free run rescanned from every key was quadratic.
        "pattern": (
            r"(?P<pre>(?<![\w.\-])(?P<q>\\?[\"']?)[\w.\-]*?"
            r"(?:(?i:password|passwd|passphrase|secret|token"
            r"|(?:api|access|secret|private|auth)[_\-]?key)|_KEY)"
            r"(?P=q)[ \t]*(?:=(?![=>])|:(?![:=]))[ \t]*)"
            r"(?P<v>\\?\"(?![${]|<redacted:)[^\"\n]+\"|'(?![${]|<redacted:)[^'\n]+'"
            r"|(?![A-Za-z_]\w*\.[A-Za-z_])"
            r"(?=" + _BARE + r"{4})"
            r"(?=" + _BARE + r"{0,256}\d|[A-Za-z+/=]{16})" + _BARE + r"++(?![(\[{]))"
        ),
        "replacement": r"\g<pre><redacted:kv_secret>",
    },
]
