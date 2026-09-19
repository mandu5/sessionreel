import pytest

from sessionreel import ingest, story
from sessionreel.models import Event
from sessionreel.redact import redact_session


@pytest.mark.parametrize("cmd,family", [
    ("python -m pytest -q", "pytest"), ("cd x && uv run pytest tests/", "pytest"),
    ("PYTHONPATH=src python3 -m pytest", "pytest"), (".venv/bin/pytest -x", "pytest"),
    ("npx vitest run", "jest"), ("pnpm test", "npm-test"), ("go test ./...", "go-test"),
    ("cargo test", "cargo-test"), ("npx tsc --noEmit", "tsc"), ("make typecheck", "make typecheck"),
    ("make -s test", "make test"), ("ruff check .", "ruff check"),
    ("echo pytest", None), ("cat > f <<'EOF'\nmake stuff\npytest\nEOF", None),
    ("git commit -m 'run pytest'", None), ("grep -r pytest .", None),
])
def test_check_family(cmd, family):
    assert story.check_family(cmd) == family


@pytest.mark.parametrize("out,err,ok,passed,failed", [
    ("1 failed, 68 passed in 0.23s", True, False, 68, 1),
    ("72 passed in 0.12s", False, True, 72, None),
    ("Tests:  2 failed, 10 passed, 12 total", True, False, 10, 2),
    ("Tests:  10 passed, 10 total", False, True, 10, 0),
    ("test result: FAILED. 3 passed; 1 failed; 0 ignored", True, False, 3, 1),
    ("test result: ok. 4 passed; 0 failed; 0 ignored", False, True, 4, 0),
    ("ERROR collecting tests/test_x.py\n1 error in 0.1s", True, False, None, None),
])
def test_parse_check(out, err, ok, passed, failed):
    r = story.parse_check(Event("tool", tool="Bash", input={"command": "pytest"}, output=out, error=err, has_result=True), 0)
    assert (r.ok, r.passed, r.failed) == (ok, passed, failed)


def test_tsc_errors_count():
    ev = Event("tool", tool="Bash", input={"command": "tsc --noEmit"},
               output="a.ts(1,1): error TS2322: x\nb.ts(2,2): error TS2345: y", error=True, has_result=True)
    r = story.parse_check(ev, 0)
    assert not r.ok and r.errors == 2


def _board(path, **kw):
    return story.build(redact_session(ingest.load(path), home="/nonexistent"), **kw)


def test_arc_story(arc_session):
    b = _board(arc_session)
    kinds = [s["kind"] for s in b["scenes"]]
    # 10 candidate scenes, budget 9: the agent's closing message is the first to go
    assert b["arc"] and kinds == ["title", "prompt", "montage", "terminal", "diff", "terminal", "ship", "stats", "end"]
    red, green = [s for s in b["scenes"] if s["kind"] == "terminal"]
    assert red["status"] == "fail" and red["badge"] == "1 failed" and red["command"] == "python -m pytest -q"
    assert green["status"] == "pass" and green["badge"] == "3 passed"
    assert b["scenes"][0]["title"] == "1 failed → 3 passed"
    diff = next(s for s in b["scenes"] if s["kind"] == "diff")
    assert diff["file"] == "parser.py" and diff["added"] == 3 and diff["removed"] == 1


def test_scene_budget_is_respected(arc_session):
    b = _board(arc_session, max_scenes=7)
    assert len(b["scenes"]) == 7 and b["scenes"][0]["kind"] == "title" and b["scenes"][-1]["kind"] == "end"
    assert any(s["kind"] == "diff" for s in b["scenes"])


def test_no_arc_falls_back_to_largest_edit(log, tmp_path):
    log.prompt("Rename the config loader and update callers please")
    log.edit("/work/app/small.py", "a", "b")
    log.edit("/work/app/big.py", "x\ny", "x1\ny1\nz1\nw1")
    b = _board(log.write(tmp_path / "n.jsonl"))
    assert not b["arc"]
    assert [s["file"] for s in b["scenes"] if s["kind"] == "diff"] == ["small.py", "big.py"]
    assert b["scenes"][0]["title"] == "2 files changed"


