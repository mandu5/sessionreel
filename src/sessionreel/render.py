"""Draw a storyboard into video frames and stream them to ffmpeg.

One design language for every scene: a dark stage, a headline caption, one content window
(terminal, editor or card) and a thin progress rail. Motion is short and eased — things arrive,
they do not dance. Everything is drawn with Pillow; there is no browser and no Node.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
FADE = 0.35  # seconds of crossfade between scenes

FORMATS = {"square": (1080, 1080), "wide": (1920, 1080), "tall": (1080, 1920)}

# palette
BG = (11, 13, 18)
BG2 = (20, 24, 33)
PANEL = (17, 20, 28)
PANEL_EDGE = (38, 44, 58)
TEXT = (230, 233, 240)
MUTED = (138, 147, 166)
DIM = (86, 94, 112)
RED = (255, 99, 99)
GREEN = (61, 220, 151)
AMBER = (255, 196, 87)
BLUE = (110, 168, 254)
VIOLET = (178, 140, 255)
ADD_BG = (20, 58, 43)
DEL_BG = (70, 25, 30)

SYNTAX = {
    "Keyword": (198, 146, 255), "Name.Function": (110, 180, 255), "Name.Class": (255, 203, 107),
    "Name.Builtin": (130, 200, 255), "String": (170, 220, 140), "Number": (255, 170, 110),
    "Comment": (110, 120, 140), "Operator": (180, 190, 210), "Name.Decorator": (255, 150, 200),
}


# ---------------------------------------------------------------- fonts

def _font_path(name: str) -> str:
    return str(resources.files("sessionreel").joinpath("fonts", name))


FONT_FILES = {
    "mono": "JetBrainsMono-Regular.ttf", "mono-bold": "JetBrainsMono-Bold.ttf",
    "ui": "Inter-Regular.ttf", "ui-semi": "Inter-SemiBold.ttf", "display": "InterDisplay-Bold.ttf",
    "ko": "Pretendard-Regular.otf", "ko-bold": "Pretendard-Bold.otf", "emoji": "NotoEmoji.ttf",
}
_KO_FOR = {"mono": "ko", "mono-bold": "ko-bold", "ui": "ko", "ui-semi": "ko-bold", "display": "ko-bold"}


@lru_cache(maxsize=256)
def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(FONT_FILES[key]), size)


def _needs_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xAC00 <= o <= 0xD7AF  # Hangul
            or 0x3000 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xFF00 <= o <= 0xFFEF)


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o == 0x200D


def _runs(text: str, key: str) -> list[tuple[str, str]]:
    """Split text into (font key, substring) runs: Hangul/CJK → Pretendard, emoji → Noto Emoji."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        if ch in "\ufe0f\ufe0e":  # variation selectors: no glyph of their own
            continue
        k = "emoji" if _is_emoji(ch) else _KO_FOR.get(key, key) if _needs_cjk(ch) else key
        if runs and runs[-1][0] == k:
            runs[-1] = (k, runs[-1][1] + ch)
        else:
            runs.append((k, ch))
    return runs


@lru_cache(maxsize=1 << 16)
def text_width(text: str, key: str, size: int) -> float:
    return sum(font(k, size).getlength(s) for k, s in _runs(text, key))


def draw_text(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, key: str, size: int,
              fill: tuple[int, ...]) -> float:
    x, y = xy
    for k, s in _runs(text, key):
        f = font(k, size)
        # Pretendard sits higher than Inter at the same size; nudge so baselines line up.
        dy = size * 0.06 if k.startswith("ko") and not key.startswith("ko") else size * 0.1 if k == "emoji" else 0
        d.text((x, y + dy), s, font=f, fill=fill)
        x += f.getlength(s)
    return x


def wrap(text: str, key: str, size: int, width: float, max_lines: int = 99) -> list[str]:
    """Greedy wrap on spaces; CJK text (no spaces) wraps per character."""
    return list(_wrap(text, key, size, float(width), max_lines))


