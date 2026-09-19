"""sessionreel command line."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from importlib import resources
from pathlib import Path

from . import __version__, ingest, redact, render, story


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def _progress(done: int, total: int) -> None:
    if done == total or done % 15 == 0:
        bar = int(28 * done / max(1, total))
        sys.stderr.write(f"\r  rendering [{'█' * bar}{'·' * (28 - bar)}] {done}/{total} frames")
        if done == total:
            sys.stderr.write("\n")
        sys.stderr.flush()


def _resolve(ref: str | None) -> Path:
    if ref:
        return ingest.find_session(ref)
    files = ingest.session_files(cwd=os.getcwd())
    if not files:
        raise FileNotFoundError(
            f"no Claude Code sessions for {os.getcwd()} under {ingest.projects_root()}\n"
            "  run `sessionreel list` to see all sessions, or pass a session id / .jsonl path")
    return files[0]


def _plan(args: argparse.Namespace) -> dict:
    path = _resolve(args.session)
    sess = ingest.load(path)
    redact.redact_session(sess, extra=args.redact or ())
    board = story.build(sess, lang=args.lang, whole=args.whole)
    n = sum(board["redactions"].values())
    what = ", ".join(f"{v} {k}" for k, v in sorted(board["redactions"].items(), key=lambda kv: -kv[1]))
    _eprint(f"  session  {path.stem[:8]}  ({len(sess.events)} events"
            + (f", {sess.skipped_lines} malformed lines skipped" if sess.skipped_lines else "") + ")")
    _eprint(f"  story    {' → '.join(s['kind'] for s in board['scenes'])}"
            + ("" if board["arc"] else "   (no red→green arc found; built from the largest edits)"))
    _eprint(f"  redacted {n} item{'s' if n != 1 else ''}" + (f" ({what})" if what else ""))
    return board


def _render(board: dict, args: argparse.Namespace) -> Path:
    out = Path(args.output)
    audio = None
    if args.voice is not None:
        from . import voice
        board, audio = voice.narrate(board, voice=args.voice or None)
    t0 = time.time()
    render.render(board, out, fmt=args.format, audio=audio, progress=_progress)
    secs = sum(float(s.get("seconds", 3)) for s in board["scenes"])
    _eprint(f"  wrote    {out}  ({secs:.0f}s video, {out.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f}s to render)")
    if args.gif:
        gif = render.to_gif(out, out.with_suffix(".gif"))
        _eprint(f"  wrote    {gif}  ({gif.stat().st_size / 1e6:.1f} MB)")
    return out


def cmd_make(args: argparse.Namespace) -> int:
    board = _plan(args)
    _render(board, args)
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    board = _plan(args)
    text = json.dumps(board, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(text)
    else:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        _eprint(f"  wrote    {args.output}  — edit captions, then: sessionreel render {args.output}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    board = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    if board.get("version") != story.STORYBOARD_VERSION:
        _eprint(f"  storyboard version {board.get('version')} is not supported by this sessionreel ({__version__})")
        return 2
    _render(board, args)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    files = ingest.session_files(cwd=os.getcwd() if args.here else None)[: args.limit]
    if not files:
        _eprint(f"  no sessions under {ingest.projects_root()}")
        return 1
    home = str(Path.home())
    for f in files:
        sess = ingest.load(f)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
        cwd = sess.cwd.replace(home, "~") if sess.cwd else "?"
        mins = int(story.active_seconds(sess.events) // 60)
        print(f"{f.stem[:8]}  {when}  {mins:>4}m  {len(sess.prompts):>3} prompts  {len(sess.tools):>4} tools  {cwd}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    args.session = str(resources.files("sessionreel").joinpath("demo", "demo-session.jsonl"))
    return cmd_make(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sessionreel",
        description="Turn a Claude Code session into a short recap video. Local, redacted, no API key.",
    )
    p.add_argument("--version", action="version", version=f"sessionreel {__version__}")
    sub = p.add_subparsers(dest="cmd")

    def story_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("session", nargs="?", help="session id, id prefix or .jsonl path (default: latest here)")
        sp.add_argument("--lang", choices=sorted(story.T), default="en", help="caption language")
        sp.add_argument("--whole", action="store_true", help="tell the whole session, not just the episode around the fix")
        sp.add_argument("--redact", action="append", metavar="REGEX", help="extra pattern to redact (repeatable)")

    def video_opts(sp: argparse.ArgumentParser, default_out: str = "reel.mp4") -> None:
        sp.add_argument("-o", "--output", default=default_out)
        sp.add_argument("--format", choices=sorted(render.FORMATS), default="square")
        sp.add_argument("--voice", nargs="?", const="", default=None, metavar="NAME",
                        help="narrate captions with the OS voice (optionally a voice name)")
        sp.add_argument("--gif", action="store_true", help="also write a GIF next to the mp4")

    mk = sub.add_parser("make", help="session → mp4 (default command)")
    story_opts(mk)
    video_opts(mk)
    mk.set_defaults(fn=cmd_make)

    pl = sub.add_parser("plan", help="session → editable storyboard.json")
    story_opts(pl)
    pl.add_argument("-o", "--output", default="storyboard.json", help="path, or - for stdout")
    pl.set_defaults(fn=cmd_plan)

    rd = sub.add_parser("render", help="storyboard.json → mp4")
    rd.add_argument("storyboard")
    video_opts(rd)
    rd.set_defaults(fn=cmd_render)

    ls = sub.add_parser("list", help="recent sessions")
    ls.add_argument("--here", action="store_true", help="only sessions for the current directory")
    ls.add_argument("-n", "--limit", type=int, default=20)
    ls.set_defaults(fn=cmd_list)

    dm = sub.add_parser("demo", help="render the bundled sample session (no logs needed)")
    dm.add_argument("--lang", choices=sorted(story.T), default="en")
    video_opts(dm, "sessionreel-demo.mp4")
    dm.set_defaults(fn=cmd_demo, whole=False, redact=None)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    if not argv or argv[0] not in {"make", "plan", "render", "list", "demo", "-h", "--help", "--version"}:
        argv = ["make", *argv]
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _eprint(f"sessionreel: {e}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