def test_episode_cuts_unrelated_tasks(log, tmp_path):
    log.prompt("First, update the README wording for the install section")
    log.edit("/work/app/README.md", "old", "new").say("README updated with the new install steps.")
    log.prompt("Now fix the failing date parser test in utils")
    log.bash("pytest -q", "1 failed, 5 passed", error=True)
    log.edit("/work/app/utils.py", "a", "b").bash("pytest -q", "6 passed").say("Date parser fixed, all six pass.")
    log.prompt("Unrelated: draft the release notes for next week")
    log.say("Release notes drafted in NOTES.md for your review.")
    b = _board(log.write(tmp_path / "ep.jsonl"))
    prompt = next(s for s in b["scenes"] if s["kind"] == "prompt")
    say = next(s for s in b["scenes"] if s["kind"] == "say")
    assert "date parser" in prompt["text"] and "Date parser fixed" in say["text"]
    assert not any(s.get("file") == "README.md" for s in b["scenes"])
    whole = _board(log.write(tmp_path / "ep2.jsonl"), whole=True)
    assert "README" in next(s for s in whole["scenes"] if s["kind"] == "prompt")["text"]


def test_short_prompts_are_not_the_goal(log, tmp_path):
    log.prompt("Make the export button download a CSV of the table")
    log.prompt("ㄱㄱ")
    log.bash("pytest", "1 failed", error=True).edit("/work/app/export.py", "a", "b").bash("pytest", "1 passed")
    b = _board(log.write(tmp_path / "g.jsonl"))
    assert "CSV" in next(s for s in b["scenes"] if s["kind"] == "prompt")["text"]


def test_active_time_ignores_breaks(log, tmp_path):
    log.prompt("Start the migration of the user table", dt=0).bash("ls", dt=60).bash("ls", dt=3 * 86400).bash("ls", dt=120)
    s = ingest.load(log.write(tmp_path / "t.jsonl"))
    assert 60 + 15 * 60 + 120 <= story.active_seconds(s.events) <= 60 + 15 * 60 + 120 + 20


def test_captions_in_korean(arc_session):
    b = _board(arc_session, lang="ko")
    assert any("실패" in s.get("caption", "") for s in b["scenes"])
    assert b["scenes"][-1]["text"].endswith("sessionreel")


def test_empty_session(log, tmp_path):
    b = _board(log.write(tmp_path / "empty.jsonl"))
    assert [s["kind"] for s in b["scenes"]] == ["title", "stats", "end"]


# ---- regressions from the pre-release review ------------------------------------------------

def _ev(cmd, out, err=False, has_result=True):
    return Event("tool", tool="Bash", input={"command": cmd}, output=out, error=err, has_result=has_result)


@pytest.mark.parametrize("out,err,has", [
    ("Command running in background with ID: bash_1", False, True),
    ("The user doesn't want to proceed with this tool use. The tool use was rejected", True, True),
    ("", False, False),                  # pending / truncated log: no result
    ("collected 0 items", False, True),  # ran, but no pass signal
])
def test_no_verdict_is_not_a_pass_or_a_fail(out, err, has):
    assert story.parse_check(_ev("pytest -q", out, err, has), 0) is None


def test_ruff_fix_with_nothing_remaining_is_green():
    r = story.parse_check(_ev("ruff check --fix .", "Found 3 errors (3 fixed, 0 remaining)."), 0)
    assert r.ok and r.errors == 0


def test_ruff_subcommands_are_different_checks():
    assert story.check_family("ruff check a.py") == "ruff check"
    assert story.check_family("ruff format b.py") == "ruff format"


def test_green_must_not_be_narrower_than_red(log, tmp_path):
    log.prompt("Fix the parser failures in the test suite please")
    log.bash("pytest -q", "5 failed, 20 passed", error=True)
    log.edit("/work/app/parser.py", "a", "b")
    log.bash("pytest -q tests/test_parser.py -k empty", "1 passed, 24 deselected")
    b = _board(log.write(tmp_path / "narrow.jsonl"))
    assert not b["arc"] and "5 failed → 1 passed" not in b["scenes"][0]["title"]


def test_green_with_same_selectors_pairs(log, tmp_path):
    log.prompt("Fix the parser failures in the test suite please")
    log.bash("pytest -q tests/test_parser.py", "2 failed, 3 passed", error=True)
    log.edit("/work/app/parser.py", "a", "b")
    log.bash("pytest -q tests/test_parser.py", "5 passed")
    assert _board(log.write(tmp_path / "same.jsonl"))["scenes"][0]["title"] == "2 failed → 5 passed"


