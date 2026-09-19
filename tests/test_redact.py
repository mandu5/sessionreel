import pytest

from sessionreel import ingest
from sessionreel.redact import Redactor, is_secret_file, redact_session

LEAKS = [
    ("sk" "-ant-api03-AbCdEfGhIjKlMnOpQrStUv", "anthropic-key"),
    ("sk" "-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456", "openai-key"),
    ("gh" "p_AbCdEfGhIjKlMnOpQrStUvWxYz1234", "github-token"),
    ("gi" "thub_pat_11ABCDEFG0123456789_abcdefghijkl", "github-token"),
    ("AK" "IAIOSFODNN7EXAMPLE", "aws-key"),
    ("xo" "xb-1234567890-abcdefghij", "slack-token"),
    ("AI" "zaSyA1234567890abcdefghijklmnopqrstuv", "google-key"),
    ("hf" "_abcdefghijklmnopqrstuvwxyz1234567", "hf-token"),
    ("ey" "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
    ("Authorization: Be" "arer abcdefghijklmnop1234", "bearer"),
    ("ht" "tps://user:hunter2pass@db.example.com/x", "url-credentials"),
    ("https://api.example.com/v1?ap" "i_key=abcdef123456&x=1", "url-token"),
    ("OP" "ENAI_API_KEY=abcdef1234567890", "assignment"),
    ('DB' '_PASSWORD: "correct-horse-battery"', "assignment"),
    ("mail me at someone@example.org please", "email"),
    ("-----BE" "GIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "private-key"),
]


SECRETS = {'sk' '-ant-api03-AbCdEfGhIjKlMnOpQrStUv': 'MnOpQrStUv', 'sk' '-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456': 'WxYz123456', 'gh' 'p_AbCdEfGhIjKlMnOpQrStUvWxYz1234': 'WxYz1234', 'gi' 'thub_pat_11ABCDEFG0123456789_abcdefghijkl': 'abcdefghijkl', 'AK' 'IAIOSFODNN7EXAMPLE': 'IOSFODNN7', 'xo' 'xb-1234567890-abcdefghij': 'abcdefghij', 'AI' 'zaSyA1234567890abcdefghijklmnopqrstuv': 'mnopqrstuv', 'hf' '_abcdefghijklmnopqrstuvwxyz1234567': 'xyz1234567', 'ey' 'JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U': 'THsR8U', 'Authorization: Be' 'arer abcdefghijklmnop1234': 'mnop1234', 'ht' 'tps://user:hunter2pass@db.example.com/x': 'hunter2pass', 'https://api.example.com/v1?ap' 'i_key=abcdef123456&x=1': 'abcdef123456', 'OP' 'ENAI_API_KEY=abcdef1234567890': 'abcdef1234567890', 'DB' '_PASSWORD: "correct-horse-battery"': 'correct-horse', 'mail me at someone@example.org please': 'someone@', '-----BE' 'GIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----': 'MIIEow'}


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
    "def get_ap" "i_key(self):",             # identifier, no value
    "version: 2026.09.18",                # dotted value, not a secret key
    "AK" "IA",                               # prefix alone
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
    log.tool("Read", {"file_path": "/work/app/.env"}, "OP" "ENAI_API_KEY=sk-live-1\nX=1")
    log.edit("/work/app/.env", "X=1", "X=2")
    s = redact_session(ingest.load(log.write(tmp_path / "e.jsonl")), home="/x")
    assert all(e.output in ("[contents hidden: secret file]",) and not e.hunks for e in s.tools)
    assert s.redactions["secret-file"] == 2


def test_every_string_field_is_redacted(log, tmp_path):
    key = "gh" "p_AbCdEfGhIjKlMnOpQrStUvWxYz1234"
    log.prompt(f"use {key} to push").bash(f"GH_TOKEN={key} gh pr create", f"token {key}")
    log.edit("/work/app/ci.yml", "token: old", f"token: {key}").say(f"pushed with {key}")
    s = redact_session(ingest.load(log.write(tmp_path / "r.jsonl")), home="/x")
    blob = repr([(e.text, e.input, e.output, [h.lines for h in e.hunks]) for e in s.events])
    assert key not in blob


# ---- regressions from the pre-release review ------------------------------------------------

REVIEW_LEAKS = [
    ('{"ap" "i_key": "abcd1234efgh5678"}', "abcd1234efgh5678"),
    ('{"AW" "S_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}', "wJalrXUtnFEMI"),
    ("sk" "_live_51H8abcdefghijklmnop", "51H8abcdefgh"),
    ("STRIPE_KEY=rk" "_live_abcdefghijk", "abcdefghijk"),
    ("my" "sql -uroot -pS3cretPw db", "S3cretPw"),
    ("cu" "rl -u admin:S3cretPw https://x", "S3cretPw"),
    ("tool --" "password S3cretPw", "S3cretPw"),
    ("Authorization: Ba" "sic dXNlcjpwYXNzd29yZA==", "dXNlcjpw"),
    ("Authorization: Be" "arer abc/def+ghijklmnopqrstuv", "ghijklmnop"),
    ("np" "m_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnop"),
    ("py" "pi-AgEIcHlwaS5vcmcCJGFiY2RlZmdoaWprbG1ub3A", "AgEIcHlwaS5v"),
    ("gl" "pat-abcdefghijklmnopqrst", "abcdefghijklmnop"),
    ("SG" ".abcdefghijklmnopqr.abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqr"),
    ("https://ho" "oks.slack.com/services/T000/B000/XXXXYYYYZZZZ", "XXXXYYYYZZZZ"),
    ("https://di" "scord.com/api/webhooks/123/abcDEF", "abcDEF"),
    ("https://ap" "i.telegram.org/bot123456:ABCdefGHI/sendMessage", "ABCdefGHI"),
    ("DefaultEndpointsProtocol=https;Ac" "countKey=abcdEFGH1234ijklMNOP==;", "abcdEFGH1234"),
    ("SE" "SSION_SIGNING=0123456789abcdef0123456789abcdef", "0123456789abcdef0123"),
    ("export X=Zm9vYmFyQmF6UXV4MTIzNDU2Nzg5MEFiQ2RFZg", "Zm9vYmFyQmF6UXV4"),  # high-entropy fallback
]


@pytest.mark.parametrize("text,secret", REVIEW_LEAKS)
def test_review_leaks_are_closed(text, secret):
    assert secret not in Redactor(home="/nonexistent", hostname="zz").text(text)


@pytest.mark.parametrize("text", [
    "author: Youngmin Ko",
    "Co-Authored-By: Claude Fable 5.1",
    'const password = request.form["password"]',
    "commit 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",  # git SHAs are not secrets
    "mkdir -p src/app",
])
def test_review_false_positives_are_gone(text):
    assert Redactor(home="/nonexistent", hostname="zz").text(text) == text


def test_identity_is_removed_in_every_form():
    r = Redactor(home="/Users/alice", hostname="alices-MacBook-Pro.local")
    out = r.text("/Users/alice/x -Users-alice-Documents-GitHub-app/m.md /users/alice/y "
                 "alice@alices-MacBook-Pro ~ % ls -l\ndrwxr-xr-x  4 alice  staff  128 . on alices-MacBook-Pro")
    assert "alice" not in out.lower()
    assert r.text("/Users/alice2/x") == "/Users/alice2/x"  # another user's home is not ours


def test_private_key_body_in_a_diff_is_removed(log, tmp_path):
    key = "-----BE" "GIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo\n-----END RSA PRIVATE KEY-----"
    log.edit("/work/app/config.py", "KEY = None", f'KEY = """{key}"""')
    s = redact_session(ingest.load(log.write(tmp_path / "k.jsonl")), home="/x", hostname="zz")
    assert "MIIEow" not in repr([h.lines for e in s.tools for h in e.hunks])


def test_branch_and_model_are_redacted(log, tmp_path):
    log.lines.append({"type": "user", "cwd": "/w", "gitBranch": "alice@acme.com/sk" "_live_51H8abcdefghijklmnop",
                      "message": {"role": "user", "content": "hello there, please fix the build"}})
    s = redact_session(ingest.load(log.write(tmp_path / "b.jsonl")), home="/x", hostname="zz")
    assert "acme.com" not in s.branch and "51H8" not in s.branch


def test_more_secret_files():
    for f in ["/a/.git-credentials", "/a/.envrc", "/a/prod.tfvars", "/a/x.tfstate", "/a/c.p12",
              "/a/k.pfx", "/k/sa-key.json", "/h/.kube/config", "/h/.docker/config.json", "/h/.aws/credentials"]:
        assert is_secret_file(f), f


@pytest.mark.parametrize("text", ["\\if@neuripsfinal", "reader-001@session-d90ba878", "eval@NeurIPS results", "npm i pkg@latest"])
def test_at_signs_that_are_not_shell_prompts_survive(text):
    assert Redactor(home="/nonexistent", hostname="zz").text(text) == text
