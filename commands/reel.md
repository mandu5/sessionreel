---
description: Turn this session into a 30-60 second recap video (local, redacted, no API key)
argument-hint: "[--lang en|ko] [--whole] [--project NAME] [--no-branch] [--format square|wide|tall] [--voice] [--gif]"
allowed-tools:
  - Bash
  - Read
  - Write
---

Make a recap video of this session by following [`skills/sessionreel/SKILL.md`](../skills/sessionreel/SKILL.md). That file is the source of truth; do not reimplement its steps here.

Arguments: `$ARGUMENTS` — pass `--lang`, `--whole`, `--project`, `--no-branch`, `--redact` to `plan`, and `--format`, `--voice`, `--gif` to `render`.
