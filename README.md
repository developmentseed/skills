# skills

A [Claude Code plugin marketplace](https://docs.anthropic.com/en/docs/claude-code/plugins) for shared AI Skills by [Development Seed](https://developmentseed.org). Skills are written in plain language, not code. They package up domain knowledge and workflows so AI tools can follow them.

## What's here

- **[github-issue-to-markdown](skills/github-issue-to-markdown/)**: exports GitHub issues (including from private repos) to structured Markdown using the `gh` CLI
- **[veda-story-creator](skills/veda-story-creator/)**: generates [VEDA](https://www.earthdata.nasa.gov/dashboard) scrollytelling MDX stories with satellite data visualizations. Includes a dataset catalog, annotated examples, and lessons learned

Know of a useful Skill that lives in another repo? See **[EXTERNAL-SKILLS.md](EXTERNAL-SKILLS.md)**.

## How to use

Skills use the SKILL.md format, which works across multiple AI tools.

### Plugin marketplace (Claude Code)

```
/plugin marketplace add developmentseed/skills
/plugin install github-issue-to-markdown@skills
```

### Manual install (any CLI tool)

```bash
# Global (available in any project)
cp -r skills/skill-name ~/.claude/skills/    # Claude Code
cp -r skills/skill-name ~/.codex/skills/     # Codex CLI
cp -r skills/skill-name ~/.gemini/skills/    # Gemini CLI

# Per-project
cp -r skills/skill-name your-project/.claude/skills/
```

### Cross-tool compatibility

| Tool | Install location | Auto-discovery |
|---|---|---|
| **Claude Code** | `~/.claude/skills/skill-name/` or `.claude/skills/` | Yes, also supports `/plugin marketplace add` |
| **OpenAI Codex CLI** | `~/.codex/skills/skill-name/` or `.codex/skills/` | Yes |
| **Gemini CLI** | `~/.gemini/skills/skill-name/` or `.gemini/skills/` | Yes |
| **Cursor** (agent mode, v2.4+) | `.cursor/skills/skill-name/` | Yes |
| **Windsurf** | `.windsurf/workflows/skill-name/` | Yes (via `/workflow-name`) |

For web-based tools (Claude.ai, ChatGPT, GitHub Copilot), upload the SKILL.md as a knowledge file or paste it into a conversation. If the skill includes scripts, run them locally first and upload the output.

## Contributing

1. Create a folder under `skills/` with a descriptive name
2. Add a `SKILL.md` file with your skill definition (see the template below)
3. Add a `.claude-plugin/plugin.json` manifest (see existing skills for examples)
4. Add your plugin entry to `.claude-plugin/marketplace.json`
5. Open a PR with a brief description of what the skill does and how you've tested it

### SKILL.md template

```markdown
---
name: your-skill-name
description: One sentence description of what this skill does and when to use it.
---

# Skill Name

What this skill does in more detail.

## When to use this

Describe the situation where someone would want this skill.

## How it works

What the skill does, step by step.

## Requirements

Any dependencies, API keys, or setup needed.
```

### Tips

- Start small, get one thing working well before adding complexity
- Be specific. The more context you give, the better the Skill works
- Test in a fresh context to make sure it works without leftover state
- Think about portability. Not everyone uses the same AI tool. If your Skill includes scripts, make sure it works when someone runs the script manually and uploads the output to a web-based tool

## Resources

- [Claude Code Skills docs](https://code.claude.com/docs/en/skills)
- [The Complete Guide to Building Skills for Claude (PDF)](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf?hsLang=en)
- [Simon Willison on Claude Skills](https://simonwillison.net/2025/Oct/16/claude-skills/)
- [Awesome Claude Skills](https://github.com/travisvn/awesome-claude-skills)

## License

MIT