@lru_cache(maxsize=4096)
def _wrap(text: str, key: str, size: int, width: float, max_lines: int) -> tuple[str, ...]:
    lines: list[str] = []
    for para in text.split("\n"):
        tokens = re.findall(r"\S+\s*|\s+", para) if " " in para else list(para)
        cur = ""
        for tok in tokens:
            if text_width(cur + tok, key, size) <= width or not cur:
                cur += tok
                while text_width(cur, key, size) > width and len(cur) > 1:  # a single over-long token
                    cut = len(cur)
                    while cut > 1 and text_width(cur[:cut], key, size) > width:
                        cut -= 1
                    lines.append(cur[:cut])
                    cur = cur[cut:]
            else:
                lines.append(cur.rstrip())
                cur = tok.lstrip()
        lines.append(cur.rstrip())
    lines = [ln for ln in lines if ln or len(lines) == 1]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_width(last + "…", key, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return tuple(lines)


def fit(text: str, key: str, size: int, width: float) -> str:
    if text_width(text, key, size) <= width:
        return text
    while text and text_width(text + "…", key, size) > width:
        text = text[:-1]
    return text + "…"


# ---------------------------------------------------------------- motion

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease_out(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def phase(t: float, start: float, dur: float) -> float:
    return ease_out((t - start) / dur) if dur > 0 else float(t >= start)


def mix(a: tuple[int, ...], b: tuple[int, ...], k: float) -> tuple[int, ...]:
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b, strict=False))


# ---------------------------------------------------------------- stage

@dataclass
class Stage:
    w: int
    h: int
    project: str
    total: float

    @property
    def s(self) -> float:
        """Scale factor relative to the 1080-px short side."""
        return min(self.w, self.h) / 1080

    @property
    def margin(self) -> int:
        return int(64 * self.s)

    def px(self, v: float) -> int:
        return int(v * self.s)

    @property
    def top_pad(self) -> int:
        """Tall frames: start the content lower so it sits in the middle of the phone screen."""
        return int((self.h - self.w) * 0.3) if self.h > self.w else 0


