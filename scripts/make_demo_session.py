"""Write the bundled demo session: a synthetic Claude Code log in the real on-disk format.

Nothing here comes from a real person's session. Re-run after changing the story:
    python scripts/make_demo_session.py
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/sessionreel/demo/demo-session.jsonl"
CWD = "/home/dev/slugkit"
SID = "5e55a0d0-de40-4c1e-9d3e-000000000001"
T0 = datetime(2026, 9, 18, 14, 2, 11, tzinfo=timezone.utc)

OLD_SLUG = '''import re


def slugify(title: str) -> str:
    """Lowercase, keep a-z0-9, join words with '-'."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return "-".join(words)
'''
NEW_SLUG = '''import re
import unicodedata


def slugify(title: str, max_len: int = 80) -> str:
    """ASCII slug: strip accents, drop symbols and emoji, join words with '-'."""
    text = unicodedata.normalize("NFKD", title)
    text = text.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words)[:max_len].rstrip("-")
'''

lines: list[dict] = []
clock = [T0]
parent = [None]


def tick(seconds: float) -> str:
    clock[0] += timedelta(seconds=seconds)
    return clock[0].isoformat().replace("+00:00", "Z")


def base(kind: str, dt: float) -> dict:
    u = str(uuid.uuid4())
    e = {"parentUuid": parent[0], "isSidechain": False, "userType": "external", "cwd": CWD,
         "sessionId": SID, "version": "2.1.270", "gitBranch": "fix/unicode-slugs", "type": kind,
         "uuid": u, "timestamp": tick(dt)}
    parent[0] = u
    return e


def prompt(text: str, dt: float = 2) -> None:
    e = base("user", dt)
    e["message"] = {"role": "user", "content": text}
    lines.append(e)


def say(text: str, dt: float = 4) -> None:
    e = base("assistant", dt)
    e["message"] = {"model": "claude-opus-5", "role": "assistant", "type": "message",
                    "content": [{"type": "text", "text": text}],
                    "usage": {"input_tokens": 6, "cache_creation_input_tokens": 2100,
                              "cache_read_input_tokens": 31000, "output_tokens": 180}}
    lines.append(e)


def tool(name: str, inp: dict, output: str, dt: float = 5, error: bool = False, result: dict | None = None) -> None:
    tid = "toolu_" + uuid.uuid4().hex[:24]
    e = base("assistant", dt)
    e["message"] = {"model": "claude-opus-5", "role": "assistant", "type": "message",
                    "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}],
                    "usage": {"input_tokens": 4, "cache_creation_input_tokens": 900,
                              "cache_read_input_tokens": 33000, "output_tokens": 220}}
    lines.append(e)
    r = base("user", 2)
    r["message"] = {"role": "user", "content": [{"tool_use_id": tid, "type": "tool_result",
                                                  "content": output, "is_error": error}]}
    if result is not None:
        r["toolUseResult"] = result
    lines.append(r)


def patch(old: str, new: str) -> list[dict]:
    import difflib
    a, b = old.split("\n"), new.split("\n")
    out = []
    for grp in difflib.SequenceMatcher(None, a, b).get_grouped_opcodes(2):
        i1, i2, j1, j2 = grp[0][1], grp[-1][2], grp[0][3], grp[-1][4]
        body = []
        for tag, a1, a2, b1, b2 in grp:
            if tag == "equal":
                body += [" " + x for x in a[a1:a2]]
            if tag in ("replace", "delete"):
                body += ["-" + x for x in a[a1:a2]]
            if tag in ("replace", "insert"):
                body += ["+" + x for x in b[b1:b2]]
        out.append({"oldStart": i1 + 1, "oldLines": i2 - i1, "newStart": j1 + 1, "newLines": j2 - j1, "lines": body})
    return out


lines.append({"type": "ai-title", "aiTitle": "Unicode titles produce empty slugs", "sessionId": SID})
prompt("Titles with accents or emoji come out as broken slugs — \"Crème brûlée 🍮\" becomes "
       "\"cr-me-br-l-e\". Fix slugify so it produces \"creme-brulee\", cap slugs at 80 chars, and add tests.", 0)
say("I'll look at how slugs are built and what the tests cover first.")
tool("Read", {"file_path": f"{CWD}/slugkit/slug.py"}, OLD_SLUG)
tool("Grep", {"pattern": "slugify\\(", "path": CWD}, "slugkit/slug.py\nslugkit/posts.py\nslugkit/feed.py\ntests/test_slug.py")
tool("Read", {"file_path": f"{CWD}/slugkit/posts.py"}, "from .slug import slugify\n...")
tool("Read", {"file_path": f"{CWD}/tests/test_slug.py"}, "def test_basic(): ...")
tool("Read", {"file_path": f"{CWD}/pyproject.toml"}, "[project]\nname = \"slugkit\"")
tool("Edit", {"file_path": f"{CWD}/tests/test_slug.py", "old_string": "def test_basic():",
              "new_string": "def test_accents():\n    assert slugify(\"Crème brûlée 🍮\") == \"creme-brulee\"\n\n\ndef test_max_len():\n    assert len(slugify(\"word \" * 40)) <= 80\n\n\ndef test_basic():"},
     "The file tests/test_slug.py has been updated.", dt=9,
     result={"filePath": f"{CWD}/tests/test_slug.py", "structuredPatch": patch(
         "from slugkit.slug import slugify\n\n\ndef test_basic():\n    assert slugify(\"Hello World\") == \"hello-world\"",
         "from slugkit.slug import slugify\n\n\ndef test_accents():\n    assert slugify(\"Crème brûlée 🍮\") == \"creme-brulee\"\n\n\ndef test_max_len():\n    assert len(slugify(\"word \" * 40)) <= 80\n\n\ndef test_basic():\n    assert slugify(\"Hello World\") == \"hello-world\"")})
tool("Bash", {"command": "cd /home/dev/slugkit && python -m pytest -q", "description": "Run tests"},
     "Exit code 1\n..F.F.........                                                   [100%]\n"
     "=================================== FAILURES ===================================\n"
     "________________________________ test_accents _________________________________\n"
     ">       assert slugify(\"Crème brûlée 🍮\") == \"creme-brulee\"\n"
     "E       AssertionError: assert 'cr-me-br-l-e' == 'creme-brulee'\n"
     "________________________________ test_max_len _________________________________\n"
     "E       assert 199 <= 80\n"
     "=========================== short test summary info ============================\n"
     "FAILED tests/test_slug.py::test_accents - AssertionError\n"
     "FAILED tests/test_slug.py::test_max_len - assert 199 <= 80\n"
     "2 failed, 12 passed in 0.31s", dt=14, error=True)
say("Two failures, as expected: accented letters are dropped instead of folded, and there is no length cap. "
    "Normalising to NFKD and encoding to ASCII folds é→e and drops the emoji.")
tool("Edit", {"file_path": f"{CWD}/slugkit/slug.py", "old_string": OLD_SLUG, "new_string": NEW_SLUG},
     "The file slugkit/slug.py has been updated.", dt=21,
     result={"filePath": f"{CWD}/slugkit/slug.py", "structuredPatch": patch(OLD_SLUG, NEW_SLUG)})
tool("Bash", {"command": "cd /home/dev/slugkit && python -m pytest -q", "description": "Run tests"},
     "..............                                                   [100%]\n14 passed in 0.27s", dt=12)
tool("Bash", {"command": "cd /home/dev/slugkit && git add -A && git commit -q -m \"slugify: fold accents, drop emoji, cap at 80 chars\" && git push -q",
              "description": "Commit and push"}, "", dt=8)
say("Fixed. `slugify(\"Crème brûlée 🍮\")` now returns `creme-brulee`: titles are NFKD-normalised and folded to ASCII, "
    "symbols and emoji are dropped, and slugs are capped at 80 characters. Two new tests cover it; all 14 pass.")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
print(f"wrote {OUT} ({len(lines)} lines)")
