"""Read Claude Code session logs (~/.claude/projects/<encoded cwd>/<session id>.jsonl).

The format is undocumented and changes between Claude Code versions, so this reader is
deliberately forgiving: unknown entry types are ignored, malformed lines are counted and
skipped (a live session's last line is often half-written), and every field is read with a
default.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Event, Hunk, Session

# User-typed text that is really harness plumbing, not a human request.
_WRAPPERS = (
    "<command-name>", "<command-message>", "<local-command", "<system-reminder>",
    "<task-notification>", "<bash-input>", "<bash-stdout>", "<user-prompt-submit-hook>",
    "Caveat:", "[Request interrupted", "This session is being continued",
    "Another Claude session sent a message", "<teammate-message", "<local-command-caveat>",
)
_INJECTED = re.compile(r"<(system-reminder|local-command-caveat|command-name|command-message|command-args|local-command-stdout)>"
                       r"[\s\S]*?</\1>")
FILE_TOOLS = {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit"}
MAX_WRITE_LINES = 400


def projects_root() -> Path:
    env = os.environ.get("SESSIONREEL_PROJECTS_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
    if env and Path(env, "projects").is_dir():
        return Path(env, "projects")
    if env and Path(env).is_dir():
        return Path(env)
    return Path.home() / ".claude" / "projects"


def encode_cwd(cwd: str) -> str:
    """Claude Code names a project directory after its cwd with every non-alphanumeric → '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def session_files(root: Path | None = None, cwd: str | None = None) -> list[Path]:
    """Session logs, newest first. With `cwd`, only that project's sessions."""
    root = root or projects_root()
    if not root.is_dir():
        return []
    if cwd:
        d = root / encode_cwd(os.path.abspath(cwd))
        files = list(d.glob("*.jsonl")) if d.is_dir() else []
    else:
        files = list(root.glob("*/*.jsonl"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def find_session(ref: str, root: Path | None = None) -> Path:
    """Accept a path, a full session id, or a unique id prefix.

    The same session id can exist under two project directories (a session that changed
    directory); an exact id match picks the most recently written copy.
    """
    p = Path(ref).expanduser()
    if p.is_file():
        return p
    files = session_files(root)
    exact = [f for f in files if f.stem == ref]
    if exact:
        return exact[0]  # session_files is newest first
    hits = [f for f in files if f.stem.startswith(ref)]
    if len({f.stem for f in hits}) == 1:
        return hits[0]
    if not hits:
        raise FileNotFoundError(f"no session matches {ref!r}")
    raise FileNotFoundError(f"{ref!r} is ambiguous ({len({f.stem for f in hits})} sessions); use more characters")


def current_session(cwd: str | None = None, root: Path | None = None) -> Path | None:
    """The session the user most likely means when they name none.

    1. Inside Claude Code, CLAUDE_CODE_SESSION_ID names the running session exactly.
    2. Otherwise the newest session recorded for this directory or its nearest parent that has
       any (a command run from a subdirectory still finds the project's sessions).
    """
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        try:
            return find_session(sid, root)
        except FileNotFoundError:
            pass
    d = Path(os.path.abspath(cwd or os.getcwd()))
    for candidate in (d, *d.parents):
        files = session_files(root, str(candidate))
        if files:
            return files[0]
    return None


def _ts(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _prompt_text(entry: dict[str, Any]) -> str | None:
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    # Harness blocks ride along with a real prompt in the same message; drop them, keep the ask.
    text = _INJECTED.sub("", text).strip()
    if not text or text.startswith(_WRAPPERS):
        return None
    return text


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _count(hunks: list[Hunk]) -> tuple[int, int]:
    return (sum(1 for h in hunks for ln in h.lines if ln.startswith("+")),
            sum(1 for h in hunks for ln in h.lines if ln.startswith("-")))


def _hunks(tool: str, tool_input: dict[str, Any], result: Any) -> tuple[list[Hunk], int, int]:
    """Diff hunks for an edit plus the true +/- line counts (counted before the display cap)."""
    if isinstance(result, dict):
        patch = result.get("structuredPatch")
        if isinstance(patch, list) and patch:
            hunks = [Hunk(int(h.get("oldStart", 0)), int(h.get("newStart", 0)),
                          [str(x) for x in h.get("lines", [])]) for h in patch if isinstance(h, dict)]
            return (hunks, *_count(hunks))
    if tool == "Write":
        body = str(tool_input.get("content", ""))
        if not body:
            return [], 0, 0
        lines = body.split("\n")
        return [Hunk(0, 1, ["+" + ln for ln in lines[:MAX_WRITE_LINES]])], len(lines), 0
    if tool == "Edit" and "old_string" in tool_input:
        old = str(tool_input.get("old_string", "")).split("\n")
        new = str(tool_input.get("new_string", "")).split("\n")
        hunks = [Hunk(0, 0, ["-" + ln for ln in old] + ["+" + ln for ln in new])]
        return (hunks, *_count(hunks))
    return [], 0, 0


def load(path: str | Path) -> Session:
    path = Path(path)
    sess = Session(id=path.stem, path=str(path))
    pending: dict[str, Event] = {}  # tool_use id -> event waiting for its result
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            sess.skipped_lines += 1
            continue
        if not isinstance(entry, dict):
            sess.skipped_lines += 1
            continue
        etype = entry.get("type")
        if etype == "ai-title" and entry.get("aiTitle"):
            sess.title = str(entry["aiTitle"])
            continue
        if entry.get("isSidechain"):
            continue
        sess.cwd = sess.cwd or str(entry.get("cwd") or "")
        sess.branch = sess.branch or str(entry.get("gitBranch") or "")
        ts = _ts(entry)
        msg = entry.get("message") if isinstance(entry.get("message"), dict) else {}

        prompt = _prompt_text(entry)
        if prompt is not None:
            sess.events.append(Event("prompt", ts, text=prompt))
            continue

        if etype == "assistant":
            model = str(msg.get("model") or "")
            if model and not model.startswith("<"):
                sess.model = model
            usage = msg.get("usage") or {}
            sess.tokens_in += int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
            sess.tokens_cache += int(usage.get("cache_read_input_tokens") or 0)
            sess.tokens_out += int(usage.get("output_tokens") or 0)
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    sess.events.append(Event("say", ts, text=str(block["text"]).strip()))
                elif block.get("type") == "tool_use":
                    tin = block.get("input") if isinstance(block.get("input"), dict) else {}
                    ev = Event("tool", ts, tool=str(block.get("name", "")), input=dict(tin))
                    if ev.tool in FILE_TOOLS:
                        ev.file = str(tin.get("file_path") or tin.get("notebook_path") or "")
                    sess.events.append(ev)
                    if block.get("id"):
                        pending[str(block["id"])] = ev
            continue

        if etype == "user":
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                ev = pending.pop(str(block.get("tool_use_id", "")), None)
                if ev is None:
                    continue
                ev.output = _result_text(block)
                ev.error = bool(block.get("is_error"))
                ev.has_result = True
                if ev.tool in ("Edit", "MultiEdit", "Write", "NotebookEdit") and not ev.error:
                    ev.hunks, ev.added, ev.removed = _hunks(ev.tool, ev.input, entry.get("toolUseResult"))
    return sess
