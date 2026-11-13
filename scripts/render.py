#!/usr/bin/env python3
"""
TELEMETRY: renders the solomon-mh profile README as a car's instrument cluster.

Every number on the profile is live. A GitHub Action runs this script every few
hours with --refresh, pulls the contribution calendar and language data from the
GitHub GraphQL API, writes stats.json and re-renders every panel in assets/.

    pip install fonttools
    python scripts/render.py                              # render from stats.json
    GITHUB_TOKEN=... python scripts/render.py --refresh   # pull live data first

All text is converted to vector paths, so the images look identical wherever
GitHub shows them.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
ASSETS = ROOT / "assets"
STATS = Path(os.environ.get("STATS_FILE", ROOT / "stats.json"))
LOGIN = "solomon-mh"
SINCE = 2020
EAT = dt.timezone(dt.timedelta(hours=3), "EAT")

# ── palette: graphite cluster, one signal green ────────────────────────────
BG, BG2 = "#0C0D0F", "#16181B"
HAIR, HAIR2 = "#24272B", "#34383D"
TX, TX2, TX3 = "#ECECEA", "#9A9DA1", "#62666B"
G, G2 = "#3DDC97", "#1F8A5B"


# ── type ───────────────────────────────────────────────────────────────────
def _n(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


class Font:
    def __init__(self, file):
        self.tt = TTFont(FONTS / file)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upm = self.tt["head"].unitsPerEm

    def g(self, ch):
        name = self.cmap.get(ord(ch))
        if name is None:
            raise ValueError(f"glyph {ch!r} missing")
        return self.gs[name]

    def width(self, s, size, tr=0):
        return sum(self.g(c).width for c in s) * size / self.upm + tr * max(len(s) - 1, 0)

    def path(self, s, size, x, y, tr=0, anchor="start"):
        w = self.width(s, size, tr)
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        k = size / self.upm
        pen = SVGPathPen(self.gs, ntos=_n)
        for c in s:
            g = self.g(c)
            g.draw(TransformPen(pen, (k, 0, 0, -k, x, y)))
            x += g.width * k + tr
        return pen.getCommands(), w


XL = Font("InterDisplay-ExtraLight.woff")
LT = Font("InterDisplay-Light.woff")
MD = Font("InterDisplay-Medium.woff")
TXT = Font("inter-latin-500-normal.woff")
MONO = Font("jetbrains-mono-latin-400-normal.woff")


def T(font, s, size, x, y, fill, tr=0, anchor="start", op=None):
    d, w = font.path(s, size, x, y, tr, anchor)
    o = f' opacity="{op}"' if op is not None else ""
    return f'<path d="{d}" fill="{fill}"{o}/>', w


def wrap(font, s, size, maxw):
    lines, cur = [], ""
    for word in s.split():
        t = f"{cur} {word}".strip()
        if font.width(t, size) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


DEFS = (f'<radialGradient id="vig" cx=".76" cy=".42" r=".62"><stop offset="0" stop-color="{BG2}"/>'
        f'<stop offset="1" stop-color="{BG}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="ga" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="{G2}"/>'
        f'<stop offset="1" stop-color="{G}"/></linearGradient>'
        f'<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{G}" stop-opacity=".18"/>'
        f'<stop offset="1" stop-color="{G}" stop-opacity="0"/></linearGradient>'
        f'<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3" result="b"/>'
        f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')


def svg(w, h, body, title, vignette=False):
    bg = f'<rect width="{w}" height="{h}" fill="{BG}"/>'
    if vignette:
        bg += f'<rect width="{w}" height="{h}" fill="url(#vig)"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>'
            f'<defs>{DEFS}<clipPath id="r"><rect width="{w}" height="{h}" rx="14"/></clipPath></defs>'
            f'<g clip-path="url(#r)">{bg}{body}</g>'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="14" fill="none" stroke="{HAIR}"/></svg>')


def pulse_dot(cx, cy, r=3):
    return (f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{r}" fill="{G}">'
            f'<animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>')


def label(s, x, y, fill=TX3, anchor="start", size=9.5):
    return T(MONO, s, size, x, y, fill, tr=2, anchor=anchor)[0]


def arc(cx, cy, r, a0, a1):
    p = lambda a: (cx + r * math.sin(math.radians(a)), cy - r * math.cos(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{_n(x0)},{_n(y0)} A{r},{r} 0 {large} 1 {_n(x1)},{_n(y1)}"


def num(v, fmt="{:,}"):
    return "—" if v is None else fmt.format(v)


# ── live data ──────────────────────────────────────────────────────────────
QUERY = """query($l:String!){user(login:$l){
  contributionsCollection{contributionCalendar{totalContributions
    weeks{contributionDays{date contributionCount}}}}
  repositories(ownerAffiliations:OWNER,isFork:false,first:100){nodes{
    languages(first:10,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}}}}}"""


def derive(days: list[dict], langs: dict[str, int]) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    days = [d for d in days if d["date"] <= today]
    counts = [d["contributionCount"] for d in days]
    # current streak survives a quiet today
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    streak = 0
    while i >= 0 and counts[i] > 0:
        streak, i = streak + 1, i - 1
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    weekday = [0] * 7  # Mon..Sun
    for d in days:
        weekday[dt.date.fromisoformat(d["date"]).weekday()] += d["contributionCount"]
    weeks = [sum(counts[j:j + 7]) for j in range(max(0, len(counts) - 364), len(counts), 7)][-52:]
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:5]
    return dict(this_week=sum(counts[-7:]), streak=streak, longest_streak=longest,
                weeks=weeks, weekday=weekday, best_week=max(weeks) if weeks else None,
                active_days=sum(1 for c in counts if c > 0),
                languages=[[k, round(100 * v / total, 1)] for k, v in top])


def refresh(stats):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("no GITHUB_TOKEN, rendering stats.json as is")
        return stats
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"l": LOGIN}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": LOGIN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            u = json.load(r)["data"]["user"]
        cal = u["contributionsCollection"]["contributionCalendar"]
        days = [d for w in cal["weeks"] for d in w["contributionDays"]]
        langs: dict[str, int] = {}
        for repo in u["repositories"]["nodes"]:
            for e in repo["languages"]["edges"]:
                langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
        stats.update(contributions=cal["totalContributions"], **derive(days, langs),
                     updated=dt.datetime.now(EAT).strftime("%d %b %Y, %H:%M EAT").upper())
        STATS.write_text(json.dumps(stats, indent=2) + "\n")
        print("refreshed:", stats["contributions"], "contributions, streak", stats["streak"])
    except Exception as e:  # keep the last good data rather than break the profile
        print("refresh failed, keeping previous data:", e, file=sys.stderr)
    return stats


# ── panels ─────────────────────────────────────────────────────────────────
def gauge(cx, cy, r, value):
    b = []
    a0, a1 = -125, 125
    scale = (math.ceil((value or 0) / 1000) + 1) * 1000
    av = a0 + (a1 - a0) * min((value or 0) / scale, 1)
    for i in range(51):
        a = a0 + (a1 - a0) * i / 50
        major = i % 10 == 0
        r1, r2 = r + 14, r + (26 if major else 20)
        s, c = math.sin(math.radians(a)), math.cos(math.radians(a))
        col = G if a <= av else (TX2 if major else HAIR2)
        b.append(f'<line x1="{_n(cx + r1 * s)}" y1="{_n(cy - r1 * c)}" x2="{_n(cx + r2 * s)}" y2="{_n(cy - r2 * c)}" '
                 f'stroke="{col}" stroke-width="{1.6 if major else 1}"/>')
        if major:
            v = scale * i // 50
            lab = "0" if v == 0 else (f"{v // 1000}k" if v % 1000 == 0 else f"{v / 1000:.1f}k")
            b.append(T(MONO, lab, 9, cx + (r + 40) * s, cy - (r + 40) * c + 3, TX3, anchor="middle")[0])
    b.append(f'<path d="{arc(cx, cy, r, a0, a1)}" fill="none" stroke="{HAIR}" stroke-width="6" stroke-linecap="round"/>')
    if value:
        L = math.radians(av - a0) * r
        b.append(f'<path d="{arc(cx, cy, r, a0, av)}" fill="none" stroke="url(#ga)" stroke-width="6" '
                 f'stroke-linecap="round" stroke-dasharray="{_n(L)} 4000" filter="url(#glow)">'
                 f'<animate attributeName="stroke-dashoffset" from="{_n(L)}" to="0" dur="1.6s" fill="freeze" '
                 f'calcMode="spline" keyTimes="0;1" keySplines=".2 .8 .2 1"/></path>')
        s, c = math.sin(math.radians(av)), math.cos(math.radians(av))
        b.append(f'<circle cx="{_n(cx + r * s)}" cy="{_n(cy - r * c)}" r="5" fill="{TX}" opacity="0">'
                 f'<animate attributeName="opacity" from="0" to="1" begin="1.5s" dur=".3s" fill="freeze"/></circle>')
    return "".join(b)


def sparkline(x0, x1, yb, hgt, weeks, pid="rl"):
    b = [f'<line x1="{x0}" y1="{yb}" x2="{x1}" y2="{yb}" stroke="{HAIR}"/>']
    if not weeks:
        return "".join(b)
    mx = max(weeks) or 1
    n = len(weeks)
    P = [(x0 + (x1 - x0) * i / max(n - 1, 1), yb - hgt * v / mx) for i, v in enumerate(weeks)]
    d = "M" + " L".join(f"{_n(x)},{_n(y)}" for x, y in P)
    b.append(f'<path d="{d} L{x1},{yb} L{x0},{yb} Z" fill="url(#area)"/>')
    b.append(f'<path id="{pid}" d="{d}" fill="none" stroke="{G}" stroke-width="1.4" opacity=".9"/>')
    b.append(f'<circle r="3.2" fill="{TX}"><animateMotion dur="10s" repeatCount="indefinite">'
             f'<mpath href="#{pid}"/></animateMotion></circle>')
    return "".join(b)


def hero(st):
    W, H = 1000, 430
    b = []
    p, w = T(MONO, "FULL-STACK ENGINEER", 10.5, 52, 78, G, tr=2.4)
    b += [p, T(MONO, "/  ADDIS ABABA, UTC+3", 10.5, 52 + w + 14, 78, TX3, tr=2.4)[0]]
    b.append(T(LT, "Solomon Muhye", 60, 48, 148, TX, tr=-1.2)[0])
    b.append(T(TXT, "I take products from a Figma file to production:", 16.5, 52, 186, TX2)[0])
    b.append(T(TXT, "designed, built, tested and shipped.", 16.5, 52, 210, TX2)[0])
    y = 256
    for k, v in [("ROLE", "Lead Developer, Eagle Tech Apps"), ("IN SERVICE", f"Since {SINCE}"),
                 ("STATUS", "Open to full-stack roles")]:
        b.append(f'<line x1="52" y1="{y - 18}" x2="470" y2="{y - 18}" stroke="{HAIR}"/>')
        b.append(label(k, 52, y + 2))
        if k == "STATUS":
            b.append(pulse_dot(176, y - 2))
        b.append(T(TXT, v, 14, 172 + (14 if k == "STATUS" else 0), y + 3, TX)[0])
        y += 34
    b.append(f'<line x1="52" y1="{y - 18}" x2="470" y2="{y - 18}" stroke="{HAIR}"/>')

    cx, cy = 760, 200
    b.append(gauge(cx, cy, 128, st.get("contributions")))
    b.append(T(XL, num(st.get("contributions")), 62, cx, cy + 14, TX, anchor="middle", tr=-1)[0])
    b.append(label("CONTRIBUTIONS  ·  12 MO", cx, cy + 40, TX2, anchor="middle"))
    for i, (k, v) in enumerate([("THIS WEEK", num(st.get("this_week"))),
                                ("STREAK", num(st.get("streak"), "{}d"))]):
        x = cx - 46 + i * 92
        b.append(T(MD, v, 18, x, cy + 92, TX, anchor="middle")[0])
        b.append(T(MONO, k, 8.5, x, cy + 108, TX3, anchor="middle", tr=1.6)[0])
    b.append(f'<line x1="{cx}" y1="{cy + 76}" x2="{cx}" y2="{cy + 110}" stroke="{HAIR2}"/>')

    b.append(label("52 WEEKS", 52, 370, size=8.5))
    b.append(label("NOW", 948, 370, anchor="end", size=8.5))
    b.append(sparkline(52, 948, 404, 26, st.get("weeks")))
    return svg(W, H, "".join(b), f"Solomon Muhye, full-stack engineer in Addis Ababa. I take products from a Figma "
               f"file to production. {num(st.get('contributions'))} contributions in the last 12 months.", True)


def section(n, name, caption, x=52, w=948):
    out = [label(f"{n:02d}", x, 46, G), T(MD, name, 22, x + 34, 50, TX, tr=.2)[0]]
    out.append(label(caption, w, 46, anchor="end"))
    out.append(f'<line x1="{x}" y1="70" x2="{w}" y2="70" stroke="{HAIR}"/>')
    return "".join(out)


SPECS = [
    ("DELIVERY", "Figma → production", "Marketing site through the full product, owned end to end."),
    ("ARCHITECTURE", "Full-stack platforms", "Interface, API and data model designed as one system."),
    ("INTEGRATION", "APIs & services", "Designed, documented and debugged until they hold."),
    ("QUALITY", "Tested releases", "Unit, integration and end-to-end coverage before anything ships."),
    ("PERFORMANCE", "Fast, then faster", "Profiling, debugging and tuning the slow paths."),
    ("NEXT", "Application security", "Taking the builder's view of systems into breaking them safely."),
]


def spec_sheet():
    W = 1000
    cols, cw, ch = 3, 298.7, 132
    H = 96 + 2 * ch + 64
    b = [section(1, "Spec sheet", "WHAT YOU GET")]
    for i, (k, v, d) in enumerate(SPECS):
        r, c = divmod(i, cols)
        x, y = 52 + c * cw, 96 + r * ch
        nxt = k == "NEXT"
        if c:
            b.append(f'<line x1="{_n(x)}" y1="{y + 4}" x2="{_n(x)}" y2="{y + ch - 18}" stroke="{HAIR}"/>')
        px = x + (22 if c else 0)
        b.append(label(k, px, y + 22, G if nxt else TX3))
        if nxt:
            b.append(f'<rect x="{_n(px + MONO.width(k, 9.5, 2) + 10)}" y="{y + 12}" width="66" height="15" rx="7.5" '
                     f'fill="none" stroke="{G2}"/>' + T(MONO, "IN TRAINING", 7.5, px + MONO.width(k, 9.5, 2) + 43,
                                                         y + 22.5, G, anchor="middle", tr=.8)[0])
        b.append(T(LT, v, 23, px, y + 56, TX, tr=-.3)[0])
        yy = y + 82
        for ln in wrap(TXT, d, 13.5, cw - 44):
            b.append(T(TXT, ln, 13.5, px, yy, TX2)[0])
            yy += 20
        if r == 0:
            b.append(f'<line x1="{_n(x + (22 if c else 0))}" y1="{y + ch - 4}" x2="{_n(x + cw - 22)}" '
                     f'y2="{y + ch - 4}" stroke="{HAIR}"/>')
    tool = "TOOLCHAIN   React · Next.js · TypeScript · Node.js · PostgreSQL · Playwright"
    b.append(f'<line x1="52" y1="{H - 52}" x2="948" y2="{H - 52}" stroke="{HAIR}"/>')
    b.append(T(MONO, tool, 9.5, 52, H - 26, TX3, tr=1)[0])
    return svg(W, H, "".join(b), "Spec sheet. " + " ".join(f"{k}: {v}. {d}" for k, v, d in SPECS))


def garage_head():
    return svg(1000, 96, section(2, "Garage", "SELECTED BUILDS"), "Garage: selected builds")


MODELS = [
    dict(file="m-gittrace", code="MODEL 01", name="gitTrace", url="https://github.com/solomon-mh/gitTrace",
         desc="GitHub organization health on one screen: commit activity, PR age, stale branches and "
              "contributor concentration.",
         spec=[("TYPE", "Dashboard"), ("STACK", "Next.js, GraphQL"), ("STATUS", "Open source")]),
    dict(file="m-traceon", code="MODEL 02", name="traceOn",
         desc="A browser extension, designed and built end to end.",
         spec=[("TYPE", "Extension"), ("STACK", "TypeScript"), ("BUILT", "Solo")]),
    dict(file="m-customed", code="MODEL 03", name="customEd",
         desc="An AI-powered personalized learning platform. Built across frontend, backend, design and docs.",
         spec=[("TYPE", "Platform"), ("STACK", "Full-stack, AI"), ("BUILT", "Team of 3")]),
    dict(file="m-fetanfews", code="MODEL 04", name="Fetanfews", url="https://github.com/solomon-mh/fetanfews-server",
         desc="Location-based medicine search, so people can find what they need at a pharmacy nearby.",
         spec=[("TYPE", "Web app"), ("STACK", "PHP backend"), ("BUILT", "Final-year")]),
]


def model(m):
    W, H = 490, 262
    b = [label(m["code"], 30, 42, G)]
    if m.get("url"):
        b.append(f'<circle cx="452" cy="38" r="15" fill="none" stroke="{HAIR2}"/>'
                 + T(MD, "↗", 15, 452, 43.5, TX, anchor="middle")[0])
    b.append(T(LT, m["name"], 36, 28, 92, TX, tr=-.6)[0])
    y = 126
    for ln in wrap(TXT, m["desc"], 14, 420)[:3]:
        b.append(T(TXT, ln, 14, 30, y, TX2)[0])
        y += 21
    b.append(f'<line x1="30" y1="194" x2="460" y2="194" stroke="{HAIR}"/>')
    for i, (k, v) in enumerate(m["spec"]):
        x = 30 + i * 146
        b.append(T(MONO, k, 8.5, x, 216, TX3, tr=1.8)[0])
        b.append(T(TXT, v, 13.5, x, 238, TX)[0])
    return svg(W, H, "".join(b), f"{m['name']}: {m['desc']}")


def telemetry(st):
    W, H = 1000, 340
    b = [section(3, "Live telemetry", "UPDATED " + (st.get("updated") or "ON NEXT RUN"))]
    # languages
    b.append(label("LANGUAGES", 52, 108))
    langs = st.get("languages") or []
    y = 136
    for i, (name, pct) in enumerate(langs[:5]):
        b.append(T(TXT, name, 13.5, 52, y, TX if i == 0 else TX2)[0])
        b.append(T(MONO, f"{pct:.0f}%", 10.5, 330, y, TX3, anchor="end")[0])
        b.append(f'<rect x="52" y="{y + 8}" width="278" height="3" rx="1.5" fill="{HAIR}"/>')
        b.append(f'<rect x="52" y="{y + 8}" width="{_n(max(278 * pct / 100, 3))}" height="3" rx="1.5" '
                 f'fill="{G if i == 0 else TX3}"/>')
        y += 36
    if not langs:
        b.append(T(TXT, "Waiting for first data refresh", 13.5, 52, y, TX3)[0])
    # weekday rhythm
    b.append(f'<line x1="372" y1="96" x2="372" y2="{H - 30}" stroke="{HAIR}"/>')
    b.append(label("WEEKLY RHYTHM", 404, 108))
    wd = st.get("weekday") or [0] * 7
    mx = max(wd) or 1
    top = wd.index(max(wd)) if any(wd) else -1
    for i, v in enumerate(wd):
        x = 410 + i * 40
        h = 130 * v / mx
        b.append(f'<rect x="{x}" y="138" width="16" height="130" rx="3" fill="{HAIR}" opacity=".6"/>')
        if v:
            b.append(f'<rect x="{x}" y="{_n(268 - h)}" width="16" height="{_n(h)}" rx="3" '
                     f'fill="{G if i == top else TX3}"/>')
        b.append(T(MONO, "MTWTFSS"[i], 9.5, x + 8, 290, TX if i == top else TX3, anchor="middle")[0])
    # records
    b.append(f'<line x1="708" y1="96" x2="708" y2="{H - 30}" stroke="{HAIR}"/>')
    b.append(label("RECORDS  ·  12 MO", 740, 108))
    days = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
    rec = [("BEST WEEK", num(st.get("best_week"))), ("LONGEST STREAK", num(st.get("longest_streak"), "{} days")),
           ("ACTIVE DAYS", num(st.get("active_days"), "{} / 365")), ("PEAK DAY", days[top] if top >= 0 else "—")]
    y = 146
    for k, v in rec:
        b.append(T(MONO, k, 8.5, 740, y, TX3, tr=1.8)[0])
        b.append(T(MD, v, 19, 948, y + 2, TX, anchor="end")[0])
        b.append(f'<line x1="740" y1="{y + 16}" x2="948" y2="{y + 16}" stroke="{HAIR}"/>')
        y += 46
    return svg(W, H, "".join(b), "Live telemetry: languages, weekly rhythm and records from the last 12 months.")


def button(name, sub, primary):
    W, H = 490, 96
    b = [label("CONTACT" if primary else "WRITE", 30, 38, G if primary else TX3),
         T(LT, name, 26, 28, 72, TX, tr=-.3)[0],
         T(MONO, sub, 10.5, 460 - 52, 66, TX2, anchor="end", tr=.4)[0],
         f'<circle cx="452" cy="58" r="17" fill="{G if primary else "none"}" stroke="{G if primary else HAIR2}"/>',
         T(MD, "→", 17, 452, 64, BG if primary else TX, anchor="middle")[0]]
    return svg(W, H, "".join(b), f"{name}: {sub}")


def main():
    st = json.loads(STATS.read_text())
    if "--refresh" in sys.argv:
        st = refresh(st)
    files = {"hero.svg": hero(st), "spec.svg": spec_sheet(), "garage.svg": garage_head(),
             "telemetry.svg": telemetry(st),
             "btn-linkedin.svg": button("LinkedIn", "in/solomonmuhye", True),
             "btn-email.svg": button("Email", "solomon.muhye.wd@gmail.com", False)}
    for m in MODELS:
        files[m["file"] + ".svg"] = model(m)
    out = Path(os.environ.get("ASSETS_DIR", ASSETS))
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content)
    print(f"rendered {len(files)} panels into {out}")


if __name__ == "__main__":
    main()
