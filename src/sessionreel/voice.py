"""Optional narration with the operating system's own voice: `say` on macOS, `espeak-ng` on Linux.

No cloud TTS, no model download. Each caption becomes one clip; the storyboard stretches a scene
when its clip is longer than the scene, so the voice is never cut off.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .render import ffmpeg_exe


def available() -> str | None:
    for exe in ("say", "espeak-ng", "espeak"):
        if shutil.which(exe):
            return exe
    return None


def _speakable(text: str) -> str:
    text = text.replace("`", "").replace("−", "minus ").replace("→", "then")
    return re.sub(r"\s+", " ", text).strip()


def _clip(text: str, out: Path, engine: str, voice: str | None) -> float:
    raw = out.with_suffix(".aiff" if engine == "say" else ".raw.wav")
    script = out.with_suffix(".txt")
    script.write_text(text, encoding="utf-8")  # a file, never argv: text starting with '-' is not an option
    if engine == "say":
        cmd = ["say", "-o", str(raw), "-f", str(script)] + (["-v", voice] if voice else [])
    else:
        cmd = [engine, "-w", str(raw), "-f", str(script)] + (["-v", voice] if voice else [])
    subprocess.run(cmd, check=True, capture_output=True)
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(raw), "-ar", "44100", "-ac", "1", str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


def narrate(board: dict, voice: str | None = None, pad: float = 0.5) -> tuple[dict, Path]:
    """Speak every scene caption; return the adjusted storyboard and one WAV track aligned to it."""
    engine = available()
    if not engine:
        raise RuntimeError("no system voice found (macOS `say` or `espeak-ng`)")
    tmp = Path(tempfile.mkdtemp(prefix="sessionreel-voice-"))
    parts: list[Path] = []
    for i, sc in enumerate(board["scenes"]):
        text = sc.get("caption") or ""
        if sc.get("kind") == "title":
            text = ". ".join(x for x in (sc.get("project"), sc.get("title")) if x)
        elif sc.get("kind") == "say":
            text = f"{text}: {sc.get('text', '')}"
        seg = tmp / f"s{i:02d}.wav"
        dur = float(sc.get("seconds", 3))
        if text:
            spoken = _clip(_speakable(text), seg, engine, voice)
            dur = max(dur, spoken + pad)
            sc["seconds"] = round(dur, 2)
        # pad each clip with silence to exactly the scene length
        padded = tmp / f"p{i:02d}.wav"
        src = ["-i", str(seg)] if seg.exists() else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *src, "-af", f"apad=whole_dur={dur}",
                        "-t", f"{dur}", "-ar", "44100", "-ac", "1", str(padded)], check=True)
        parts.append(padded)
    listing = tmp / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    track = tmp / "voice.wav"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(track)], check=True)
    return board, track
