from sessionreel import ingest


def test_events_and_join(arc_session):
    s = ingest.load(arc_session)
    kinds = [e.kind for e in s.events]
    assert kinds[0] == "prompt" and kinds[-1] == "say"
    bash = [e for e in s.tools if e.tool == "Bash"]
    assert bash[0].error and "1 failed" in bash[0].output
    assert not bash[1].error and bash[1].output.endswith("3 passed in 0.1s")
    edit = next(e for e in s.tools if e.tool == "Edit")
    assert edit.file == "/work/app/parser.py" and edit.hunks[0].lines[-1] == "+    return line.split(',')"
    assert s.cwd == "/work/app" and s.model == "claude-opus-5" and s.branch == "main"


def test_harness_wrappers_are_not_prompts(log, tmp_path):
    log.prompt("<command-name>/model</command-name>").prompt("Caveat: the messages below")
    log.prompt("real ask here", isMeta=False).prompt("<system-reminder>x</system-reminder>")
    log.prompt("meta", isMeta=True)
    s = ingest.load(log.write(tmp_path / "w.jsonl"))
    assert [e.text for e in s.prompts] == ["real ask here"]


def test_malformed_and_truncated_lines_are_skipped(log, tmp_path):
    log.prompt("hello there friend").raw("{not json").raw('{"type": "assistant", "mess')
    s = ingest.load(log.write(tmp_path / "m.jsonl"))
    assert s.skipped_lines == 2 and len(s.prompts) == 1


def test_sidechains_are_ignored(log, tmp_path):
    log.prompt("main thread ask").tool("Bash", {"command": "rm -rf /"}, "", sidechain=True)
    s = ingest.load(log.write(tmp_path / "sc.jsonl"))
    assert s.tools == []


def test_write_without_patch_becomes_all_added(log, tmp_path):
    log.tool("Write", {"file_path": "/w/a.py", "content": "a = 1\nb = 2"}, "ok")
    s = ingest.load(log.write(tmp_path / "wr.jsonl"))
    assert s.tools[0].hunks[0].lines == ["+a = 1", "+b = 2"]


def test_encode_cwd_matches_claude_code_directory_names():
    assert ingest.encode_cwd("/Users/me/Documents/GitHub/job-radar") == "-Users-me-Documents-GitHub-job-radar"
    assert ingest.encode_cwd("/Users/me/Downloads/1. 커리어") == "-Users-me-Downloads-1-----"


def test_find_session_by_prefix(tmp_path, arc_session):
    root = tmp_path / "projects"
    (root / "-work-app").mkdir(parents=True)
    target = root / "-work-app" / "abcd1234-0000.jsonl"
    target.write_text(arc_session.read_text())
    assert ingest.find_session("abcd", root=root) == target
