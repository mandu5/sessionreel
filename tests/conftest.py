"""Build synthetic Claude Code logs in the real on-disk shape, one entry at a time."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


class LogBuilder:
    def __init__(self, cwd: str = "/work/app") -> None:
        self.cwd = cwd
        self.lines: list[dict] = []
        self.t = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)

    def _base(self, kind: str, dt: float = 5, **extra) -> dict:
        self.t += timedelta(seconds=dt)
        e = {"type": kind, "isSidechain": False, "cwd": self.cwd, "gitBranch": "main",
             "sessionId": "s", "uuid": str(uuid.uuid4()), "timestamp": self.t.isoformat().replace("+00:00", "Z")}
        e.update(extra)
        return e

    def prompt(self, text, dt=5, **extra):
        self.lines.append(self._base("user", dt, message={"role": "user", "content": text}, **extra))
        return self

    def say(self, text, dt=5):
        self.lines.append(self._base("assistant", dt, message={
            "model": "claude-opus-5", "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 50}}))
        return self

    def tool(self, name, inp, output="", error=False, result=None, dt=5, sidechain=False):
        tid = "toolu_" + uuid.uuid4().hex[:12]
        a = self._base("assistant", dt, message={"model": "claude-opus-5",
                                                 "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]})
        a["isSidechain"] = sidechain
        r = self._base("user", 1, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": output, "is_error": error}]})
        r["isSidechain"] = sidechain
        if result is not None:
            r["toolUseResult"] = result
        self.lines += [a, r]
        return self

    def bash(self, command, output="", error=False, dt=5):
        return self.tool("Bash", {"command": command}, output, error, dt=dt)

    def edit(self, path, old, new, dt=5):
        lines = ["-" + x for x in old.split("\n")] + ["+" + x for x in new.split("\n")]
        return self.tool("Edit", {"file_path": path, "old_string": old, "new_string": new}, "ok",
                         result={"filePath": path, "structuredPatch": [{"oldStart": 1, "newStart": 1, "lines": lines}]}, dt=dt)

    def raw(self, text):
        self.lines.append(text)
        return self

    def write(self, path: Path) -> Path:
        path.write_text("".join((x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) + "\n" for x in self.lines))
        return path


@pytest.fixture
def log():
    return LogBuilder()


@pytest.fixture
def arc_session(tmp_path):
    """ask → explore → red → fix → green → commit → report"""
    b = LogBuilder()
    b.prompt("Fix the parser so empty lines stop crashing it, and add a test.")
    b.tool("Read", {"file_path": "/work/app/parser.py"}, "def parse(x): ...")
    b.tool("Read", {"file_path": "/work/app/tests/test_parser.py"}, "...")
    b.tool("Grep", {"pattern": "parse("}, "parser.py")
    b.bash("cd /work/app && python -m pytest -q", "F..\nFAILED tests/test_parser.py::test_empty\n1 failed, 2 passed in 0.1s", error=True)
    b.edit("/work/app/parser.py", "    return line.split(',')", "    if not line.strip():\n        return []\n    return line.split(',')")
    b.bash("cd /work/app && python -m pytest -q", "...\n3 passed in 0.1s")
    b.bash("git commit -m 'parser: skip empty lines'", "")
    b.say("Fixed: empty lines now return an empty row. All 3 tests pass.")
    return b.write(tmp_path / "arc.jsonl")