@lru_cache(maxsize=8)
def _background(w: int, h: int) -> Image.Image:
    """Dark stage with a soft glow top-left and a vignette; drawn once per size."""
    img = Image.new("RGB", (w, h), BG)
    glow = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(glow)
    r = int(max(w, h) * 0.55)
    gd.ellipse((-r // 2, -r // 2, r, r), fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(max(w, h) // 8))
    img.paste(Image.new("RGB", (w, h), (40, 52, 90)), (0, 0), glow)
    grid = ImageDraw.Draw(img)
    step = int(min(w, h) / 18)
    for x in range(0, w, step):
        grid.line([(x, 0), (x, h)], fill=(15, 18, 25))
    for y in range(0, h, step):
        grid.line([(0, y), (w, y)], fill=(15, 18, 25))
    return img


def _chrome(img: Image.Image, st: Stage, t_global: float, label: str) -> ImageDraw.ImageDraw:
    d = ImageDraw.Draw(img)
    m = st.margin
    # top-left brand + project
    y = m - st.px(24)
    d.rounded_rectangle((m, y + st.px(6), m + st.px(14), y + st.px(20)), radius=st.px(4), fill=VIOLET)
    x = draw_text(d, (m + st.px(24), y), "sessionreel", "ui-semi", st.px(22), TEXT)
    draw_text(d, (x + st.px(12), y), "·  " + st.project, "ui", st.px(22), MUTED)
    if label:
        lw = text_width(label, "mono", st.px(18))
        draw_text(d, (st.w - m - lw, y + st.px(3)), label, "mono", st.px(18), DIM)
    # bottom progress rail
    ry = st.h - m + st.px(20)
    d.rounded_rectangle((m, ry, st.w - m, ry + st.px(4)), radius=st.px(2), fill=(30, 35, 47))
    k = clamp(t_global / st.total) if st.total else 0
    d.rounded_rectangle((m, ry, m + (st.w - 2 * m) * k, ry + st.px(4)), radius=st.px(2), fill=VIOLET)
    return d


def _caption(d: ImageDraw.ImageDraw, st: Stage, text: str, t: float, color: tuple[int, ...] = TEXT) -> int:
    """Headline under the brand line. Returns the y where content may start."""
    m = st.margin
    size = st.px(56) if st.w <= st.h else st.px(60)
    lines = wrap(text, "display", size, st.w - 2 * m, max_lines=2)
    k = phase(t, 0.0, 0.45)
    y = m + st.px(44) + st.top_pad + int((1 - k) * st.px(18))
    for ln in lines:
        _draw_inline_code(d, (m, y), ln, size, mix(BG, color, k))
        y += int(size * 1.18)
    return y + st.px(28)


def _draw_inline_code(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, fill: tuple[int, ...]) -> None:
    """Render `code` spans in a caption in the mono face and amber."""
    x, y = xy
    for i, part in enumerate(re.split(r"`", text)):
        if not part:
            continue
        if i % 2:
            x = draw_text(d, (x, y + size * 0.08), part, "mono-bold", int(size * 0.86), mix(BG, AMBER, sum(fill) / max(1, sum(TEXT))))
        else:
            x = draw_text(d, (x, y), part, "display", size, fill)


def _window(img: Image.Image, st: Stage, box: tuple[int, int, int, int], title: str, t: float,
            accent: tuple[int, ...] | None = None) -> tuple[ImageDraw.ImageDraw, tuple[int, int, int, int]]:
    """A macOS-style window that rises into place. Returns the drawer and the inner content box."""
    k = phase(t, 0.08, 0.5)
    x0, y0, x1, y1 = box
    dy = int((1 - k) * st.px(40))
    y0, y1 = y0 + dy, y1 + dy
    r = st.px(18)
    img.paste((0, 0, 0), (0, 0), _shadow(img.size, (x0, y0 + st.px(14), x1, y1 + st.px(14)), r, int(150 * k), st.px(22)))
    d = ImageDraw.Draw(img)
    edge = accent if accent else PANEL_EDGE
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=mix(BG, PANEL, k), outline=mix(BG, edge, k), width=max(1, st.px(2)))
    bar = st.px(52)
    d.line([(x0 + r // 2, y0 + bar), (x1 - r // 2, y0 + bar)], fill=mix(BG, PANEL_EDGE, k), width=1)
    for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        cx, cy = x0 + st.px(28) + i * st.px(22), y0 + bar // 2
        d.ellipse((cx - st.px(7), cy - st.px(7), cx + st.px(7), cy + st.px(7)), fill=mix(BG, c, k))
    tw = text_width(title, "mono", st.px(20))
    draw_text(d, ((x0 + x1) / 2 - tw / 2, y0 + bar // 2 - st.px(12)), fit(title, "mono", st.px(20), x1 - x0 - st.px(200)),
              "mono", st.px(20), mix(BG, MUTED, k))
    return d, (x0 + st.px(28), y0 + bar + st.px(22), x1 - st.px(28), y1 - st.px(22))


@lru_cache(maxsize=64)
def _shadow(size: tuple[int, int], box: tuple[int, int, int, int], radius: int, alpha: int, blur: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=alpha)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def _badge(d: ImageDraw.ImageDraw, st: Stage, xy: tuple[int, int], text: str, color: tuple[int, ...], k: float,
           anchor_right: bool = False) -> None:
    if k <= 0:
        return
    size = st.px(26)
    pad = st.px(16)
    w = text_width(text, "ui-semi", size) + 2 * pad + st.px(22)
    h = st.px(46)
    x, y = xy
    if anchor_right:
        x -= w
    sc = 0.85 + 0.15 * k
    cx, cy = x + w / 2, y + h / 2
    bw, bh = w * sc, h * sc
    d.rounded_rectangle((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2), radius=int(bh / 2),
                        fill=mix(BG, mix(color, BG, 0.78), k), outline=mix(BG, color, k), width=max(1, st.px(2)))
    dot = st.px(6)
    d.ellipse((x + pad - dot / 2 + st.px(4), cy - dot, x + pad + dot * 1.5 + st.px(4) - dot / 2, cy + dot), fill=mix(BG, color, k))
    draw_text(d, (x + pad + st.px(22), cy - size * 0.62), text, "ui-semi", size, mix(BG, color, k))


# ---------------------------------------------------------------- scenes

SceneFn = Callable[[Image.Image, Stage, dict, float, float], None]


def _content_box(st: Stage, top: int, content_h: int | None = None) -> tuple[int, int, int, int]:
    """The window rectangle. With `content_h`, the window hugs its content (plus title bar and
    padding) and sits in the upper third of the free space instead of stretching to the rail."""
    m = st.margin
    bottom = st.h - m - st.px(10) - (st.top_pad if st.h > st.w else 0)
    if content_h is None:
        return (m, top, st.w - m, bottom)
    h = min(bottom - top, content_h + st.px(52 + 44))
    y = top + int((bottom - top - h) * 0.25)
    return (m, y, st.w - m, y + h)


def scene_title(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    m = st.margin
    k1, k2, k3 = phase(t, 0.1, 0.6), phase(t, 0.35, 0.6), phase(t, 0.6, 0.6)
    size = st.px(112)
    y = st.h * 0.34
    draw_text(d, (m, y - (1 - k1) * st.px(24)), fit(sc.get("project", ""), "display", size, st.w - 2 * m),
              "display", size, mix(BG, TEXT, k1))
    sub = sc.get("title") or ""
    if " → " in sub:
        # the hook: red state → green state
        left, right = sub.split(" → ", 1)
        hs = st.px(52)
        yy = y + size * 1.25
        x = draw_text(d, (m, yy), left, "display", hs, mix(BG, RED, k2))
        x = draw_text(d, (x + st.px(18), yy), "→", "display", hs, mix(BG, MUTED, k2))
        draw_text(d, (x + st.px(18), yy), right, "display", hs, mix(BG, GREEN, phase(t, 0.7, 0.5)))
    elif sub:
        lines = wrap(sub, "ui", st.px(40), st.w - 2 * m, max_lines=2)
        yy = y + size * 1.2
        for ln in lines:
            draw_text(d, (m, yy), ln, "ui", st.px(40), mix(BG, MUTED, k2))
            yy += st.px(52)
    meta = [v for v in (sc.get("date"), sc.get("duration"), _model_name(sc.get("model", "")), sc.get("branch")) if v]
    x = m
    yb = st.h * 0.68
    for i, v in enumerate(meta):
        kk = phase(t, 0.6 + 0.12 * i, 0.5)
        tw = text_width(v, "mono", st.px(24))
        d.rounded_rectangle((x, yb, x + tw + st.px(32), yb + st.px(50)), radius=st.px(25),
                            outline=mix(BG, PANEL_EDGE, kk), fill=mix(BG, PANEL, kk), width=max(1, st.px(2)))
        draw_text(d, (x + st.px(16), yb + st.px(10)), v, "mono", st.px(24), mix(BG, TEXT if i == 0 else MUTED, kk))
        x += tw + st.px(48)
        if x > st.w - m - st.px(160):
            x, yb = m, yb + st.px(66)
    d.rectangle((m, y - st.px(40), m + st.px(90) * k3, y - st.px(34)), fill=VIOLET)


def _model_name(model: str) -> str:
    m = re.sub(r"^claude-", "", model or "")
    m = re.sub(r"-\d{8}$", "", m)
    return m.replace("-", " ").title().replace(" ", " ") if m else ""


def scene_prompt(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t)
    size = st.px(40)
    text = sc.get("text", "")
    inner_w = st.w - 2 * st.margin - st.px(56) - st.px(40)
    full = wrap(text, "ui", size, inner_w, max_lines=12)
    box = _content_box(st, top, int(len(full) * size * 1.45) + st.px(10))
    d, (x0, y0, x1, y1) = _window(img, st, box, "you", t)
    typed = int(len(text) * clamp((t - 0.45) / max(0.8, dur * 0.55)))
    lines = wrap(text[:typed], "ui", size, x1 - x0 - st.px(40), max_lines=int((y1 - y0 - st.px(20)) / (size * 1.45)))
    draw_text(d, (x0, y0 + st.px(4)), "›", "mono-bold", size, VIOLET)
    y = y0
    for ln in lines:
        draw_text(d, (x0 + st.px(40), y), ln, "ui", size, TEXT)
        y += int(size * 1.45)
    if typed < len(text) or int(t * 2) % 2 == 0:
        cx = x0 + st.px(40) + (text_width(lines[-1], "ui", size) if lines else 0) + st.px(4)
        cy = y - int(size * 1.45) if lines else y
        d.rectangle((cx, cy + st.px(6), cx + st.px(4), cy + size + st.px(4)), fill=VIOLET)


def scene_montage(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t)
    files = sc.get("files", [])
    size = st.px(28)
    lh = int(size * 1.62)
    box = _content_box(st, top, max(1, len(files)) * lh)
    d, (x0, y0, x1, y1) = _window(img, st, box, "exploring", t)
    rows = max(1, int((y1 - y0) / lh))
    for i, f in enumerate(files[:rows]):
        k = phase(t, 0.35 + i * 0.12, 0.35)
        if k <= 0:
            break
        y = y0 + i * lh
        draw_text(d, (x0 + (1 - k) * st.px(30), y), "Read", "mono-bold", size, mix(PANEL, BLUE, k))
        draw_text(d, (x0 + st.px(96) + (1 - k) * st.px(30), y), fit(f, "mono", size, x1 - x0 - st.px(110)), "mono", size, mix(PANEL, TEXT, k))


def _terminal_lines(st: Stage, sc: dict, width: float) -> list[tuple[str, tuple[int, ...]]]:
    size = st.px(24)
    out: list[tuple[str, tuple[int, ...]]] = []
    for ln in sc.get("output", []):
        color = TEXT
        if re.search(r"FAIL|Error|error|failed|✗|assert", ln):
            color = (255, 140, 140)
        elif re.search(r"passed|PASS|✓|\bok\b", ln):
            color = (140, 235, 185)
        for part in wrap(ln, "mono", size, width, max_lines=2):
            out.append((part, color))
    return out


def scene_terminal(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    status = sc.get("status", "ok")
    color = RED if status == "fail" else GREEN if status == "pass" else BLUE
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t, TEXT)
    size = st.px(24)
    lh = int(size * 1.55)
    cmd = sc.get("command", "")
    inner_w = st.w - 2 * st.margin - st.px(56)
    est = min(3, len(wrap(cmd, "mono", size, inner_w - st.px(40)))) + len(_terminal_lines(st, sc, inner_w))
    box = _content_box(st, top, est * lh + st.px(10) + st.px(70))
    d, (x0, y0, x1, y1) = _window(img, st, box, "terminal", t, accent=mix(PANEL_EDGE, color, phase(t, dur * 0.55, 0.4)))
    typed_k = clamp((t - 0.4) / 0.9)
    cmd_lines = wrap(cmd, "mono", size, x1 - x0 - st.px(40), max_lines=3)
    total = sum(len(c) for c in cmd_lines)
    shown = int(total * typed_k)
    y = y0
    for ln in cmd_lines:
        part = ln[:max(0, shown)]
        shown -= len(ln)
        draw_text(d, (x0, y), "$" if y == y0 else " ", "mono-bold", size, GREEN)
        draw_text(d, (x0 + st.px(32), y), part, "mono", size, TEXT)
        y += lh
    y += st.px(10)
    lines = _terminal_lines(st, sc, x1 - x0)
    room = max(1, int((y1 - y - st.px(70)) / lh))
    lines = lines[-room:]
    reveal = clamp((t - 1.35) / max(0.6, dur * 0.35))
    n = int(len(lines) * reveal + 0.999) if reveal > 0 else 0
    for i, (ln, c) in enumerate(lines[:n]):
        draw_text(d, (x0, y + i * lh), ln, "mono", size, c)
    kb = phase(t, dur * 0.55, 0.35)
    _badge(d, st, (x1, y1 - st.px(46)), sc.get("badge", ""), color, kb, anchor_right=True)


@lru_cache(maxsize=2048)
def _highlight(line: str, filename: str) -> list[tuple[str, tuple[int, ...]]]:
    try:
        from pygments.lexers import get_lexer_for_filename
        from pygments.util import ClassNotFound
        try:
            lexer = get_lexer_for_filename(filename, stripnl=False, ensurenl=False)
        except ClassNotFound:
            return [(line, TEXT)]
        out: list[tuple[str, tuple[int, ...]]] = []
        for ttype, value in lexer.get_tokens(line):
            name = str(ttype).replace("Token.", "")
            color = TEXT
            for key, c in SYNTAX.items():
                if name.startswith(key):
                    color = c
                    break
            out.append((value.replace("\n", ""), color))
        return out
    except Exception:  # noqa: BLE001 — highlighting is decoration, never a failure
        return [(line, TEXT)]


def scene_diff(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t)
    fname = sc.get("file", "")
    lines = sc.get("lines", [])
    size = st.px(26) if len(lines) <= 12 else st.px(23)
    lh = int(size * 1.58)
    box = _content_box(st, top, len(lines) * lh + st.px(64))
    d, (x0, y0, x1, y1) = _window(img, st, box, fname, t)
    room = max(1, int((y1 - y0 - st.px(64)) / lh))
    lines = lines[:room]
    reveal = clamp((t - 0.45) / max(0.8, dur * 0.5))
    n = int(len(lines) * reveal + 0.999) if reveal > 0 else 0
    width = x1 - x0 + st.px(28)
    for i, ln in enumerate(lines[:n]):
        y = y0 + i * lh
        sign = ln[:1]
        body = ln[1:] if sign in "+- " else ln
        if ln == "@@":
            draw_text(d, (x0, y), "⋯", "mono", size, DIM)
            continue
        if sign in "+-":
            bg = ADD_BG if sign == "+" else DEL_BG
            d.rectangle((x0 - st.px(28), y - st.px(3), x0 - st.px(28) + width, y + lh - st.px(5)), fill=bg)
            draw_text(d, (x0 - st.px(18), y), sign, "mono-bold", size, GREEN if sign == "+" else RED)
        x = x0 + st.px(10)
        maxx = x1
        for seg, c in _highlight(body.replace("\t", "    "), fname):
            if x >= maxx:
                break
            seg = fit(seg, "mono", size, maxx - x) if text_width(seg, "mono", size) > maxx - x else seg
            x = draw_text(d, (x, y), seg, "mono", size, c)
    kb = phase(t, dur * 0.6, 0.35)
    stats = f"+{sc.get('added', 0)}  −{sc.get('removed', 0)}"
    _badge(d, st, (x1, y1 - st.px(46)), stats, GREEN, kb, anchor_right=True)


def scene_ship(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t)
    box = _content_box(st, top, st.px(200) if sc.get("message") else st.px(90))
    d, (x0, y0, x1, y1) = _window(img, st, box, "git", t, accent=mix(PANEL_EDGE, VIOLET, phase(t, 1.0, 0.4)))
    size = st.px(26)
    k = phase(t, 0.45, 0.5)
    for i, ln in enumerate(wrap(sc.get("command", ""), "mono", size, x1 - x0 - st.px(40), max_lines=2)):
        draw_text(d, (x0, y0 + i * st.px(42)), ("$ " if i == 0 else "  ") + ln, "mono", size, mix(PANEL, TEXT, k))
    msg = sc.get("message") or ""
    if msg:
        km = phase(t, 0.9, 0.5)
        for i, ln in enumerate(wrap(msg, "ui-semi", st.px(34), x1 - x0, max_lines=2)):
            draw_text(d, (x0, y0 + st.px(110) + i * st.px(46)), ln, "ui-semi", st.px(34), mix(PANEL, VIOLET, km))


def scene_say(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t, MUTED)
    m = st.margin
    size = st.px(50)
    lines = wrap(sc.get("text", ""), "ui-semi", size, st.w - 2 * m - st.px(40), max_lines=5)
    k = phase(t, 0.3, 0.6)
    y = top + st.px(30)
    d.rectangle((m, y, m + st.px(6), y + len(lines) * int(size * 1.3)), fill=mix(BG, VIOLET, k))
    for ln in lines:
        draw_text(d, (m + st.px(40), y + (1 - k) * st.px(20)), ln, "ui-semi", size, mix(BG, TEXT, k))
        y += int(size * 1.3)


def scene_stats(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    top = _caption(d, st, sc.get("caption", ""), t)
    m = st.margin
    items = sc.get("items", [])
    cols = 2 if st.w <= st.h * 1.2 else 3
    gap = st.px(24)
    cw = (st.w - 2 * m - gap * (cols - 1)) / cols
    ch = st.px(150)
    for i, (label, value) in enumerate(items):
        k = phase(t, 0.3 + i * 0.1, 0.45)
        r, c = divmod(i, cols)
        x, y = m + c * (cw + gap), top + r * (ch + gap) + (1 - k) * st.px(20)
        if y + ch > st.h - m:
            break
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=st.px(18), fill=mix(BG, PANEL, k), outline=mix(BG, PANEL_EDGE, k), width=max(1, st.px(2)))
        draw_text(d, (x + st.px(26), y + st.px(22)), label.upper(), "ui-semi", st.px(20), mix(BG, MUTED, k))
        shown = _count_up(str(value), phase(t, 0.35 + i * 0.1, 0.9))
        color = GREEN if re.search(r"passing|통과", value) or value.startswith("+") else TEXT
        draw_text(d, (x + st.px(26), y + st.px(60)), fit(shown, "display", st.px(54), cw - st.px(40)), "display", st.px(54), mix(BG, color, k))


def _count_up(value: str, k: float) -> str:
    """Animate the first integer in a value from 0; units and other text stay put."""
    m = re.search(r"\d[\d,]*", value)
    if not m or k >= 1:
        return value
    n = int(m.group(0).replace(",", ""))
    return value[:m.start()] + f"{round(n * k):,}" + value[m.end():]


def scene_end(img: Image.Image, st: Stage, sc: dict, t: float, dur: float) -> None:
    d = ImageDraw.Draw(img)
    k = phase(t, 0.1, 0.6)
    size = st.px(76)
    name = "sessionreel"
    w = text_width(name, "display", size)
    x, y = (st.w - w) / 2, st.h * 0.42
    d.rounded_rectangle((x - st.px(58), y + st.px(18), x - st.px(22), y + st.px(54)), radius=st.px(9), fill=mix(BG, VIOLET, k))
    draw_text(d, (x, y), name, "display", size, mix(BG, TEXT, k))
    sub = sc.get("text", "")
    k2 = phase(t, 0.4, 0.6)
    for i, ln in enumerate(wrap(sub, "ui", st.px(30), st.w - 2 * st.margin, max_lines=2)):
        lw = text_width(ln, "ui", st.px(30))
        draw_text(d, ((st.w - lw) / 2, y + size * 1.45 + i * st.px(42)), ln, "ui", st.px(30), mix(BG, MUTED, k2))
    url = "github.com/mandu5/sessionreel"
    uw = text_width(url, "mono", st.px(26))
    draw_text(d, ((st.w - uw) / 2, y + size * 1.45 + st.px(110)), url, "mono", st.px(26), mix(BG, VIOLET, phase(t, 0.7, 0.6)))


SCENES: dict[str, SceneFn] = {
    "title": scene_title, "prompt": scene_prompt, "montage": scene_montage, "terminal": scene_terminal,
    "diff": scene_diff, "ship": scene_ship, "say": scene_say, "stats": scene_stats, "end": scene_end,
}
CHROMELESS = {"title", "end"}


# ---------------------------------------------------------------- timeline

def frames(board: dict, fmt: str = "square", fps: int = FPS) -> Iterator[Image.Image]:
    w, h = FORMATS[fmt]
    scenes = [s for s in board["scenes"] if s.get("kind") in SCENES]
    total = sum(float(s.get("seconds", 3)) for s in scenes)
    project = next((s.get("project", "") for s in scenes if s["kind"] == "title"), "") or "session"
    st = Stage(w, h, project, total)

    def draw(i: int, t_local: float, t_global: float) -> Image.Image:
        sc = scenes[i]
        img = _background(w, h).copy()
        dur = float(sc.get("seconds", 3))
        if sc["kind"] not in CHROMELESS:
            n = sum(1 for s in scenes[:i + 1] if s["kind"] not in CHROMELESS)
            m = sum(1 for s in scenes if s["kind"] not in CHROMELESS)
            _chrome(img, st, t_global, f"{n:02d}/{m:02d}")
        SCENES[sc["kind"]](img, st, sc, t_local, dur)
        return img

    t0 = 0.0
    for i, sc in enumerate(scenes):
        dur = float(sc.get("seconds", 3))
        count = max(1, round(dur * fps))
        for f in range(count):
            tl = f / fps
            frame = draw(i, tl, t0 + tl)
            left = dur - tl
            if left < FADE and i + 1 < len(scenes):
                k = ease_in_out(1 - left / FADE)
                frame = Image.blend(frame, draw(i + 1, 0.0, t0 + dur), k)
            yield frame
        t0 += dur


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("ffmpeg not found: install it (brew install ffmpeg / apt install ffmpeg) "
                           "or `pip install imageio-ffmpeg`") from e


def render(board: dict, out: str | Path, fmt: str = "square", fps: int = FPS, audio: str | Path | None = None,
           progress: Callable[[int, int], None] | None = None) -> Path:
    if not board.get("redacted"):
        raise ValueError("refusing to render a storyboard that was not redacted")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = FORMATS[fmt]
    total = sum(max(1, round(float(s.get("seconds", 3)) * fps)) for s in board["scenes"] if s.get("kind") in SCENES)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-i", str(audio), "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
            "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for i, frame in enumerate(frames(board, fmt, fps)):
            proc.stdin.write(frame.tobytes())
            if progress:
                progress(i + 1, total)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[:500]}")
    return out


def to_gif(mp4: str | Path, gif: str | Path, width: int = 640, fps: int = 15) -> Path:
    vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=sierra2_4a"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(mp4), "-vf", vf, str(gif)], check=True)
    return Path(gif)


def still(board: dict, scene_index: int, t: float, fmt: str = "square") -> Image.Image:
    """One frame of one scene — for previews and tests."""
    w, h = FORMATS[fmt]
    scenes = [s for s in board["scenes"] if s.get("kind") in SCENES]
    total = sum(float(s.get("seconds", 3)) for s in scenes)
    project = next((s.get("project", "") for s in scenes if s["kind"] == "title"), "") or "session"
    st = Stage(w, h, project, total)
    img = _background(w, h).copy()
    sc = scenes[scene_index]
    if sc["kind"] not in CHROMELESS:
        _chrome(img, st, sum(float(s.get("seconds", 3)) for s in scenes[:scene_index]) + t, "")
    SCENES[sc["kind"]](img, st, sc, t, float(sc.get("seconds", 3)))
    return img

