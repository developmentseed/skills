"""neutralize_remote_embeds: the note must not make Obsidian fetch a URL that
transcript content chose. Remote images become links; local embeds stay."""

import pytest

import curate


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "![chart](https://x.example/p.png?q=s3cret)",
            "[chart](https://x.example/p.png?q=s3cret)",
        ),
        ("![](http://x.example/a.gif)", "[](http://x.example/a.gif)"),
        ("![a]( <https://x.example/a b.png>)", "[a]( <https://x.example/a b.png>)"),
        ("![a](//x.example/a.png)", "[a](//x.example/a.png)"),
        (
            "![a][ref]\n\n[ref]: https://x.example/a.png",
            "[a][ref]\n\n[ref]: https://x.example/a.png",
        ),
        ("![shortcut]", "[shortcut]"),
        (
            '<img src="https://x.example/a.png">',
            '&lt;img src="https://x.example/a.png">',
        ),
        ("<IMG/src=https://x.example/a.png>", "&lt;IMG/src=https://x.example/a.png>"),
        (
            '<iframe src="https://x.example"></iframe>',
            '&lt;iframe src="https://x.example">&lt;/iframe>',
        ),
        (
            "<video><source src=https://x.example/v.mp4></video>",
            "&lt;video>&lt;source src=https://x.example/v.mp4>&lt;/video>",
        ),
        (
            "<audio src=a>, <embed src=a>, <object data=a>",
            "&lt;audio src=a>, &lt;embed src=a>, &lt;object data=a>",
        ),
    ],
)
def test_remote_embeds_are_neutralized(text, expected):
    assert curate.neutralize_remote_embeds(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "![[diagram.png]]",
        "![[Some note#Heading]]",
        "![arch](attachments/arch.png)",
        "![arch](</abs path/arch.png>)",
        "[a link](https://x.example), not an embed",
        "if a < b and Vec<u8> and <details> and <imgur>",
        "Wow! [x](https://x.example)",
    ],
)
def test_local_embeds_links_and_code_survive(text):
    assert curate.neutralize_remote_embeds(text) == text


def test_is_idempotent():
    once = curate.neutralize_remote_embeds(
        '![a](https://x.example/a.png) <img src="x">'
    )
    assert curate.neutralize_remote_embeds(once) == once


def test_written_note_has_no_remote_embed(tmp_path):
    """Title, body and source links are all model output."""
    note = tmp_path / "n.md"
    curate._write_artifact(
        note,
        title="Gotcha <img src=https://x.example/t.png>",
        fm_type="gotcha",
        project="p",
        tags=[],
        source="claude-code-curated",
        session_id="s",
        created="2026-10-15",
        model="m",
        cost_usd=None,
        redactions={},
        body="See ![beacon](https://x.example/b.png) and ![[local.png]].",
        source_links=["![](https://x.example/s.png)"],
    )
    # Frontmatter is JSON-quoted YAML, which Obsidian shows as text.
    _, frontmatter, rendered = note.read_text().split("---\n", 2)
    assert "<img" in frontmatter
    assert "![beacon]" not in rendered
    assert "![](" not in rendered
    assert "<img" not in rendered
    assert "![[local.png]]" in rendered
