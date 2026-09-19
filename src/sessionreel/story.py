"""Turn a session into a storyboard: a short list of scenes that tells what happened.

Deterministic on purpose. The spine is the red→fix→green arc: a test or build command that
failed, the edits that followed, the same command passing. Every caption is built from numbers
in the log; nothing here can claim what the log does not show.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .models import Event, Session

STORYBOARD_VERSION = 1

# (family, pattern) — the family groups "the same check" so red and green can be matched.
_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("pytest", re.compile(r"\bpytest\b|\bpython[0-9.]* -m pytest\b")),
    ("jest", re.compile(r"\b(?:jest|vitest)\b")),
    ("npm-test", re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b")),
    ("go-test", re.compile(r"\bgo test\b")),
    ("cargo-test", re.compile(r"\bcargo (?:test|nextest)\b")),
    ("tsc", re.compile(r"\btsc\b")),
    ("build", re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+run\s+build\b|\bcargo build\b|\bgo build\b|\bmake\b(?!\S)")),
    ("ruff", re.compile(r"\bruff\b")),
    ("mypy", re.compile(r"\bmypy\b|\bpyright\b")),
    ("unittest", re.compile(r"\bpython[0-9.]* -m unittest\b")),
]
_SHIP = re.compile(r"\bgit (?:commit|push)\b|\bgh (?:pr create|release create)\b|\b(?:npm|pnpm) publish\b|\btwine upload\b|\buv publish\b")
_COMMIT_MSG = re.compile(r"""git commit[^\n]*?-m\s+(?:"([^"]+)"|'([^']+)'|\$\(cat <<'?EOF'?\n([^\n]+))""")
_EXPLORE = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}
_EDITS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}

MAX_ARC_EVENTS = 80  # a red and its green further apart than this are different stories
MIN_GOAL_CHARS = 12
_DOC = re.compile(r"\.(?:md|mdx|rst|txt|json|ya?ml|toml|lock|csv)$", re.I)

SECONDS = {"title": 2.6, "prompt": 4.2, "montage": 3.2, "terminal": 4.6, "diff": 5.6,
           "ship": 3.4, "say": 3.8, "stats": 4.2, "end": 2.6}


@dataclass
class CheckRun:
    index: int
    family: str
    ok: bool
    passed: int | None
    failed: int | None
    errors: int | None


_PREFIX = re.compile(r"^(?:[A-Z_][A-Z0-9_]*=\S*\s+)*(?:(?:uv|poetry|pdm|hatch)\s+run\s+|npx\s+|bunx\s+|\S*/(?=\S*(?:pytest|python|jest|vitest|tsc|ruff|mypy)\b))?")


def _segments(command: str) -> list[str]:
    """Split a shell line into the commands it runs; heredoc bodies are not commands."""
    body = re.split(r"<<-?\s*'?\"?(\w+)", command, maxsplit=1)[0]
    return [seg.strip() for seg in re.split(r"&&|\|\||;|\||\n", body) if seg.strip()]


def check_family(command: str) -> str | None:
    """The check a command runs, judged only from the start of each shell segment."""
    for seg in _segments(command):
        if seg.startswith(("cd ", "echo ", "export ", "source ", ". ")):
            continue
        head = _PREFIX.sub("", seg)
        for family, rx in _CHECKS:
            m = rx.search(head)
            if m and m.start() == 0:
                if family == "build" and head.startswith("make"):
                    target = next((w for w in head.split()[1:] if not w.startswith("-")), "")
                    return f"make {target}".strip()
                return family
    return None


def _num(rx: str, text: str) -> int | None:
    m = re.findall(rx, text)
    return int(m[-1]) if m else None


