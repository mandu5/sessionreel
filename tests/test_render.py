import json
import shutil
import subprocess

import pytest

from sessionreel import cli, ingest, render, story
from sessionreel.redact import redact_session


def _board(path):
    return story.build(redact_session(ingest.load(path), home="/nonexistent"))


def test_every_scene_draws_something(arc_session):
    b = _board(arc_session)
    for i, sc in enumerate(b["scenes"]):
        img = render.still(b, i, sc["seconds"] * 0.9)
        assert img.size == (1080, 1080)
        lo, hi = img.convert("L").getextrema()
        assert hi - lo > 120, sc["kind"]  # real content, not a flat frame


@pytest.mark.parametrize("fmt", ["wide", "tall"])
def test_other_formats(arc_session, fmt):
    b = _board(arc_session)
    img = render.still(b, 3, 3.0, fmt)
    assert img.size == render.FORMATS[fmt]


def test_korean_and_emoji_use_fallback_fonts():
    assert [k for k, _ in render._runs("fix 한글 🍮", "mono")] == ["mono", "ko", "mono", "emoji"]
    assert render._runs("a️b", "ui") == [("ui", "ab")]


def test_wrap_respects_width_and_line_cap():
    lines = render.wrap("word " * 80, "ui", 40, 500, max_lines=3)
    assert len(lines) == 3 and lines[-1].endswith("…")
    assert all(render.text_width(ln, "ui", 40) <= 500 for ln in lines)
    ko = render.wrap("가" * 200, "ui", 40, 500)
    assert len(ko) > 1 and all(render.text_width(ln, "ui", 40) <= 500 for ln in ko)


def test_unredacted_board_is_refused(arc_session, tmp_path):
    b = _board(arc_session)
    b["redacted"] = False
    with pytest.raises(ValueError):
        render.render(b, tmp_path / "x.mp4")


@pytest.mark.skipif(not (shutil.which("ffprobe") or shutil.which("ffmpeg")), reason="needs ffmpeg")
def test_video_end_to_end(arc_session, tmp_path):
    b = _board(arc_session)
    for s in b["scenes"]:
        s["seconds"] = 0.6  # keep the test fast; timing logic is the same
    out = render.render(b, tmp_path / "reel.mp4", fps=10)
    probe = shutil.which("ffprobe")
    if probe:
        info = json.loads(subprocess.check_output([probe, "-v", "error", "-show_entries",
                                                   "stream=width,height,codec_name:format=duration", "-of", "json", str(out)]))
        st = info["streams"][0]
        assert (st["codec_name"], st["width"], st["height"]) == ("h264", 1080, 1080)
        assert abs(float(info["format"]["duration"]) - 0.6 * len(b["scenes"])) < 0.3


def test_cli_plan_then_render(arc_session, tmp_path, monkeypatch):
    sb = tmp_path / "sb.json"
    assert cli.main(["plan", str(arc_session), "-o", str(sb)]) == 0
    board = json.loads(sb.read_text())
    assert board["redacted"] and board["scenes"][0]["kind"] == "title"
    for s in board["scenes"]:
        s["seconds"] = 0.4
    board["scenes"][1]["caption"] = "Rewritten by a human"
    sb.write_text(json.dumps(board))
    assert cli.main(["render", str(sb), "-o", str(tmp_path / "r.mp4")]) == 0
    assert (tmp_path / "r.mp4").stat().st_size > 10_000


def test_cli_errors_are_friendly(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SESSIONREEL_PROJECTS_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1
    assert "no Claude Code sessions" in capsys.readouterr().err
    assert cli.main(["nope"]) == 1


def test_demo_session_is_bundled_and_tells_an_arc():
    from importlib import resources
    path = resources.files("sessionreel").joinpath("demo", "demo-session.jsonl")
    b = story.build(redact_session(ingest.load(str(path))))
    assert b["arc"] and b["scenes"][0]["title"] == "2 failed → 14 passed"


def test_wrap_never_gets_zero_lines():
    assert render.wrap("short", "ui", 40, 500, max_lines=0) == ["short"]
