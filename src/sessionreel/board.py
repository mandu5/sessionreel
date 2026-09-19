"""Checks a storyboard must pass before any frame is drawn.

A storyboard is plain JSON that people and agents edit between `plan` and `render`, so the
renderer cannot trust it: `validate` normalises its shape (clear errors instead of tracebacks),
`reredact` runs the redactor over every string again (idempotent — placeholders do not re-match),
and `caption_claims` flags numbers in captions that the scene's own data does not contain.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from .redact import Redactor

KINDS = {"title", "prompt", "montage", "terminal", "diff", "ship", "say", "stats", "end"}
MAX_SECONDS = 30.0


class BoardError(ValueError):
    pass


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def validate(board: Any) -> dict:
    """Return a cleaned copy of `board` or raise BoardError naming the first problem."""
    if not isinstance(board, dict):
        raise BoardError("storyboard must be a JSON object")
    scenes = board.get("scenes")
    if not isinstance(scenes, list):
        raise BoardError("storyboard has no 'scenes' list")
    out = copy.deepcopy(board)
    clean: list[dict] = []
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            raise BoardError(f"scene {i} is not an object")
        kind = sc.get("kind")
        if kind not in KINDS:
            raise BoardError(f"scene {i}: unknown kind {kind!r} (expected one of {', '.join(sorted(KINDS))})")
        sc = dict(sc)
        try:
            secs = float(sc.get("seconds", 3))
        except (TypeError, ValueError):
            raise BoardError(f"scene {i} ({kind}): seconds must be a number, got {sc.get('seconds')!r}") from None
        if not math.isfinite(secs) or secs <= 0:
            raise BoardError(f"scene {i} ({kind}): seconds must be a positive number, got {secs!r}")
        sc["seconds"] = min(secs, MAX_SECONDS)
        for key in ("caption", "fact", "text", "command", "file", "message", "badge", "status",
                    "project", "title", "date", "model", "branch", "duration"):
            if key in sc:
                sc[key] = _str(sc[key])
        for key in ("output", "lines", "files"):
            if key in sc:
                if not isinstance(sc[key], list):
                    raise BoardError(f"scene {i} ({kind}): {key} must be a list of strings")
                sc[key] = [_str(x) for x in sc[key]]
        if kind == "stats":
            items = sc.get("items", [])
            if not isinstance(items, list) or not all(isinstance(it, (list, tuple)) and len(it) == 2 for it in items):
                raise BoardError(f"scene {i} (stats): items must be a list of [label, value] pairs")
            sc["items"] = [[_str(a), _str(b)] for a, b in items]
        for key in ("added", "removed"):
            if key in sc:
                try:
                    sc[key] = int(sc[key])
                except (TypeError, ValueError):
                    raise BoardError(f"scene {i} ({kind}): {key} must be an integer") from None
        clean.append(sc)
    out["scenes"] = clean
    return out


def reredact(board: dict, redactor: Redactor | None = None) -> tuple[dict, dict[str, int]]:
    """Run redaction over every string in every scene. Returns the board and what changed."""
    r = redactor or Redactor()
    scenes = r.value(board["scenes"])
    return {**board, "scenes": scenes}, dict(r.counts)


_NUM = re.compile(r"\d[\d,.]*")


def caption_claims(board: dict) -> list[str]:
    """Numbers in a caption that appear nowhere in that scene's data or its template fact."""
    warnings: list[str] = []
    for i, sc in enumerate(board.get("scenes", [])):
        cap = sc.get("caption", "")
        if not cap or cap == sc.get("fact"):
            continue
        support = " ".join(_str(v) if not isinstance(v, list) else " ".join(map(_str, v))
                           for k, v in sc.items() if k != "caption")
        known = {n.strip(".,").replace(",", "") for n in _NUM.findall(support)}
        for n in _NUM.findall(cap):
            n = n.strip(".,").replace(",", "")
            if n and n not in known:
                warnings.append(f"scene {i} ({sc.get('kind')}): caption says {n!r}, which is not in the scene data")
    return warnings