def parse_check(ev: Event, index: int) -> CheckRun | None:
    family = check_family(ev.command)
    if family is None:
        return None
    out = ev.output
    passed = _num(r"(\d+) passed", out)
    failed = _num(r"(\d+) failed", out)
    errors = _num(r"(\d+) errors?\b", out)
    m = re.search(r"Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(\d+) passed", out)  # jest
    if m:
        failed = int(m.group(1) or 0)
        passed = int(m.group(2))
    m = re.search(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed", out)  # cargo
    if m:
        passed, failed = int(m.group(1)), int(m.group(2))
    bad = ev.error or bool(failed) or bool(errors) or bool(re.search(r"^(?:FAIL|FAILED)\b|Exit code [1-9]", out, re.M))
    if family == "tsc" and re.search(r"error TS\d+", out):
        bad = True
        errors = errors or len(re.findall(r"error TS\d+", out))
    return CheckRun(index, family, not bad, passed, failed, errors)


def _changed(ev: Event) -> tuple[int, int]:
    add = sum(1 for h in ev.hunks for ln in h.lines if ln.startswith("+"))
    rem = sum(1 for h in ev.hunks for ln in h.lines if ln.startswith("-"))
    return add, rem


_CWD = [""]  # set per build so paths can be shown relative to the project


def _short(path: str, keep: int = 2) -> str:
    root = _CWD[0].rstrip("/")
    if root and path.startswith(root + "/"):
        path = path[len(root) + 1:]
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return "/".join(parts[-keep:]) if parts else path


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _first_sentence(text: str, n: int = 150) -> str:
    text = re.sub(r"[`*_#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?。])(?:\s|$)", text)
    return _clip(m.group(1) if m else text, n)


def _output_tail(output: str, n: int = 14) -> list[str]:
    lines = [ln.rstrip() for ln in output.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    # Keep the lines that carry the verdict: failures and the summary, then the tail.
    key = [ln for ln in lines if re.search(r"FAIL|Error|error|passed|failed|✓|✗|assert", ln)]
    picked = (key[-(n - 4):] if key else []) + lines[-4:]
    seen: set[str] = set()
    out = [ln for ln in picked if not (ln in seen or seen.add(ln))]  # type: ignore[func-returns-value]
    return [ln[:110] for ln in out[-n:]]


def _badge(run: CheckRun) -> str:
    if run.ok:
        return f"{run.passed} passed" if run.passed is not None else "passed"
    if run.failed:
        return f"{run.failed} failed"
    if run.errors:
        return f"{run.errors} error{'s' if run.errors != 1 else ''}"
    return "failed"


def _terminal_scene(ev: Event, run: CheckRun | None, caption: str) -> dict:
    status = "ok" if run is None else ("pass" if run.ok else "fail")
    return {"kind": "terminal", "command": _clip(ev.command, 160), "output": _output_tail(ev.output),
            "status": status, "badge": _badge(run) if run else ("error" if ev.error else "ok"),
            "caption": caption, "fact": caption}


def _diff_scene(ev: Event, caption: str, max_lines: int = 24) -> dict:
    lines: list[str] = []
    for h in ev.hunks:
        body = h.lines
        # Trim unchanged context so the change itself fills the frame.
        changed = [i for i, ln in enumerate(body) if ln[:1] in "+-"]
        if changed:
            lo, hi = max(0, changed[0] - 2), min(len(body), changed[-1] + 3)
            body = body[lo:hi]
        if lines:
            lines.append("@@")
        lines.extend(body)
        if len(lines) >= max_lines:
            break
    add, rem = _changed(ev)
    return {"kind": "diff", "file": _short(ev.file, 3), "lines": [ln[:100] for ln in lines[:max_lines]],
            "added": add, "removed": rem, "caption": caption, "fact": caption}


IDLE_GAP = 15 * 60  # seconds; a longer silence is a break, not work


def active_seconds(events: list[Event]) -> float:
    """Wall time with breaks removed: gaps over IDLE_GAP count as zero."""
    stamps = sorted(e.ts for e in events if e.ts)
    return sum(min(d, IDLE_GAP) for d in ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)) if d > 0)


