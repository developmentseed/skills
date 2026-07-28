"""Unit tests for hooks/scrub.py — scrubber rules + idempotency + MULTILINE + malformed-rule skip."""

import os
import pathlib


# ─────────────────────────── helpers ──────────────────────────────────────────


# PEM markers are assembled at runtime, never stored verbatim (in fixtures OR
# this file): GitHub push protection and gitleaks match the BEGIN/END lines
# themselves, fake body or not, so a real-format block at rest would flag this
# repo and every clone of it.
def _pem(kind: str, body: str) -> str:
    marker = "-----{edge} " + kind + " KEY-----"
    return (
        marker.format(edge="BEGIN") + "\n" + body + "\n" + marker.format(edge="END")
    )


def load_fixture(name: str) -> str:
    p = pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / name
    text = p.read_text()
    return text.replace(
        "@@PEM_BEGIN@@\nFAKE_PRIVATE_KEY_BODY\n@@PEM_END@@",
        _pem("RSA PRIVATE", "FAKE_PRIVATE_KEY_BODY"),
    )


# ─────────────────────────── basic redaction ──────────────────────────────────


class TestPrivateKey:
    def test_redacts_full_block(self):
        from scrub import scrub

        text = "prefix\n" + _pem("RSA PRIVATE", "AAABBBCCC\nDDDEEEFFF") + "\nsuffix"
        out, counts = scrub(text)
        assert "<redacted:private_key>" in out
        assert "AAABBBCCC" not in out
        assert counts["private_key"] >= 1

    def test_redacts_ec_key(self):
        from scrub import scrub

        text = _pem("EC PRIVATE", "ABC")
        out, counts = scrub(text)
        assert "<redacted:private_key>" in out
        assert counts["private_key"] >= 1

    def test_cross_line_no_dotall(self):
        r"""Prove cross-line matching works via [\s\S] without re.DOTALL."""
        from scrub import scrub

        text = "a\n" + _pem("PRIVATE", "SECRET") + "\nb"
        out, _ = scrub(text)
        assert "SECRET" not in out


class TestTokenPrefixes:
    def test_anthropic_key(self):
        from scrub import scrub

        out, counts = scrub("key is sk-ant-api03-aBcDeFgHiJkLmNoPqRsT")
        assert "sk-ant-api03" not in out
        assert "<redacted:token_prefix>" in out
        assert counts["token_prefix"] >= 1

    def test_openai_key(self):
        from scrub import scrub

        out, counts = scrub("sk-abcdefghij1234567890")
        assert "sk-abcde" not in out
        assert counts["token_prefix"] >= 1

    def test_github_pat(self):
        from scrub import scrub

        out, counts = scrub("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh")
        assert "ghp_" not in out
        assert counts["token_prefix"] >= 1

    def test_slack_token(self):
        from scrub import scrub

        out, counts = scrub("token: xoxb-123456-abcdefghijk")
        assert "xoxb-" not in out
        assert counts["token_prefix"] >= 1

    def test_aws_key(self):
        from scrub import scrub

        out, counts = scrub("AKIAIOSFODNN7EXAMPLE")
        assert "AKIA" not in out
        assert counts["token_prefix"] >= 1


class TestJWT:
    def test_redacts_jwt(self):
        from scrub import scrub

        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        out, counts = scrub(jwt)
        assert jwt not in out
        assert "<redacted:jwt>" in out
        assert counts["jwt"] >= 1

    def test_non_jwt_untouched(self):
        from scrub import scrub

        text = "eyJnot.aJWT"
        out, _ = scrub(text)
        # should not match incomplete JWT (missing third segment)
        assert out == text


class TestEnvVar:
    def test_api_key_assignment(self):
        from scrub import scrub

        text = "ANTHROPIC_API_KEY=sk-ant-abc123"
        out, counts = scrub(text)
        assert "sk-ant-abc123" not in out
        assert "<redacted:env_var>" in out
        assert counts["env_var"] >= 1

    def test_key_name_preserved(self):
        from scrub import scrub

        text = "SECRET_TOKEN=super_secret_value"
        out, counts = scrub(text)
        assert "SECRET_TOKEN" in out  # key is preserved
        assert "super_secret_value" not in out

    def test_value_inside_key_preserves_key(self):
        """The replacement is a regex template, so the pre-value span is
        written back verbatim even when the value string reoccurs inside it.
        Deliberate divergence from the pre-template group(0).replace behavior,
        which mangled the key on inputs like this."""
        from scrub import scrub

        out, counts = scrub("PASSKEY=PASS")
        assert out == "PASSKEY=<redacted:env_var>"
        assert counts["env_var"] == 1

    def test_trailing_comment_not_captured(self):
        from scrub import scrub

        text = "API_KEY=xyz # prod comment"
        out, _ = scrub(text)
        assert "# prod comment" in out
        assert "xyz" not in out

    def test_lowercase_not_matched(self):
        from scrub import scrub

        text = "api_key=should_not_match"
        out, counts = scrub(text)
        assert out == text
        assert counts["env_var"] == 0

    def test_multiline_mid_transcript(self):
        """MULTILINE coverage: .env assignment on line 50 must be redacted."""
        from scrub import scrub

        lines = ["line {}\n".format(i) for i in range(50)]
        lines.append("DATABASE_PASSWORD=s3cr3t\n")
        lines.append("end\n")
        text = "".join(lines)
        out, counts = scrub(text)
        assert "s3cr3t" not in out
        assert counts["env_var"] >= 1


