"""Build the static documentation site without rendering or reading user sessions.

Only the repository's synthetic demo is copied. No network, model, or renderer calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> None:
    output = output.resolve()
    if output == ROOT or output in (ROOT / "docs", ROOT / "src", ROOT / "scripts"):
        raise ValueError("Choose a separate output directory, for example build/site")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "site.css", "site.js", "icon.svg", "demo.mp4", "demo.gif"):
        shutil.copyfile(ROOT / "docs" / name, output / name)
    shutil.copytree(ROOT / "docs" / "assets", output / "assets", dirs_exist_ok=True)
    source = ROOT / "src/sessionreel/demo/demo-session.jsonl"
    shutil.copyfile(source, output / "assets/demo-session.jsonl")
    artifacts = ("docs/demo.mp4", "docs/demo.gif", "src/sessionreel/demo/demo-session.jsonl")
    manifest = {
        "description": "Original repository demo assets; the session is synthetic.",
        "chapter_seeks": "Six equal video-time spans, not original session timestamps.",
        "sources": [
            {"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
            for name in artifacts
        ],
    }
    (output / "assets/provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Static site ready: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/site")
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
