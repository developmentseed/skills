"""Unit tests for frontmatter + filename (slug + sid8) + title sanitization."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))

import yaml
from curate import (
    sanitize_title,
    sanitize_summary,
    make_slug,
    make_filename,
    render_frontmatter,
)


class TestSanitizeTitle:
    def test_strips_pipe(self):
        assert "|" not in sanitize_title("foo|bar")

    def test_strips_closing_wikilink(self):
        assert "]]" not in sanitize_title("foo]]bar")

    def test_strips_opening_wikilink(self):
        assert "[[" not in sanitize_title("foo[[bar")

    def test_strips_hash(self):
        assert "#" not in sanitize_title("foo # bar")

    def test_strips_backtick(self):
        assert "`" not in sanitize_title("foo `code` bar")

    def test_strips_control_chars(self):
        assert "\x00" not in sanitize_title("foo\x00bar")
        assert "\n" not in sanitize_title("foo\nbar")
        assert "\t" not in sanitize_title("foo\tbar")

    def test_collapses_internal_whitespace(self):
        result = sanitize_title("foo   bar   baz")
        assert "  " not in result

    def test_strips_leading_trailing_whitespace(self):
        result = sanitize_title("  hello world  ")
        assert result == result.strip()

    def test_truncates_to_120(self):
        long_title = "a" * 200
        assert len(sanitize_title(long_title)) <= 120

    def test_normal_title_unchanged(self):
        t = "Deploy postgres connection pooling on prod"
        assert sanitize_title(t) == t


class TestMakeSlug:
    def test_lowercases(self):
        assert make_slug("Hello World") == "hello-world"

    def test_strips_non_ascii(self):
        slug = make_slug("café résumé")
        assert slug.isascii()

    def test_replaces_spaces_with_dash(self):
        assert make_slug("foo bar baz") == "foo-bar-baz"

    def test_collapses_multiple_dashes(self):
        assert "--" not in make_slug("foo   bar")

    def test_strips_leading_trailing_dashes(self):
        slug = make_slug("  -foo- ")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_truncates_to_60(self):
        long_title = "word " * 20
        assert len(make_slug(long_title)) <= 60

    def test_truncates_at_dash_boundary(self):
        # 60 chars, but last char is in middle of a word — should not end mid-word
        slug = make_slug("abcde " * 12)  # "abcde-abcde-..."
        assert not slug.endswith("-")

    def test_empty_title_fallback(self):
        assert make_slug("###|||") == "untitled"
        assert make_slug("") == "untitled"

    def test_deterministic(self):
        assert make_slug("Decision: use PostgreSQL") == make_slug(
            "Decision: use PostgreSQL"
        )


class TestMakeFilename:
    def test_format(self):
        fname = make_filename("2026-04-23", "my-slug", "abcd1234efgh")
        assert fname == "2026-04-23-my-slug-abcd1234.md"

    def test_sid8_is_first_8(self):
        fname = make_filename("2026-04-23", "slug", "0123456789abcdef")
        assert fname.endswith("-01234567.md")


class TestRenderFrontmatter:
    def test_required_fields_present(self):
        fm = render_frontmatter(
            title="Test Title",
            fm_type="decision",
            project="my-project",
            tags=["claude-code", "backend"],
            source="claude-code-curated",
            session_id="abc-123",
            created="2026-04-23",
            model="claude-sonnet-4-6",
            cost_usd=0.0123,
            redactions={"env_var": 0, "jwt": 1},
        )
        assert "title:" in fm
        assert "type:" in fm
        assert "project:" in fm
        assert "tags:" in fm
        assert "source:" in fm
        assert "session_id:" in fm
        assert "created:" in fm
        assert "model:" in fm
        assert "cost_usd:" in fm
        assert "redactions:" in fm

    def test_title_is_sanitized_value(self):
        fm = render_frontmatter(
            title="foo|bar",
            fm_type="decision",
            project="p",
            tags=[],
            source="claude-code-curated",
            session_id="s",
            created="2026-04-23",
            model="m",
            cost_usd=0.0,
            redactions={},
        )
        assert "|" not in fm

    def test_starts_and_ends_with_dashes(self):
        fm = render_frontmatter(
            title="T",
            fm_type="decision",
            project="p",
            tags=[],
            source="s",
            session_id="s",
            created="2026-04-23",
            model="m",
            cost_usd=0.0,
            redactions={},
        )
        assert fm.startswith("---")
        assert "---\n" in fm[3:]  # closing delimiter present


class TestSanitizeSummary:
    def test_strips_pipe(self):
        assert "|" not in sanitize_summary("foo|bar")

    def test_strips_closing_wikilink(self):
        assert "]]" not in sanitize_summary("foo]]bar")

    def test_strips_opening_wikilink(self):
        assert "[[" not in sanitize_summary("foo[[bar")

    def test_strips_hash(self):
        assert "#" not in sanitize_summary("foo # bar")

    def test_strips_backtick(self):
        assert "`" not in sanitize_summary("foo `code` bar")

    def test_strips_control_chars(self):
        assert "\x00" not in sanitize_summary("foo\x00bar")
        assert "\n" not in sanitize_summary("foo\nbar")
        assert "\t" not in sanitize_summary("foo\tbar")

    def test_collapses_internal_whitespace(self):
        result = sanitize_summary("foo   bar   baz")
        assert "  " not in result

    def test_strips_leading_trailing_whitespace(self):
        result = sanitize_summary("  hello world  ")
        assert result == result.strip()

    def test_truncates_to_140(self):
        long_summary = "a" * 200
        assert len(sanitize_summary(long_summary)) <= 140

    def test_normal_summary_unchanged(self):
        s = "Adds sanitize_summary helper with a 140-character cap for vault-save frontmatter"
        assert sanitize_summary(s) == s

    def test_deterministic(self):
        s = "Refactor vault-save to write to claude-docs/ with summary and description"
        assert sanitize_summary(s) == sanitize_summary(s)


class TestDescriptionYaml:
    def test_multiline_description_roundtrip(self):
        description = "First paragraph of the description.\n\nSecond paragraph with more detail.\n\nThird paragraph concluding the description."
        indented = "\n".join(
            f"  {line}" if line else "" for line in description.split("\n")
        )
        yaml_body = f"title: Test\ndescription: |\n{indented}\n"
        parsed = yaml.safe_load(yaml_body)
        assert parsed["description"].strip() == description.strip()

    def test_description_no_triple_dash(self):
        description = "This description should not contain a triple dash line that would break YAML."
        indented = "\n".join(f"  {line}" for line in description.split("\n"))
        yaml_body = f"title: Test\ndescription: |\n{indented}\n"
        parsed = yaml.safe_load(yaml_body)
        assert "---" not in parsed["description"]