class TestEnvVarBeyondLineStart:
    """The ^-anchored rule missed exactly the forms transcripts contain most."""

    def test_export_prefix(self):
        from scrub import scrub

        out, counts = scrub("export DATABASE_PASSWORD=hunter2secret")
        assert "hunter2secret" not in out
        assert "export DATABASE_PASSWORD" in out  # prefix and key kept
        assert counts["env_var"] >= 1

    def test_transcript_first_line_role_prefix(self):
        from scrub import scrub

        # curate.py renders each message's first line as '[USER]: <content>'
        out, counts = scrub("[USER]: ANTHROPIC_API_KEY=my-plain-key-value")
        assert "my-plain-key-value" not in out
        assert counts["env_var"] >= 1

    def test_quoted_value_fully_consumed(self):
        from scrub import scrub

        out, _ = scrub('API_KEY="my secret value"')
        assert "my secret value" not in out
        assert "secret value" not in out  # nothing leaks past the first space

    def test_single_quoted_value(self):
        from scrub import scrub

        out, _ = scrub("DB_PASSWORD='p a s s'")
        assert "p a s s" not in out

    def test_lowercase_still_not_matched(self):
        from scrub import scrub

        out, counts = scrub("api_key=should_not_match")
        assert out == "api_key=should_not_match"
        assert counts["env_var"] == 0


class TestModernTokenFormats:
    def test_openai_project_key_fully_redacted(self):
        from scrub import scrub

        out, _ = scrub("key: sk-proj-Ab12Cd34_Ef56Gh78Ij90Kl12Mn34Op56")
        assert "Ab12Cd34" not in out  # body must not survive the prefix

    def test_openai_service_account_key(self):
        from scrub import scrub

        out, _ = scrub("sk-svcacct-XyZ987_abcDEF654ghiJKL321")
        assert "XyZ987" not in out

    def test_fine_grained_github_pat(self):
        from scrub import scrub

        out, counts = scrub("github_pat_11ABCDEFG0_abcdefghijklmnopqrstuv")
        assert "github_pat_11ABCDEFG0" not in out
        assert counts["token_prefix"] >= 1


class TestAwsSecret:
    def test_credentials_file_form(self):
        from scrub import scrub

        out, counts = scrub(
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYFAKEFAKE40"
        )
        assert "wJalrXUtnFEMI" not in out
        assert "aws_secret_access_key" in out  # key kept for context
        assert counts["aws_secret"] >= 1

    def test_session_token_and_colon_separator(self):
        from scrub import scrub

        out, _ = scrub("AWS_SESSION_TOKEN: FwoGZXIvYXdzEFAKEFAKEtoken")
        assert "FwoGZXIvYXdzE" not in out


class TestBearerToken:
    def test_authorization_header(self):
        from scrub import scrub

        text = "Authorization: Bearer mytoken123"
        out, counts = scrub(text)
        assert "mytoken123" not in out
        assert "<redacted:bearer>" in out
        assert counts["bearer"] >= 1

    def test_lowercase_bearer(self):
        from scrub import scrub

        text = "bearer xyz123"
        out, counts = scrub(text)
        assert "xyz123" not in out
        assert counts["bearer"] >= 1

    def test_curl_header(self):
        from scrub import scrub

        text = "-H 'Authorization: Bearer myAPItoken'"
        out, counts = scrub(text)
        assert "myAPItoken" not in out
        assert counts["bearer"] >= 1


class TestBasicAuth:
    def test_url_basic_auth(self):
        from scrub import scrub

        text = "https://user:password123@example.com/path"
        out, counts = scrub(text)
        assert "password123" not in out
        assert "<redacted:basic_auth_url>" in out
        assert counts["basic_auth_url"] >= 1

    def test_user_kept(self):
        from scrub import scrub

        text = "https://alice:secret@host.com/"
        out, _ = scrub(text)
        assert "alice" in out


