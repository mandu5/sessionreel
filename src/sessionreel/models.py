"""Normalised session events. Everything downstream of ingest works on these, never on raw JSONL."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Hunk:
    """One unified-diff hunk. `lines` keep their leading ' ', '-' or '+'."""

    old_start: int
    new_start: int
    lines: list[str]


@dataclass
class Event:
    kind: str  # "prompt" | "say" | "tool"
    ts: datetime | None = None
    text: str = ""  # prompt / say text
    tool: str = ""  # tool name
    input: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    file: str = ""  # file path for Read/Edit/Write, already redacted

    @property
    def command(self) -> str:
        return str(self.input.get("command", "")) if self.tool == "Bash" else ""


@dataclass
class Session:
    id: str
    path: str
    cwd: str = ""
    branch: str = ""
    model: str = ""
    title: str = ""
    events: list[Event] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache: int = 0
    skipped_lines: int = 0
    redactions: dict[str, int] = field(default_factory=dict)

    @property
    def started(self) -> datetime | None:
        return next((e.ts for e in self.events if e.ts), None)

    @property
    def ended(self) -> datetime | None:
        return next((e.ts for e in reversed(self.events) if e.ts), None)

    @property
    def prompts(self) -> list[Event]:
        return [e for e in self.events if e.kind == "prompt"]

    @property
    def tools(self) -> list[Event]:
        return [e for e in self.events if e.kind == "tool"]


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
