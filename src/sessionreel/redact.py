"""Remove secrets and personal data from a session before anything is drawn.

Runs on the normalised Session, not on frames: once a string is redacted here, no later stage
has the original. Patterns err toward over-redaction; a false positive costs a word in a video,
a false negative costs a leaked key on X.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePath

from .models import Session

_SECRET_WORD = r"(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|credential|private[_-]?key|auth|access[_-]?key|client[_-]?secret)"

PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"), "[private key]"),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), "[anthropic key]"),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"), "[api key]"),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "[github token]"),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[aws key]"),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[slack token]"),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[google key]"),
    ("hf-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), "[hf token]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[jwt]"),
    ("bearer", re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9_\-\.=]{16,}"), r"\1 [redacted]"),
    ("url-credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/:@]+:[^\s/@]+@"), r"\1[user]:[redacted]@"),
    ("url-token", re.compile(r"(?i)([?&](?:" + _SECRET_WORD + r"|sig|signature|key)=)[^&\s\"']+"), r"\1[redacted]"),
    ("assignment", re.compile(r"(?i)\b([A-Z0-9_\-]*" + _SECRET_WORD + r"[A-Z0-9_\-]*)(\s*[=:]\s*)(['\"]?)(?!\[)[^\s'\"]{6,}\3"), r"\1\2\3[redacted]\3"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[email]"),
]

# Per-session scratch dirs are long, noisy and carry session ids; show them as $TMP.
_TMP = re.compile(r"(?:/private)?/tmp/claude-\d+/[^\s/'\"]+/[0-9a-f-]{36}/scratchpad|/(?:private/)?var/folders/[\w-]+/[\w-]+/T(?=/)")

SECRET_FILES = re.compile(r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|\.netrc|\.npmrc|\.pypirc|id_[a-z0-9]+|[^/]*\.pem|[^/]*\.key|credentials(?:\.json)?)$")


class Redactor:
    def __init__(self, extra: Iterable[str] = (), home: str | None = None) -> None:
        self.patterns = list(PATTERNS)
        for i, rx in enumerate(extra):
            self.patterns.append((f"custom-{i + 1}", re.compile(rx), "[redacted]"))
        self.home = (home if home is not None else os.path.expanduser("~")).rstrip("/")
        self.counts: Counter[str] = Counter()

    def text(self, s: str) -> str:
        if not s:
            return s
        for name, rx, repl in self.patterns:
            s, n = rx.subn(repl, s)
            if n:
                self.counts[name] += n
        s, n = _TMP.subn("$TMP", s)
        if n:
            self.counts["temp-path"] += n
        if self.home and self.home != "/" and self.home in s:
            self.counts["home-path"] += s.count(self.home)
            s = s.replace(self.home, "~")
        return s

    def value(self, v: object) -> object:
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {k: self.value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        return v


def is_secret_file(path: str) -> bool:
    return bool(path) and bool(SECRET_FILES.search(PurePath(path).as_posix()))


def redact_session(sess: Session, extra: Iterable[str] = (), home: str | None = None) -> Session:
    r = Redactor(extra, home)
    for ev in sess.events:
        if ev.kind == "tool" and is_secret_file(ev.file):
            ev.output = "[contents hidden: secret file]"
            ev.hunks = []
            ev.input = {k: v for k, v in ev.input.items() if k in ("file_path", "notebook_path")}
            r.counts["secret-file"] += 1
        ev.text = r.text(ev.text)
        ev.output = r.text(ev.output)
        ev.file = r.text(ev.file)
        ev.input = r.value(ev.input)  # type: ignore[assignment]
        for h in ev.hunks:
            h.lines = [r.text(ln) for ln in h.lines]
    sess.cwd = r.text(sess.cwd)
    sess.title = r.text(sess.title)
    sess.redactions = dict(r.counts)
    return sess
