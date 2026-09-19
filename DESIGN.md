# sessionreel — design

## Problem

A coding agent can work for two hours and leave behind a 30 MB JSONL log. The work is real, but
nobody else can see it: a teammate will not scrub a transcript, a client will not open a replay
viewer, and a link on X is not a video. The existing tools (claude-devtools, claude-code-log,
claude-replay, mindwalk, zoetrope) are *viewers* — the audience has to come to them and spend
minutes. None of them produces the one artifact people actually share: a short video that plays
inline and tells what happened.

## Goal

`sessionreel` turns one agent session into a 30–60 second video that is

1. **true** — every frame is derived from the log (the real prompt, the real diff, the real
   test output); nothing is invented, including by an LLM;
2. **interesting** — it tells the story (goal → the failure → the fix → green → shipped), not a
   random sample of 400 tool calls;
3. **safe to post** — secrets, tokens, emails and home paths are redacted before anything is
   drawn, and the report says what was removed;
4. **free and local** — no API key, no upload, no Node/Chromium; one `uvx` command.

Non-goals for v1: live capture, Codex/Cursor logs (adapter interface is in place; Codex is next),
music, voices other than the OS voice.

## Pipeline

```
session.jsonl ──ingest──▶ Session(events) ──redact──▶ Session' ──story──▶ Storyboard ──render──▶ mp4
                                                                   ▲
                                              optional: captions rewritten by the host agent
```

Every stage is a pure function with a JSON boundary, so `plan` and `render` can run separately
and a user (or the agent in plugin mode) can edit `storyboard.json` in between.

### ingest (`ingest/claude.py`)

Claude Code writes one JSON object per line. We keep only the main thread
(`isSidechain == false`) and normalise to five event kinds:

| event | source |
|---|---|
| `Prompt(text)` | `type=user`, string content, not a command/caveat/system-reminder wrapper |
| `Say(text)` | assistant `text` block |
| `Tool(name, input, output, error, patch)` | assistant `tool_use` joined to the next `tool_result` by id; `patch` from `toolUseResult.structuredPatch` (Edit/Write/MultiEdit) |
| `Usage(in, out, cache)` | assistant `message.usage` |
| timestamps | every entry's `timestamp` |

Malformed lines are skipped and counted, never fatal: logs are written live and may be truncated.

### redact (`redact.py`)

Runs on the normalised session, before the storyboard exists, so no later stage can leak.
Patterns: provider keys (`sk-…`, `sk-ant-…`, `ghp_/gho_/github_pat_`, `AKIA…`, `xox[abpr]-`,
`AIza…`), JWTs, `Bearer …`, `KEY=value` where KEY names a secret, URL credentials and token query
params, e-mail addresses, and the user's home directory (→ `~`). Contents of `.env*`, `*.pem`,
`id_rsa*` files are never shown. User-supplied `--redact REGEX` adds patterns. The count per
category is printed and stored in the storyboard; `render` refuses a storyboard whose
`redacted` flag is false.

### story (`story.py`)

Deterministic. Beats are detected, scored and packed into the time budget:

- **goal** — the first substantive prompt (the ask).
- **explore** — reads/greps/globs collapsed into one montage ("read 14 files").
- **red** — a test/build command whose output shows failure (pytest/jest/go/cargo/tsc summary
  lines, non-zero exit, `is_error`).
- **fix** — the edits between a red and the next green of the *same* command family.
- **green** — that command passing.
- **ship** — `git commit`/`git push`/`gh pr create`/publish commands that succeeded.
- **result** — the agent's final message, first sentence.
- **stats** — duration, prompts, tool calls, files changed, lines ±, tests, tokens.

The red→fix→green arc is the spine: if the session has one, the reel is built around the most
recent complete arc. Otherwise the largest edits carry the middle. Captions are templated from the
data ("3 tests failing", "fixed in `parser.py`", "12 passed"); they never claim what the log does
not show.

### captions

Default: templates (offline, zero cost). Plugin mode: the agent that did the work rewrites the
captions in `storyboard.json` — it has the context, and it runs inside the user's own session, so
no extra API key or upload exists. The renderer does not care who wrote a caption; `plan` stores
the template caption as `fact` next to it so a rewrite can be checked against the source.

### render (`render/`)

Pillow draws each frame; frames stream as raw RGB into ffmpeg (system binary, else the static
binary from `imageio-ffmpeg`) → H.264 yuv420p, CRF 20, 30 fps. Formats: `square` 1080×1080
(feeds), `wide` 1920×1080, `tall` 1080×1920. Scenes: title, prompt (typewriter), montage,
terminal (typed command, output reveal, exit badge), diff (hunks, line-by-line reveal, syntax
colour via Pygments), stats (counters), end card. Crossfades between scenes. Static layers are
drawn once per scene and cached; per-frame work is only what moves. Optional `--voice` speaks
each caption with the OS voice (`say` on macOS, `espeak-ng` on Linux) and stretches scenes to fit.

Fonts are bundled (OFL): JetBrains Mono for code, Inter for UI, Pretendard for Hangul, with
per-character fallback so a Korean prompt renders correctly.

## Interfaces

```
sessionreel                      # latest session for the current directory → reel.mp4
sessionreel list                 # recent sessions: id, when, project, prompts, tool calls
sessionreel plan [SESSION] -o storyboard.json
sessionreel render storyboard.json -o reel.mp4 [--format square|wide|tall] [--voice] [--gif]
sessionreel demo                 # bundled sample session → demo.mp4 (no logs needed)
```

Claude Code plugin: `/reel` plans, lets the agent rewrite captions from its own context, renders,
and prints the path.

## Quality bar

- Fixture sessions (synthetic, no personal data) covering: red→green arc, no tests, only
  exploration, errors without recovery, Korean prompt, secrets in commands and outputs.
- Unit tests per stage; a render smoke test that decodes the output with ffprobe (duration,
  resolution, codec) and samples frames for non-blank content.
- Redaction tests are adversarial: every pattern has a positive and a near-miss negative.
- `ruff`, CI on macOS + Ubuntu, Python 3.10–3.13.
