"""Remove secrets and personal data from a session before anything is drawn.

Runs on the normalised Session, not on frames: once a string is redacted here, no later stage
has the original. Patterns err toward over-redaction; a false positive costs a word in a video,
a false negative costs a leaked key on X.
"""
from __future__ import annotations

import os
import re
import socket
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePath

from .models import Session

_SECRET_WORD = (r"(?:api[_-]?key|secrets?|tokens?|passw(?:or)?d|pwd|credentials?|private[_-]?key|auth(?:[_-]?token|orization)?"
                r"|access[_-]?key|client[_-]?secret|signing[_-]?key|signing|salt|accountkey|[a-z0-9]*_key|dsn)")

PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"), "[private key]"),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), "[anthropic key]"),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"), "[api key]"),
    ("stripe-key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"), "[stripe key]"),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "[github token]"),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"), "[gitlab token]"),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{30,}"), "[npm token]"),
    ("pypi-token", re.compile(r"\bpypi-[A-Za-z0-9_\-]{30,}"), "[pypi token]"),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[aws key]"),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[slack token]"),
    ("sendgrid-key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"), "[sendgrid key]"),
    ("twilio-key", re.compile(r"\bSK[0-9a-f]{32}\b"), "[twilio key]"),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[google key]"),
    ("hf-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), "[hf token]"),
    ("webhook", re.compile(r"(?i)https?://(?:hooks\.slack\.com/services|(?:discord|discordapp)\.com/api/webhooks|api\.telegram\.org/bot)[^\s\"'<>]+"), "[webhook url]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[jwt]"),
    ("bearer", re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9_\-\.=+/~]{16,}"), r"\1 [redacted]"),
    ("basic-auth", re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/]{12,}={0,2}"), r"\1 [redacted]"),
    ("url-credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/:@]+:[^\s/@]+@"), r"\1[user]:[redacted]@"),
    ("url-token", re.compile(r"(?i)([?&](?:" + _SECRET_WORD + r"|sig|signature|key|code)=)[^&\s\"']+"), r"\1[redacted]"),
    ("cli-password", re.compile(r"(?i)((?:--(?:password|passwd|token|api-key|secret)(?:=|\s+))|(?:\b(?:mysql|mysqldump|mariadb|psql)\b[^\n]*?\s-p))(?!\[)[^\s'\"]{3,}"), r"\1[redacted]"),
    ("cli-user-pass", re.compile(r"((?:\s-u|--user)\s+[^\s:'\"]+:)[^\s'\"]+"), r"\1[redacted]"),
    ("assignment", re.compile(r"(?i)(?<![A-Za-z0-9])((?:[A-Z0-9.]*[_\-.])?" + _SECRET_WORD + r"(?:[_\-][A-Z0-9_\-]*)?)([\"']?\s*[=:]\s*)([\"']?)(?!\[)(?!\s)(?!(?:Bearer|Basic)\b)[^\s'\",;}\[\](){}]{6,}\3(?=[\s'\",;}\]]|$)"), r"\1\2\3[redacted]\3"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[email]"),
    # long mixed-case+digit tokens with no separators: almost always a credential or a hash of one
    ("high-entropy", re.compile(r"\b(?=[A-Za-z0-9+_=]{32,})(?=[^\s]*[A-Z])(?=[^\s]*[a-z])(?=[^\s]*\d)[A-Za-z0-9+_]{32,}={0,2}"), "[redacted]"),
]

# Per-session scratch dirs are long, noisy and carry session ids; show them as $TMP.
_TMP = re.compile(r"(?:/private)?/tmp/claude-\d+/[^\s/'\"]+/[0-9a-f-]{36}/scratchpad|/(?:private/)?var/folders/[\w-]+/[\w-]+/T(?=/)")

SECRET_FILES = re.compile(r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|\.envrc|\.netrc|\.npmrc|\.pypirc|\.pgpass|\.git-credentials|id_[a-z0-9]+"
                          r"|[^/]*\.(?:pem|key|p12|pfx|jks|keystore|tfvars|tfstate)|credentials(?:\.json)?|[^/]*service[-_]account[^/]*\.json"
                          r"|[^/]*sa[-_]key[^/]*\.json|\.kube/config|\.docker/config\.json|\.aws/credentials)$")


def _encode(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


class Redactor:
    def __init__(self, extra: Iterable[str] = (), home: str | None = None, hostname: str | None = None) -> None:
        self.patterns = list(PATTERNS)
        for i, rx in enumerate(extra):
            self.patterns.append((f"custom-{i + 1}", re.compile(rx), "[redacted]"))
        self.home = (home if home is not None else os.path.expanduser("~")).rstrip("/")
        self.counts: Counter[str] = Counter()
        # identity: the home path, its Claude-Code-encoded form, the bare username and this host
        ident: list[tuple[str, re.Pattern[str], str]] = []
        if self.home and self.home != "/":
            ident.append(("home-path", re.compile(re.escape(self.home) + r"(?![\w.-])", re.I), "~"))
            ident.append(("home-path", re.compile(re.escape(_encode(self.home)) + r"(?![A-Za-z0-9])", re.I), "-~"))
            user = os.path.basename(self.home)
            if len(user) >= 3:
                ident.append(("username", re.compile(r"(?<![\w.-])" + re.escape(user) + r"(?![\w-])", re.I), "user"))
        host = (hostname if hostname is not None else socket.gethostname()).split(".")[0]
        if len(host) >= 4 and host.lower() not in {"localhost", "local"}:
            ident.append(("hostname", re.compile(r"(?<![\w-])" + re.escape(host) + r"(?![\w-])", re.I), "host"))
        ident.append(("user-at-host", re.compile(r"(?<![\w.])[a-z_][a-z0-9_.-]{1,31}@[A-Za-z0-9][A-Za-z0-9-]{2,}(?:\.local)?\b(?!\.[A-Za-z])"), "user@host"))
        self.ident = ident

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
        for name, rx, repl in self.ident:
            s, n = rx.subn(repl, s)
            if n:
                self.counts[name] += n
        return s

    def block(self, lines: list[str]) -> list[str]:
        """Redact a multi-line block as one string so patterns spanning lines (private keys) match,
        then split back. Diff signs stay on each line."""
        return self.text("\n".join(lines)).split("\n")

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


def redact_session(sess: Session, extra: Iterable[str] = (), home: str | None = None,
                   hostname: str | None = None) -> Session:
    r = Redactor(extra, home, hostname)
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
            h.lines = r.block(h.lines)
    sess.cwd = r.text(sess.cwd)
    sess.title = r.text(sess.title)
    sess.branch = r.text(sess.branch)
    sess.model = r.text(sess.model)
    sess.redactions = dict(r.counts)
    return sess