class TestIdempotency:
    def test_scrub_is_idempotent(self):
        from scrub import scrub

        text = (
            "ANTHROPIC_API_KEY=sk-ant-abc\n"
            "Authorization: Bearer tok123\n"
            "https://user:pass@example.com/\n"
        )
        once, _ = scrub(text)
        twice, _ = scrub(once)
        assert once == twice

    def test_non_secret_untouched(self):
        from scrub import scrub

        text = "Hello world, this is a normal sentence."
        out, counts = scrub(text)
        assert out == text
        assert all(v == 0 for v in counts.values())


class TestWithSecretsFixture:
    def test_all_secrets_redacted(self):
        from scrub import scrub

        text = load_fixture("with-secrets.txt")
        out, counts = scrub(text)
        # None of the planted secret values should appear in output
        assert "FAKE_API_KEY_VALUE" not in out
        assert "FAKE_BEARER_VALUE" not in out
        assert "FAKE_URL_PASSWORD" not in out
        assert "FAKE_PRIVATE_KEY_BODY" not in out
        # JWT encoded payload should be gone
        assert "eyJzdWIiOiJGQUtFX0pXVF9UT0tFTl9WQUxVRSJ9" not in out


class TestMalformedRule:
    def test_bad_regex_skipped_no_exception(self, tmp_path):
        """A malformed pattern is skipped; scrub returns original text; no propagation."""
        import scrub_rules
        import scrub as scrub_mod
        import importlib

        # Set the failures path BEFORE reloading: reload re-runs scrub.py's
        # module-level _compile_rules(), which logs the bad rule on import. If
        # the env override isn't set yet, that log leaks to the real
        # eval/state/scrub-failures.md instead of tmp_path.
        os.environ["SCRUB_FAILURES_PATH"] = str(tmp_path / "scrub-failures.md")

        original_rules = scrub_rules.RULES[:]
        scrub_rules.RULES.insert(
            0,
            {
                "name": "bad_rule",
                "pattern": r"(?P<bad>[",  # invalid regex
                "replacement": "<redacted:bad>",
            },
        )
        importlib.reload(scrub_mod)

        try:
            text = "some normal text"
            out, counts = scrub_mod.scrub(text)
            assert (
                out == text
            )  # original returned for bad rule portion; rest still runs
        finally:
            scrub_rules.RULES[:] = original_rules
            importlib.reload(scrub_mod)
            os.environ.pop("SCRUB_FAILURES_PATH", None)

    def test_bad_template_skipped_no_exception(self, tmp_path):
        """A rule whose PATTERN compiles but whose replacement template is
        invalid must be skipped at compile time, not abort every scrub call:
        templates are parsed eagerly on each subn, even with zero matches."""
        import scrub_rules
        import scrub as scrub_mod
        import importlib

        failures_file = tmp_path / "scrub-failures.md"
        os.environ["SCRUB_FAILURES_PATH"] = str(failures_file)

        original_rules = scrub_rules.RULES[:]
        scrub_rules.RULES.insert(
            0,
            {
                "name": "bad_template",
                "pattern": r"(x)",
                "replacement": r"\g<nosuchgroup>",
            },
        )
        importlib.reload(scrub_mod)
        try:
            out, counts = scrub_mod.scrub("sk-ant-abc123 and x")
            assert "sk-ant-abc123" not in out  # other rules still ran
            assert "bad_template" in failures_file.read_text()
        finally:
            scrub_rules.RULES[:] = original_rules
            importlib.reload(scrub_mod)
            os.environ.pop("SCRUB_FAILURES_PATH", None)

    def test_bad_regex_writes_failure_log(self, tmp_path):
        """A failed rule must append to scrub-failures.md."""
        import scrub_rules
        import scrub as scrub_mod
        import importlib

        failures_file = tmp_path / "scrub-failures.md"
        os.environ["SCRUB_FAILURES_PATH"] = str(failures_file)

        original_rules = scrub_rules.RULES[:]
        scrub_rules.RULES.insert(
            0,
            {
                "name": "bad_rule_log",
                "pattern": r"[unclosed",
                "replacement": "<redacted:bad>",
            },
        )
        importlib.reload(scrub_mod)
        try:
            scrub_mod.scrub("text")
            assert failures_file.exists()
            content = failures_file.read_text()
            assert "bad_rule_log" in content
        finally:
            scrub_rules.RULES[:] = original_rules
            importlib.reload(scrub_mod)
            os.environ.pop("SCRUB_FAILURES_PATH", None)