def test_background_green_is_not_an_arc(log, tmp_path):
    log.prompt("Fix the parser failures in the test suite please")
    log.bash("pytest -q", "5 failed", error=True).edit("/work/app/p.py", "a", "b")
    log.bash("pytest -q", "Command running in background with ID: bash_1")
    assert not _board(log.write(tmp_path / "bg.jsonl"))["arc"]


@pytest.mark.parametrize("cmd,actions", [
    ("git add -A && git commit -m 'x' && git push", ["commit", "push"]),
    ("git -C repo push origin main", ["push"]),
    ("git push --dry-run origin main", []),
    ("grep -rn \"git push\" docs/", []),
    ("python3 - <<'EOF'\nimport os\nos.system('git commit -m x')\nEOF", []),
    ("gh pr create --fill", ["pr"]),
])
def test_ship_actions(cmd, actions):
    assert [a for a, _ in story.ship_actions(cmd)] == actions


def test_commit_only_is_not_called_shipped(arc_session):
    b = _board(arc_session)
    ship = next(s for s in b["scenes"] if s["kind"] == "ship")
    assert ship["caption"] == "Committed" and ship["message"] == "parser: skip empty lines"


def test_commit_message_is_subject_line_only():
    assert story._commit_message('git commit -m "Subject line\n\nBody text\nCo-Authored-By: X"') == "Subject line"


def test_teammate_messages_are_not_the_ask(log, tmp_path):
    log.prompt("Another Claude session sent a message: <teammate-message>do x</teammate-message>")
    log.prompt("Please fix the login redirect loop on the settings page")
    log.edit("/work/app/auth.py", "a", "b")
    b = _board(log.write(tmp_path / "tm.jsonl"))
    assert "login redirect" in next(s for s in b["scenes"] if s["kind"] == "prompt")["text"]


def test_write_line_counts_are_not_capped(log, tmp_path):
    body = "\n".join(f"x{i} = {i}" for i in range(1000))
    log.prompt("Generate the lookup table module from the spec")
    log.tool("Write", {"file_path": "/work/app/table.py", "content": body}, "ok")
    b = _board(log.write(tmp_path / "big.jsonl"))
    stats = dict(next(s for s in b["scenes"] if s["kind"] == "stats")["items"])
    assert stats["lines"] == "+1000 −0"
    assert next(s for s in b["scenes"] if s["kind"] == "diff")["added"] == 1000


def test_project_and_branch_overrides(arc_session):
    b = _board(arc_session, project_name="client-app", show_branch=False)
    assert b["scenes"][0]["project"] == "client-app" and b["scenes"][0]["branch"] == ""


def test_commands_after_a_heredoc_still_count():
    cmd = "cd repo && python3 - <<'PYEOF'\nprint('pytest inside is data')\nPYEOF\n.venv/bin/python -m pytest -q 2>&1 | tail -3"
    assert story.check_family(cmd) == "pytest"
    assert story.ship_actions("cat > f <<EOF\ngit push\nEOF\ngit push origin main")[0][0] == "push"


def test_python_dash_m_is_not_a_selector():
    r = story.parse_check(Event("tool", tool="Bash", input={"command": ".venv/bin/python -m pytest -q"},
                                output="95 passed", has_result=True), 0)
    assert r.selectors == ()


def test_fix_caption_only_for_files_the_failure_names(log, tmp_path):
    log.prompt("Fix the failing parser test and tidy the docs while you are at it")
    log.bash("pytest -q", "FAILED tests/test_parser.py::test_empty - parser.py:12 IndexError\n1 failed, 3 passed", error=True)
    log.edit("/work/app/docs/notes.md", "a\nb\nc", "a\nb\nc\nd\ne\nf\ng")
    log.edit("/work/app/parser.py", "x", "y")
    log.bash("pytest -q", "4 passed")
    b = _board(log.write(tmp_path / "fixname.jsonl"))
    caps = {s["file"]: s["caption"] for s in b["scenes"] if s["kind"] == "diff"}
    assert caps["parser.py"].startswith("Fix in") and caps["docs/notes.md"].startswith("Changed")
