"""Unit tests for hooks/scrub.py — scrubber rules + idempotency + MULTILINE + malformed-rule skip."""

import sys
import os
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))


# ─────────────────────────── helpers ──────────────────────────────────────────


def load_fixture(name: str) -> str:
    p = pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / name
    return p.read_text()


# ─────────────────────────── basic redaction ──────────────────────────────────


class TestPrivateKey:
    def test_redacts_full_block(self):
        from scrub import scrub

        text = (
            "prefix\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "AAABBBCCC\n"
            "DDDEEEFFF\n"
            "-----END RSA PRIVATE KEY-----\n"
            "suffix"
        )
        out, counts = scrub(text)
        assert "<redacted:private_key>" in out
        assert "AAABBBCCC" not in out
        assert counts["private_key"] >= 1

    def test_redacts_ec_key(self):
        from scrub import scrub

        text = "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----"
        out, counts = scrub(text)
        assert "<redacted:private_key>" in out
        assert counts["private_key"] >= 1

    def test_cross_line_no_dotall(self):
        r"""Prove cross-line matching works via [\s\S] without re.DOTALL."""
        from scrub import scrub

        text = "a\n-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\nb"
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
                "sentinel": "<redacted:bad>",
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
                "sentinel": "<redacted:bad>",
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
