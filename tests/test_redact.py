import pytest

from sessionreel import ingest
from sessionreel.redact import Redactor, is_secret_file, redact_session

LEAKS = [
    ("sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv", "anthropic-key"),
    ("sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456", "openai-key"),
    ("ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234", "github-token"),
    ("github_pat_11ABCDEFG0123456789_abcdefghijkl", "github-token"),
    ("AKIAIOSFODNN7EXAMPLE", "aws-key"),
    ("xoxb-1234567890-abcdefghij", "slack-token"),
    ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "google-key"),
    ("hf_abcdefghijklmnopqrstuvwxyz1234567", "hf-token"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
    ("Authorization: Bearer abcdefghijklmnop1234", "bearer"),
    ("https://user:hunter2pass@db.example.com/x", "url-credentials"),
    ("https://api.example.com/v1?api_key=abcdef123456&x=1", "url-token"),
    ("OPENAI_API_KEY=abcdef1234567890", "assignment"),
    ('DB_PASSWORD: "correct-horse-battery"', "assignment"),
    ("mail me at someone@example.org please", "email"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "private-key"),
]


SECRETS = {'sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv': 'MnOpQrStUv', 'sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456': 'WxYz123456', 'ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234': 'WxYz1234', 'github_pat_11ABCDEFG0123456789_abcdefghijkl': 'abcdefghijkl', 'AKIAIOSFODNN7EXAMPLE': 'IOSFODNN7', 'xoxb-1234567890-abcdefghij': 'abcdefghij', 'AIzaSyA1234567890abcdefghijklmnopqrstuv': 'mnopqrstuv', 'hf_abcdefghijklmnopqrstuvwxyz1234567': 'xyz1234567', 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U': 'THsR8U', 'Authorization: Bearer abcdefghijklmnop1234': 'mnop1234', 'https://user:hunter2pass@db.example.com/x': 'hunter2pass', 'https://api.example.com/v1?api_key=abcdef123456&x=1': 'abcdef123456', 'OPENAI_API_KEY=abcdef1234567890': 'abcdef1234567890', 'DB_PASSWORD: "correct-horse-battery"': 'correct-horse', 'mail me at someone@example.org please': 'someone@', '-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----': 'MIIEow'}


@pytest.mark.parametrize("text,kind", LEAKS)
def test_each_pattern_catches_its_leak(text, kind):
    r = Redactor(home="/nonexistent")
    out = r.text(text)
    assert r.counts[kind] >= 1, (kind, out)
    assert SECRETS[text] not in out, out


NEAR_MISSES = [
    "the token count was 12000",          # word 'token' with a number
    "sk-learn is a library",              # short sk- prefix
    "passed=14 failed=0",                 # key=value that is not a secret
    "def get_api_key(self):",             # identifier, no value
    "version: 2026.09.18",                # dotted value, not a secret key
    "AKIA",                               # prefix alone
]


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_near_misses_survive(text):
    r = Redactor(home="/nonexistent")
    assert r.text(text) == text


def test_home_and_scratch_paths():
    r = Redactor(home="/Users/alice")
    out = r.text("cat /Users/alice/proj/a.py /private/tmp/claude-503/-Users-alice/0f6b2c1e-1234-4abc-9def-0123456789ab/scratchpad/x.txt")
    assert out == "cat ~/proj/a.py $TMP/x.txt"


def test_extra_patterns():
    r = Redactor(extra=[r"ACME-\d+"], home="/x")
    assert r.text("ticket ACME-4411 done") == "ticket [redacted] done"


def test_secret_files_are_hidden(log, tmp_path):
    assert is_secret_file("/a/.env") and is_secret_file("/a/.env.local") and is_secret_file("/k/server.pem")
    assert not is_secret_file("/a/environment.py")
    log.tool("Read", {"file_path": "/work/app/.env"}, "OPENAI_API_KEY=sk-live-1\nX=1")
    log.edit("/work/app/.env", "X=1", "X=2")
    s = redact_session(ingest.load(log.write(tmp_path / "e.jsonl")), home="/x")
    assert all(e.output in ("[contents hidden: secret file]",) and not e.hunks for e in s.tools)
    assert s.redactions["secret-file"] == 2


def test_every_string_field_is_redacted(log, tmp_path):
    key = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234"
    log.prompt(f"use {key} to push").bash(f"GH_TOKEN={key} gh pr create", f"token {key}")
    log.edit("/work/app/ci.yml", "token: old", f"token: {key}").say(f"pushed with {key}")
    s = redact_session(ingest.load(log.write(tmp_path / "r.jsonl")), home="/x")
    blob = repr([(e.text, e.input, e.output, [h.lines for h in e.hunks]) for e in s.events])
    assert key not in blob
