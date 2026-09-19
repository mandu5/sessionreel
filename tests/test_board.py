import math
import subprocess

import pytest

from sessionreel import board as B
from sessionreel import cli, render


def _b(*scenes):
    return {"version": 1, "redacted": True, "scenes": list(scenes)}


@pytest.mark.parametrize("bad,msg", [
    ([], "JSON object"),
    ({"scenes": "x"}, "scenes"),
    (_b({"kind": "nope"}), "unknown kind"),
    (_b({"kind": "end", "seconds": "abc"}), "must be a number"),
    (_b({"kind": "end", "seconds": math.nan}), "positive"),
    (_b({"kind": "end", "seconds": -1}), "positive"),
    (_b({"kind": "stats", "items": [["a"]]}), "pairs"),
    (_b({"kind": "diff", "lines": "x"}), "list"),
    (_b({"kind": "diff", "added": "many"}), "integer"),
])
def test_validate_rejects_with_a_reason(bad, msg):
    with pytest.raises(B.BoardError, match=msg):
        B.validate(bad)


def test_validate_normalises_types():
    b = B.validate(_b({"kind": "title", "project": None, "seconds": "2"},
                      {"kind": "stats", "items": [["a", 5]], "seconds": 999}))
    assert b["scenes"][0]["project"] == "" and b["scenes"][0]["seconds"] == 2.0
    assert b["scenes"][1]["items"] == [["a", "5"]] and b["scenes"][1]["seconds"] == B.MAX_SECONDS


def test_reredact_catches_secrets_added_by_editing():
    b = _b({"kind": "prompt", "caption": "key sk-ant-api03-abcdefghijklmnop", "text": "mail a@b.co", "seconds": 1})
    out, changed = B.reredact(b)
    assert "sk-ant" not in out["scenes"][0]["caption"] and "a@b.co" not in out["scenes"][0]["text"]
    assert changed and B.reredact(out)[1] == {}  # idempotent


def test_caption_claims_flags_invented_numbers():
    ok = {"kind": "terminal", "caption": "Two failures, then 14 green", "fact": "2 failed", "badge": "14 passed", "seconds": 1}
    bad = {"kind": "terminal", "caption": "3x faster, 14 green", "fact": "2 failed", "badge": "14 passed", "seconds": 1}
    assert B.caption_claims(_b(ok)) == []
    assert any("'3'" in w for w in B.caption_claims(_b(bad)))


def test_render_is_atomic_and_cleans_up_ffmpeg(tmp_path, monkeypatch):
    out = tmp_path / "reel.mp4"
    out.write_bytes(b"GOOD")

    def boom(*a, **k):
        raise RuntimeError("scene exploded")

    monkeypatch.setitem(render.SCENES, "end", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        render.render(_b({"kind": "end", "seconds": 1}), out, fps=5)
    assert out.read_bytes() == b"GOOD"                       # the old reel survives
    assert not list(tmp_path.glob(".reel.part*"))            # no partial file left behind
    assert subprocess.run(["pgrep", "-f", str(tmp_path)], capture_output=True).stdout == b""


def test_cli_render_reports_bad_storyboards(tmp_path, capsys):
    sb = tmp_path / "sb.json"
    sb.write_text('{"version": 1, "redacted": true, "scenes": [{"kind": "stats", "items": [["a"]]}]}')
    assert cli.main(["render", str(sb), "-o", str(tmp_path / "x.mp4")]) == 1
    assert "pairs" in capsys.readouterr().err
    sb.write_text("{not json")
    assert cli.main(["render", str(sb)]) == 1
