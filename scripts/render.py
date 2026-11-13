#!/usr/bin/env python3
"""
Renders every SVG panel of the solomon-mh profile README.

All text is converted to vector paths at build time, so the images look the
same everywhere GitHub shows them (no web fonts are loaded inside an <img>).

    python scripts/render.py            # render from stats.json
    GITHUB_TOKEN=... python scripts/render.py --refresh   # pull live stats first

Brand: near-black canvas, sky -> green "trace" gradient, Chakra Petch for
display type, JetBrains Mono for anything numeric. Same family as gitTrace.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
ASSETS = ROOT / "assets"
STATS = ROOT / "stats.json"
LOGIN = "solomon-mh"
SINCE = 2020  # freelancing since

# ── palette ────────────────────────────────────────────────────────────────
INK = "#09090B"
SURF = "#121215"
SURF2 = "#1A1A1E"
LINE = "#27272D"
PAPER = "#F4F4F5"
MUTED = "#A1A1AA"
SUBTLE = "#70707A"
SKY = "#38BDF8"
GREEN = "#34D399"


# ── type ───────────────────────────────────────────────────────────────────
def _num(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


class Font:
    def __init__(self, file: str):
        self.tt = TTFont(FONTS / file)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upm = self.tt["head"].unitsPerEm
        self.cap = self.tt["OS/2"].sCapHeight or int(self.upm * 0.7)

    def _glyph(self, ch: str) -> str:
        name = self.cmap.get(ord(ch))
        if name is None:
            raise ValueError(f"glyph {ch!r} missing from font")
        return name

    def width(self, text: str, size: float, tracking: float = 0) -> float:
        adv = sum(self.gs[self._glyph(c)].width for c in text) * size / self.upm
        return adv + tracking * max(len(text) - 1, 0)

    def cap_h(self, size: float) -> float:
        return self.cap * size / self.upm

    def d(self, text: str, size: float, x: float, y: float, tracking: float = 0,
          anchor: str = "start") -> tuple[str, float]:
        w = self.width(text, size, tracking)
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        s = size / self.upm
        pen = SVGPathPen(self.gs, ntos=_num)
        cx = x
        for c in text:
            g = self.gs[self._glyph(c)]
            g.draw(TransformPen(pen, (s, 0, 0, -s, cx, y)))
            cx += g.width * s + tracking
        return pen.getCommands(), w


CHAKRA = Font("chakra-petch-latin-700-normal.woff")
CHAKRA_I = Font("chakra-petch-latin-700-italic.woff")
CHAKRA_SB = Font("chakra-petch-latin-600-normal.woff")
ARCHIVO_I = Font("archivo-latin-900-italic.woff")
ARCHIVO = Font("archivo-latin-800-normal.woff")
MONO = Font("jetbrains-mono-latin-400-normal.woff")
MONO_B = Font("jetbrains-mono-latin-700-normal.woff")
SERIF = Font("dm-serif-display-latin-400-normal.woff")


def text(font: Font, s: str, size: float, x: float, y: float, fill: str,
         tracking: float = 0, anchor: str = "start", extra: str = "") -> tuple[str, float]:
    d, w = font.d(s, size, x, y, tracking, anchor)
    return f'<path d="{d}" fill="{fill}"{extra}/>', w


# ── shapes ─────────────────────────────────────────────────────────────────
def pts(*p) -> str:
    return " ".join(f"{_num(a)},{_num(b)}" for a, b in p)


def para(x, y, w, h, k):
    """Parallelogram leaning right by k px."""
    return pts((x + k, y), (x + w, y), (x + w - k, y + h), (x, y + h))


def cut(x, y, w, h, c):
    """Rectangle with the top-left and bottom-right corners chamfered."""
    return pts((x + c, y), (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c))


def svg(w, h, body, title, defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{title}"><title>{title}</title>'
        f"<defs>{GRAD}{defs}</defs><style>{MOTION}</style>{body}</svg>"
    )


GRAD = (
    f'<linearGradient id="tr" x1="0" y1="1" x2="1" y2="0">'
    f'<stop offset="0" stop-color="{SKY}"/><stop offset="1" stop-color="{GREEN}"/></linearGradient>'
)
MOTION = (
    "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}"
    "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}"
    "@keyframes nudge{0%,100%{transform:translateX(0)}50%{transform:translateX(7px)}}"
    "@keyframes flow{to{stroke-dashoffset:-48}}"
    ".blink{animation:blink 1.1s steps(1) infinite}"
    ".pulse{animation:pulse 1.8s ease-in-out infinite}"
    ".nudge{animation:nudge 1.3s ease-in-out infinite}"
    ".flow{animation:flow 1.6s linear infinite}"
    "@media (prefers-reduced-motion:reduce){.blink,.pulse,.nudge,.flow{animation:none}}"
)


# ── ransom-note tiles ──────────────────────────────────────────────────────
# Each tile: (font, tile fill, letter fill, rotation, border)
STYLES = {
    "p": (CHAKRA, PAPER, INK, None),          # paper tile, ink letter
    "s": (ARCHIVO_I, "url(#tr)", INK, None),  # trace tile
    "k": (CHAKRA, INK, PAPER, PAPER),          # ink tile, outlined
    "f": (SERIF, PAPER, INK, None),            # serif cut-out
    "a": (ARCHIVO_I, PAPER, INK, None),
    "m": (MONO_B, SURF2, SKY, SKY),            # terminal tile
}


def tiles(word: str, styles: str, rots: list[float], x: float, y: float, h: float,
          size: float, seed: int, gap: float = -3, lifts: list[float] | None = None):
    rnd = random.Random(seed)
    out, cx = [], x
    lifts = lifts or [0] * len(word)
    for i, ch in enumerate(word):
        font, fill, ink, border = STYLES[styles[i]]
        fs = size * (1.08 if font is SERIF else 1.0)
        gw = font.width(ch, fs)
        tw = max(gw + size * 0.42, h * 0.72)
        ty = y + lifts[i]
        j = lambda: rnd.uniform(-2.6, 2.6)
        quad = pts((cx + j(), ty + j()), (cx + tw + j(), ty + j()),
                   (cx + tw + j(), ty + h + j()), (cx + j(), ty + h + j()))
        mx, my = cx + tw / 2, ty + h / 2
        stroke = f' stroke="{border}" stroke-width="2.5"' if border else ""
        glyph, _ = text(font, ch, fs, mx, my + font.cap_h(fs) / 2, ink, anchor="middle")
        out.append(
            f'<g transform="rotate({rots[i]} {_num(mx)} {_num(my)})">'
            f'<polygon points="{pts((cx + 4, ty + 5), (cx + tw + 4, ty + 5), (cx + tw + 4, ty + h + 5), (cx + 4, ty + h + 5))}" fill="#000" opacity=".55"/>'
            f'<polygon points="{quad}" fill="{fill}"{stroke}/>{glyph}</g>'
        )
        cx += tw + gap
    return "".join(out), cx - x


def chevron(x, y, s, fill):
    return f'<polygon points="{pts((x, y - s), (x + s * 1.1, y), (x, y + s))}" fill="{fill}"/>'


def mono_chain(items, x, y, size, fill, sep_fill, font=MONO_B, tracking=1.2):
    out, cx = [], x
    for i, it in enumerate(items):
        p, w = text(font, it, size, cx, y, fill, tracking)
        out.append(p)
        cx += w
        if i < len(items) - 1:
            out.append(chevron(cx + 9, y - font.cap_h(size) / 2, size * 0.32, sep_fill))
            cx += 24
    return "".join(out), cx - x


# ── stats ──────────────────────────────────────────────────────────────────
def load_stats() -> dict:
    return json.loads(STATS.read_text())


def refresh_stats(stats: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("no GITHUB_TOKEN, keeping stats.json as is")
        return stats
    q = {
        "query": "query($l:String!){user(login:$l){"
                 "contributionsCollection{contributionCalendar{totalContributions}}"
                 "repositories(ownerAffiliations:OWNER,privacy:PUBLIC){totalCount}}}",
        "variables": {"l": LOGIN},
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=json.dumps(q).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": LOGIN})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            u = json.load(r)["data"]["user"]
        stats["contributions"] = u["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        stats["public_repos"] = u["repositories"]["totalCount"]
        stats["updated"] = dt.date.today().isoformat()
        STATS.write_text(json.dumps(stats, indent=2) + "\n")
        print("stats refreshed:", stats)
    except Exception as e:  # keep the last good numbers rather than break the profile
        print("stats refresh failed, keeping previous values:", e, file=sys.stderr)
    return stats


# ── panels ─────────────────────────────────────────────────────────────────
def dot_grid(pid, step, r, color, op):
    return (f'<pattern id="{pid}" width="{step}" height="{step}" patternUnits="userSpaceOnUse">'
            f'<circle cx="{step / 2}" cy="{step / 2}" r="{r}" fill="{color}" opacity="{op}"/></pattern>')


def stat_card(x, y, w, h, rot, value, label, dark=False, accent=False):
    bg, fg = (INK, PAPER) if dark else (PAPER, INK)
    num, nw = text(MONO_B, value, 52, x + 22, y + 62, fg, tracking=-1)
    lab, _ = text(CHAKRA_SB, label, 12.5, x + 23, y + h - 17, fg, tracking=2.6)
    bar = f'<rect x="{_num(x + 22)}" y="{_num(y + h - 34)}" width="34" height="4" fill="url(#tr)"/>'
    stroke = f' stroke="{PAPER}" stroke-width="3"' if dark else ""
    mx, my = x + w / 2, y + h / 2
    return (f'<g transform="rotate({rot} {_num(mx)} {_num(my)})">'
            f'<polygon points="{cut(x + 7, y + 8, w, h, 16)}" fill="#000" opacity=".6"/>'
            f'<polygon points="{cut(x, y, w, h, 16)}" fill="{bg}"{stroke}/>{num}{bar}{lab}</g>')


def hero(stats: dict) -> str:
    W, H = 1000, 380
    years = dt.date.today().year - SINCE
    b = []
    b.append(f'<rect width="{W}" height="{H}" fill="{INK}"/>')
    b.append(f'<rect width="{W}" height="{H}" fill="url(#grid)"/>')

    # shard panel (lightning-cut edge, white rim, rays, halftone)
    edge = [(565, 380), (634, 172), (598, 172), (652, 0)]
    panel = [(652, 0), (1000, 0), (1000, 380)] + edge
    rim = [(x - 15, y) for x, y in edge]
    b.append(f'<polygon points="{pts((652 - 15, 0), (1000, 0), (1000, 380), *rim)}" fill="{PAPER}"/>')
    b.append(f'<polygon points="{pts(*panel)}" fill="url(#tr)"/>')
    rays = []
    cx, cy = 845, 190
    for i in range(0, 24, 2):
        a1, a2 = math.radians(i * 15), math.radians(i * 15 + 15)
        rays.append(pts((cx, cy), (cx + 900 * math.cos(a1), cy + 900 * math.sin(a1)),
                        (cx + 900 * math.cos(a2), cy + 900 * math.sin(a2))))
    b.append(f'<g clip-path="url(#shard)"><g opacity=".13">'
             f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="120s" repeatCount="indefinite"/>'
             + "".join(f'<polygon points="{r}" fill="{INK}"/>' for r in rays) + "</g>"
             f'<rect x="540" width="460" height="{H}" fill="url(#halftone)" mask="url(#fade)"/></g>')

    # stat cards
    b.append(stat_card(700, 30, 236, 104, -4, f"{stats['contributions']:,}", "CONTRIBUTIONS · 1Y"))
    b.append(stat_card(790, 146, 178, 104, 3.5, f"{stats['public_repos']}", "PUBLIC REPOS", dark=True))
    b.append(stat_card(686, 258, 206, 100, -2.5, f"{years}+", "YEARS SHIPPING"))

    # name, cut out of everything
    row1, w1 = tiles("SOLOMON", "pskfpap", [-4, 3, -2, 5, -3, 2, -5], 38, 34, 84, 60, 7,
                     lifts=[0, 6, -2, 4, 0, 7, 1])
    row2, w2 = tiles("MUHYE", "kpfsp", [3, -4, 2, -3, 4], 112, 132, 80, 56, 11,
                     lifts=[2, -3, 5, 0, -2])
    b.append(row1 + row2)

    # role bar
    role, rw = text(CHAKRA_I, "FULL-STACK SOFTWARE ENGINEER", 25, 0, 0, INK, tracking=1.2)
    bx, by, bh = 34, 236, 46
    b.append(f'<polygon points="{para(bx + 6, by + 6, rw + 64, bh, 14)}" fill="url(#tr)"/>')
    b.append(f'<polygon points="{para(bx, by, rw + 64, bh, 14)}" fill="{PAPER}"/>')
    b.append(text(CHAKRA_I, "FULL-STACK SOFTWARE ENGINEER", 25, bx + 32, by + 32, INK, tracking=1.2)[0])

    # stack line + status line
    chain, _ = mono_chain(["REACT", "TYPESCRIPT", "NODE.JS", "POSTGRESQL", "PLAYWRIGHT"],
                          38, 316, 12.5, SKY, GREEN)
    b.append(chain)
    stat_txt = "SYS://TRACE.ON  ·  LOC: ADDIS ABABA, ET  ·  UTC+3"
    st, sw = text(MONO, stat_txt, 10.5, 58, 350, MUTED, tracking=0.6)
    b.append(f'<circle class="pulse" cx="44" cy="346.3" r="4.2" fill="{GREEN}"/>' + st)
    b.append(f'<rect class="blink" x="{_num(58 + sw + 6)}" y="341" width="7" height="12" fill="{SKY}"/>')

    defs = (dot_grid("grid", 22, 1, PAPER, 0.07) + dot_grid("halftone", 10, 2, INK, 0.28)
            + f'<clipPath id="shard"><polygon points="{pts(*panel)}"/></clipPath>'
            + '<radialGradient id="fg" cx=".55" cy=".5" r=".75"><stop offset="0" stop-color="#000"/>'
              '<stop offset=".45" stop-color="#000"/><stop offset="1" stop-color="#fff"/></radialGradient>'
            + f'<mask id="fade"><rect x="540" width="460" height="{H}" fill="url(#fg)"/></mask>'
            + f'<clipPath id="round"><rect width="{W}" height="{H}" rx="14"/></clipPath>')
    body = f'<g clip-path="url(#round)">{"".join(b)}</g>'
    return svg(W, H, body, "Solomon Muhye, full-stack software engineer", defs)


def wrap(font, s, size, maxw, tracking=0):
    lines, cur = [], ""
    for word in s.split():
        t = f"{cur} {word}".strip()
        if font.width(t, size, tracking) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


ABOUT = ("I'm a full-stack engineer from Addis Ababa, shipping since 2020. I lead development "
         "at Eagle Tech Apps, taking products from a Figma file to production with React, "
         "TypeScript and Node on PostgreSQL, tested end to end with Playwright. Lately I'm "
         "going deeper into security and building tools that trace what's really happening in "
         "a codebase.")


def about() -> str:
    W = 1000
    size, lh = 17.5, 29
    lines = wrap(ARCHIVO, ABOUT, size, 880)
    H = 92 + lh * len(lines) + 34
    top, bot = 38, H - 14
    quad = [(18, top + 6), (984, top), (976, bot), (26, bot - 4)]
    b = [f'<polygon points="{pts(*[(x + 9, y + 9) for x, y in quad])}" fill="url(#tr)"/>',
         f'<polygon points="{pts(*quad)}" fill="{INK}" stroke="{PAPER}" stroke-width="3.5"/>',
         f'<polygon points="{pts(*[(x + (10 if x < 500 else -10), y + (10 if y < 100 else -10)) for x, y in quad])}" '
         f'fill="url(#grid)" stroke="{LINE}" stroke-width="1.2"/>']
    # name tab
    tab, tw = text(CHAKRA_I, "SOLOMON", 26, 0, 0, INK, tracking=2)
    b.append(f'<g transform="rotate(-3 120 30)"><polygon points="{para(40, 10, tw + 56, 42, 12)}" fill="{PAPER}"/>'
             + text(CHAKRA_I, "SOLOMON", 26, 66, 41, INK, tracking=2)[0] + "</g>")
    b.append(text(MONO, "~/whoami", 11, 954, top + 30, SUBTLE, anchor="end", tracking=1)[0])
    y = top + 62
    for ln in lines:
        b.append(text(ARCHIVO, ln, size, 58, y, PAPER)[0])
        y += lh
    defs = dot_grid("grid", 22, 1, PAPER, 0.06)
    return svg(W, H, "".join(b), "About: " + ABOUT.replace("'", "&#39;"), defs)


def header(word: str, styles: str, rots, caption: str, seed: int) -> str:
    W, H = 1000, 84
    parts, x, i = [], 14, 0
    for wd in word.split(" "):
        n = len(wd)
        r, ww = tiles(wd, styles[i:i + n], rots[i:i + n], x, 14, 54, 36, seed + i, gap=-2)
        parts.append(r)
        x += ww + 16
        i += n
    end = x + 4
    line = f'<polygon points="{pts((end, 58), (986, 50), (984, 57), (end - 2, 66))}" fill="url(#tr)"/>'
    cap = text(MONO, caption, 11, 984, 38, MUTED, anchor="end", tracking=1.4)[0]
    return svg(W, H, line + "".join(parts) + cap, word.title())


PROJECTS = [
    dict(n="0x01", title="gitTrace", desc="Org health for GitHub: commit flow, PR age, stale branches",
         tags=["NEXT.JS", "GRAPHQL", "RECHARTS"], sel=True, x=58, file="case-gittrace"),
    dict(n="0x02", title="traceOn", desc="Browser extension, designed and built end to end",
         tags=["EXTENSION", "TYPESCRIPT"], x=92, file="case-traceon"),
    dict(n="0x03", title="NuBred", desc="Certification platform for breeders, growers and retailers",
         tags=["FIGMA TO PROD", "PILOT"], x=72, file="case-nubred"),
]


def case_bar(p: dict) -> str:
    W, H = 1000, 86
    x, y, w, h, k = p["x"], 8, 870, 66, 18
    sel = p.get("sel")
    b = []
    frame = "url(#tr)" if sel else PAPER
    b.append(f'<polygon points="{para(x + 6, y + 7, w, h, k)}" fill="#000" opacity=".5"/>')
    b.append(f'<polygon points="{para(x, y, w, h, k)}" fill="{frame}"/>')
    b.append(f'<polygon points="{para(x + 5, y + 5, w - 10, h - 10, k - 1.5)}" fill="{INK}"/>')
    b.append(f'<polygon points="{para(x + 10, y + 10, w - 20, h - 20, k - 3)}" fill="none" stroke="{LINE}" stroke-width="1.2"/>')
    if sel:
        b.append(f'<g class="nudge">{chevron(16, y + h / 2, 13, "url(#tr)")}</g>')
    tx = x + 42
    b.append(text(MONO_B, f"CASE {p['n']}", 10.5, tx, y + 29, SKY if sel else SUBTLE, tracking=1.6)[0])
    t, tw = text(CHAKRA_I, p["title"], 27, tx, y + 53, PAPER, tracking=0.6)
    b.append(t)
    b.append(text(CHAKRA_SB, p["desc"], 13.5, tx + max(tw, 92) + 26, y + 51, MUTED, tracking=0.3)[0])
    # tags, right-aligned
    rx = x + w - 40
    for tag in reversed(p["tags"]):
        tg, tgw = text(MONO_B, tag.replace("→", "-"), 10.5, 0, 0, PAPER, tracking=1)
        bx = rx - tgw - 18
        b.append(f'<polygon points="{cut(bx, y + 18, tgw + 18, 22, 6)}" fill="{SURF2}" stroke="{LINE}" stroke-width="1"/>')
        b.append(text(MONO_B, tag.replace("→", "-"), 10.5, bx + 9, y + 33, GREEN if sel else PAPER, tracking=1)[0])
        rx = bx - 8
    return svg(W, H, "".join(b), f"Case {p['n']}: {p['title']}, {p['desc']}")


def more_bar() -> str:
    W, H = 1000, 60
    x, y, w, h, k = 112, 6, 560, 44, 14
    b = [f'<polygon points="{para(x, y, w, h, k)}" fill="{INK}" stroke="{SUBTLE}" stroke-width="1.6" stroke-dasharray="6 5"/>']
    t, tw = text(CHAKRA_I, "ALL CASE FILES", 17, x + 36, y + 29, PAPER, tracking=2)
    b.append(t)
    b.append(text(MONO, "work.solomonmuhye.et", 12, x + 36 + tw + 22, y + 28.5, SKY, tracking=0.6)[0])
    b.append(chevron(x + w - 44, y + h / 2, 7, "url(#tr)"))
    return svg(W, H, "".join(b), "All case files at work.solomonmuhye.et")


LOADOUT = [
    ("FRONTEND", ["REACT", "NEXT.JS", "VUE", "TYPESCRIPT", "TAILWIND"], False),
    ("BACKEND", ["NODE.JS", "EXPRESS", "POSTGRESQL", "MONGODB"], False),
    ("TESTING", ["PLAYWRIGHT", "VITEST", "JEST", "TESTING LIBRARY"], False),
    ("TOOLING", ["GIT", "FIGMA", "POSTMAN", "LINUX"], False),
    ("ON RADAR", ["APPLICATION SECURITY", "OWASP TOP 10"], True),
]


def loadout() -> str:
    W = 1000
    rh = 50
    H = 36 + rh * len(LOADOUT) + 22
    b = [f'<rect width="{W}" height="{H}" rx="14" fill="{INK}"/>',
         f'<rect width="{W}" height="{H}" rx="14" fill="url(#grid)"/>']
    y = 36
    for i, (label, chips, radar) in enumerate(LOADOUT):
        lx = 30 + (i % 2) * 8
        lab_fill = "url(#tr)" if not radar else "none"
        stroke = f' stroke="{SKY}" stroke-width="1.6" stroke-dasharray="5 4"' if radar else ""
        b.append(f'<polygon points="{para(lx, y, 168, 34, 12)}" fill="{lab_fill}"{stroke}/>')
        b.append(text(CHAKRA_I, label, 16, lx + 84, y + 23.5, SKY if radar else INK, anchor="middle", tracking=1.8)[0])
        cx = 222
        for c in chips:
            _, cw = text(MONO_B, c, 12, 0, 0, PAPER, tracking=1.1)
            cs = f' stroke="{SKY}" stroke-dasharray="4 3"' if radar else f' stroke="{LINE}"'
            b.append(f'<polygon points="{cut(cx, y, cw + 28, 34, 8)}" fill="{SURF}"{cs} stroke-width="1.2"/>')
            b.append(text(MONO_B, c, 12, cx + 14, y + 22, SKY if radar else PAPER, tracking=1.1)[0])
            cx += cw + 28 + 10
        y += rh
    tp = [(770, H - 40), (830, H - 120), (930, H - 150)]
    tpath = f"M{tp[0][0]},{tp[0][1]} L{tp[1][0]},{tp[1][1]} L{tp[2][0]},{tp[2][1]}"
    b.append(f'<path d="{tpath}" fill="none" stroke="{LINE}" stroke-width="3" stroke-linecap="round"/>')
    b.append(f'<g opacity=".7"><path class="flow" d="M{tp[0][0]},{tp[0][1]} L{tp[1][0]},{tp[1][1]} L{tp[2][0]},{tp[2][1]}" '
             f'fill="none" stroke="url(#tr)" stroke-width="3" stroke-dasharray="14 34" stroke-linecap="round"/>'
             + "".join(f'<rect x="{x - s / 2}" y="{y - s / 2}" width="{s}" height="{s}" rx="3" fill="url(#tr)"/>'
                       for (x, y), s in zip(tp, [16, 22, 30])) + "</g>")
    b.append(text(MONO, "SM.LOADOUT  ·  REV 2026", 10, 970, H - 22, SUBTLE, anchor="end", tracking=1.4)[0])
    defs = dot_grid("grid", 22, 1, PAPER, 0.05)
    names = "; ".join(f"{l.title()}: {', '.join(c)}" for l, c, _ in LOADOUT)
    return svg(W, H, "".join(b), "Loadout. " + names, defs)


def button(label: str, sub: str, kind: str) -> str:
    W, H = 330, 80
    x, y, w, h, k = 8, 8, 306, 60, 16
    fill, fg, subc = {"trace": ("url(#tr)", INK, INK), "paper": (PAPER, INK, "#3F3F46"),
                      "ink": (INK, PAPER, SKY)}[kind]
    stroke = f' stroke="{PAPER}" stroke-width="3"' if kind == "ink" else ""
    b = [f'<polygon points="{para(x + 6, y + 7, w, h, k)}" fill="#000" opacity=".45"/>',
         f'<polygon points="{para(x, y, w, h, k)}" fill="{fill}"{stroke}/>',
         text(CHAKRA_I, label, 21, x + 36, y + 30, fg, tracking=2)[0],
         text(MONO, sub, 10.5, x + 34, y + 47, subc, tracking=0.4)[0],
         chevron(x + w - 46, y + h / 2, 8, fg)]
    return svg(W, H, "".join(b), f"{label.title()}: {sub}")


def footer() -> str:
    W, H = 1000, 64
    pts_ = [(20, 44), (300, 44), (330, 28), (620, 28), (650, 40), (760, 40)]
    path = "M" + " L".join(f"{x},{y}" for x, y in pts_)
    b = [f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="2"/>',
         f'<path class="flow" d="{path}" fill="none" stroke="url(#trh)" stroke-width="2" stroke-dasharray="14 34"/>']
    for (x, y), s in zip([pts_[0], pts_[2], pts_[4]], [6, 8, 11]):
        b.append(f'<rect x="{x - s / 2}" y="{y - s / 2}" width="{s}" height="{s}" rx="1.5" fill="url(#trh)"/>')
    b.append(text(MONO, "EOT  ·  SM // ADDIS ABABA", 10.5, 980, 44, SUBTLE, anchor="end", tracking=1.4)[0])
    defs = (f'<linearGradient id="trh" gradientUnits="userSpaceOnUse" x1="20" y1="0" x2="760" y2="0">'
            f'<stop offset="0" stop-color="{SKY}"/><stop offset="1" stop-color="{GREEN}"/></linearGradient>')
    return svg(W, H, "".join(b), "End of transmission", defs)


def main():
    stats = load_stats()
    if "--refresh" in sys.argv:
        stats = refresh_stats(stats)
    ASSETS.mkdir(exist_ok=True)
    files = {
        "hero.svg": hero(stats),
        "about.svg": about(),
        "h-case-files.svg": header("CASE FILES", "pskfpmapk", [-3, 2, -4, 3, -2, 4, -3, 2, -2], "// SELECT ONE", 3),
        "h-loadout.svg": header("LOADOUT", "kpsfapm", [3, -3, 2, -4, 3, -2, 4], "// EQUIPPED", 5),
        "h-channel.svg": header("OPEN CHANNEL", "pfskpaspkfmp", [-2, 3, -3, 2, -4, 3, -2, 4, -3, 2, 3, -2],
                                "// SAY HELLO", 9),
        "loadout.svg": loadout(),
        "more.svg": more_bar(),
        "btn-portfolio.svg": button("PORTFOLIO", "work.solomonmuhye.et", "trace"),
        "btn-linkedin.svg": button("LINKEDIN", "in/solomonmuhye", "paper"),
        "btn-email.svg": button("EMAIL", "solomon.muhye.wd@gmail.com", "ink"),
        "footer.svg": footer(),
    }
    for p in PROJECTS:
        files[p["file"] + ".svg"] = case_bar(p)
    for name, content in files.items():
        (ASSETS / name).write_text(content)
    print(f"rendered {len(files)} files")


if __name__ == "__main__":
    main()