def _fmt_duration(seconds: float) -> str:
    mins = max(1, int(seconds // 60))
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins} min"


def _fmt_tokens(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)


T = {
    "en": {
        "goal": "The ask", "explore": "Read {files} file{fs}, ran {searches} search{ss}",
        "red": "{badge} — `{family}` goes red", "fix": "Fix in {file} (+{add} −{rem})",
        "green": "Green: {badge}", "edit": "Changed {file} (+{add} −{rem})",
        "ship": "Shipped", "check": "Ran `{family}`: {badge}", "say": "What the agent reported",
        "stats": "The session in numbers", "end": "Recapped from the session log with sessionreel",
        "labels": {"active time": "active time", "tool calls": "tool calls", "files changed": "files changed",
                   "lines": "lines", "tests": "tests", "prompts": "prompts", "passing": "passing"},
    },
    "ko": {
        "goal": "요청", "explore": "파일 {files}개 읽고 {searches}번 검색",
        "red": "{badge} — `{family}` 실패", "fix": "{file} 수정 (+{add} −{rem})",
        "green": "통과: {badge}", "edit": "{file} 변경 (+{add} −{rem})",
        "ship": "배포", "check": "`{family}` 실행: {badge}", "say": "에이전트의 보고",
        "stats": "숫자로 본 세션", "end": "세션 로그로 만든 리캡 · sessionreel",
        "labels": {"active time": "작업 시간", "tool calls": "도구 호출", "files changed": "바뀐 파일",
                   "lines": "줄", "tests": "테스트", "prompts": "프롬프트", "passing": "통과"},
    },
}


def _find_arc(ev: list[Event], runs: list[CheckRun]) -> tuple[CheckRun, CheckRun] | None:
    """Most recent red → green of the same check with at least one edit in between."""
    for j in range(len(runs) - 1, -1, -1):
        if not runs[j].ok:
            continue
        for red in reversed([r for r in runs[:j] if r.family == runs[j].family and not r.ok]):
            if runs[j].index - red.index > MAX_ARC_EVENTS:
                break
            if any(e.kind == "tool" and e.tool in _EDITS and e.hunks for e in ev[red.index:runs[j].index]):
                return red, runs[j]
    return None


def _substantive(e: Event) -> bool:
    return e.kind == "prompt" and len(re.sub(r"\s+", "", e.text)) >= MIN_GOAL_CHARS


def episode(sess: Session, whole: bool = False) -> tuple[int, int, tuple[CheckRun, CheckRun] | None]:
    """The slice of the session the reel tells: from the ask that led to the arc up to the next ask.

    A long session holds many unrelated tasks; a reel about one of them must not end on another
    task's summary. `whole=True` keeps the entire session.
    """
    ev = sess.events
    runs = [r for i, e in enumerate(ev) if e.kind == "tool" and e.tool == "Bash" for r in [parse_check(e, i)] if r]
    arc = _find_arc(ev, runs)
    if whole:
        return 0, len(ev), arc
    edits = [i for i, e in enumerate(ev) if e.kind == "tool" and e.tool in _EDITS and e.hunks]
    if arc:
        anchor, after = arc[0].index, arc[1].index
    elif edits:
        # no arc: the busiest stretch of editing, anchored on its largest edit
        anchor = max(edits, key=lambda i: sum(_changed(ev[i])))
        after = anchor
    else:
        return 0, len(ev), None
    start = next((i for i in range(anchor, -1, -1) if _substantive(ev[i])), 0)
    end = next((i for i in range(after + 1, len(ev)) if _substantive(ev[i])), len(ev))
    return start, end, arc


def _display_command(command: str) -> str:
    """Show the part of a shell line that ran the check, not the `cd … &&` plumbing around it."""
    for seg in _segments(command):
        if check_family(seg):
            return re.sub(r"\s*2>&1\s*$", "", seg)
    segs = [x for x in _segments(command) if not x.startswith(("cd ", "export ", "source "))]
    return segs[0] if segs else command


_NOISE = re.compile(r"^(?:Shell cwd was reset to .*|.*<persisted-output>.*|\(eval\):\d+: .*)$")


def _commit_message(command: str) -> str:
    m = _COMMIT_MSG.search(command)
    if m:
        return next((g for g in m.groups() if g), "")
    m = re.search(r"git commit[^\n]*?-F\s*-\s*<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n\s*(\S[^\n]*)", command)
    return m.group(2).strip() if m else ""


def _ship_command(command: str) -> str:
    seg = next((x for x in _segments(command) if _SHIP.search(x)), command)
    return seg.split("\n")[0]


def build(sess: Session, lang: str = "en", max_scenes: int = 9, whole: bool = False) -> dict:
    t = T.get(lang, T["en"])
    _CWD[0] = sess.cwd
    start, end, arc = episode(sess, whole)
    ev = sess.events[start:end]
    shift = start
    runs = [r for i, e in enumerate(ev) if e.kind == "tool" and e.tool == "Bash" for r in [parse_check(e, i)] if r]
    if arc:
        arc = (CheckRun(**{**arc[0].__dict__, "index": arc[0].index - shift}),
               CheckRun(**{**arc[1].__dict__, "index": arc[1].index - shift}))
    for e in ev:
        if e.output:
            e.output = "\n".join(ln for ln in e.output.split("\n") if not _NOISE.match(ln.strip()))

    edits = [(i, e) for i, e in enumerate(ev) if e.kind == "tool" and e.tool in _EDITS and e.hunks]
    goal = next((e for e in ev if _substantive(e)), None)
    first_work = arc[0].index if arc else (edits[0][0] if edits else len(ev))

    scenes: list[dict] = []
    started = next((e.ts for e in ev if e.ts), None)
    project = os.path.basename(sess.cwd.rstrip("/")) or "session"
    if arc:
        hook = f"{_badge(arc[0])} → {_badge(arc[1])}"
    elif edits:
        hook = f"{len({e.file for _, e in edits})} files changed"
    else:
        hook = _clip(sess.title, 60)
    scenes.append({"kind": "title", "project": project, "title": hook,
                   "date": started.strftime("%Y-%m-%d") if started else "", "model": sess.model,
                   "branch": "" if sess.branch in ("HEAD", "") else sess.branch,
                   "duration": _fmt_duration(active_seconds(ev))})
    if goal:
        scenes.append({"kind": "prompt", "text": _clip(goal.text, 280), "caption": t["goal"], "fact": t["goal"]})

    window = ev[:first_work]
    reads = {e.file for e in window if e.kind == "tool" and e.tool == "Read" and e.file}
    searches = sum(1 for e in window if e.kind == "tool" and e.tool in _EXPLORE - {"Read"})
    if len(reads) + searches >= 3:
        cap = t["explore"].format(files=len(reads), searches=searches,
                                  fs="" if len(reads) == 1 else "s", ss="" if searches == 1 else "es")
        scenes.append({"kind": "montage", "files": sorted({_short(f) for f in reads})[:14],
                       "reads": len(reads), "searches": searches, "caption": cap, "fact": cap})

    def term(e: Event, run: CheckRun | None, cap: str) -> dict:
        sc = _terminal_scene(e, run, cap)
        sc["command"] = _clip(_display_command(e.command), 160)
        return sc

    if arc:
        red, green = arc
        scenes.append(term(ev[red.index], red, t["red"].format(badge=_badge(red), family=red.family)))
        fix = sorted((e for e in ev[red.index:green.index] if e.kind == "tool" and e.tool in _EDITS and e.hunks),
                     key=lambda e: (not _DOC.search(e.file), sum(_changed(e))), reverse=True)[:2]
        for e in sorted(fix, key=ev.index):
            add, rem = _changed(e)
            scenes.append(_diff_scene(e, t["fix"].format(file=_short(e.file, 1), add=add, rem=rem)))
        scenes.append(term(ev[green.index], green, t["green"].format(badge=_badge(green))))
    else:
        big = sorted(edits, key=lambda ie: (not _DOC.search(ie[1].file), sum(_changed(ie[1]))), reverse=True)[:2]
        for _, e in sorted(big, key=lambda ie: ie[0]):
            add, rem = _changed(e)
            scenes.append(_diff_scene(e, t["edit"].format(file=_short(e.file, 1), add=add, rem=rem)))
        if runs:
            last = runs[-1]
            scenes.append(term(ev[last.index], last, t["check"].format(family=last.family, badge=_badge(last))))

    after = arc[1].index if arc else 0
    ship = next((e for e in ev[after:] if e.kind == "tool" and e.tool == "Bash" and not e.error
                 and _SHIP.search(e.command)), None)
    if ship:
        scenes.append({"kind": "ship", "command": _clip(_ship_command(ship.command), 120),
                       "message": _clip(_commit_message(ship.command), 90), "caption": t["ship"], "fact": t["ship"]})

    final = next((e for e in reversed(ev) if e.kind == "say" and len(e.text) > 20), None)
    if final:
        scenes.append({"kind": "say", "text": _first_sentence(final.text, 170), "caption": t["say"], "fact": t["say"]})

    touched = {e.file for _, e in edits}
    add = sum(_changed(e)[0] for _, e in edits)
    rem = sum(_changed(e)[1] for _, e in edits)
    tools = [e for e in ev if e.kind == "tool"]
    items = [["active time", _fmt_duration(active_seconds(ev))], ["tool calls", str(len(tools))],
             ["files changed", str(len(touched))], ["lines", f"+{add} −{rem}"]]
    final_run = runs[-1] if runs else None
    if final_run and final_run.passed is not None:
        items.append(["tests", f"{final_run.passed} passing" if final_run.ok else _badge(final_run)])
    n_prompts = sum(1 for e in ev if e.kind == "prompt")
    if n_prompts > 1:
        items.append(["prompts", str(n_prompts)])
    lab = t["labels"]
    items = [[lab.get(k, k), v.replace("passing", lab["passing"])] for k, v in items]
    scenes.append({"kind": "stats", "items": items, "caption": t["stats"], "fact": t["stats"]})
    scenes.append({"kind": "end", "text": t["end"]})

    order = ["say", "montage", "ship", "prompt"]
    while len(scenes) > max_scenes and any(s["kind"] in order for s in scenes):
        kind = next(k for k in order if any(s["kind"] == k for s in scenes))
        scenes.remove(next(s for s in scenes if s["kind"] == kind))
    for s in scenes:
        s["seconds"] = SECONDS[s["kind"]]

    return {"version": STORYBOARD_VERSION, "session": sess.id, "lang": lang, "arc": bool(arc),
            "episode": [start, end], "redacted": True, "redactions": sess.redactions,
            "skipped_lines": sess.skipped_lines, "scenes": scenes}
