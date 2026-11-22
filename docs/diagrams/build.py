#!/usr/bin/env python3
"""Generate the architecture diagrams in docs/diagrams/ (README sections 4 and 5).

Single source of truth for every committed SVG:

  architecture.svg         the whole system on one map
  components/<id>.svg      one card per component: what it is, what it does, who it talks to
  flows/<id>.svg           animated flows (SMIL), drawn on the same map as architecture.svg

Standard library only:  python3 docs/diagrams/build.py
GIF copies of the flows: node docs/diagrams/render-gifs.mjs  (needs Playwright and ffmpeg)

Keep the facts here in line with the code (docker-compose.yml, backend/app, agent/).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from textwrap import wrap

OUT = Path(__file__).resolve().parent
FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"

INK = "#1f2328"
MUTED = "#59636e"
LINE = "#d0d7de"
PAPER = "#ffffff"
PACKET = "#f97316"

# Tier -> (accent, tint). One colour per kind of component, used on the map, cards and legend.
TIERS: dict[str, tuple[str, str, str]] = {
    "edge": ("#d97706", "#fef3c7", "Edge / ingress"),
    "app": ("#2563eb", "#dbeafe", "Application"),
    "tasks": ("#7c3aed", "#ede9fe", "Celery tasks"),
    "data": ("#059669", "#d1fae5", "Data stores"),
    "host": ("#475569", "#e2e8f0", "macOS host"),
    "external": ("#db2777", "#fce7f3", "Outside the Mac"),
}


# ----------------------------------------------------------------------------- model


@dataclass
class Node:
    id: str
    label: str
    sub: str
    tier: str
    icon: str
    x: float
    y: float
    w: float = 180
    h: float = 54

    @property
    def left(self) -> float:
        return self.x - self.w / 2

    @property
    def right(self) -> float:
        return self.x + self.w / 2

    @property
    def top(self) -> float:
        return self.y - self.h / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h / 2


@dataclass
class Edge:
    id: str
    points: list[tuple[float, float]]
    label: str = ""
    label_at: tuple[float, float] | None = None
    dashed: bool = False
    anchor: str = "middle"


@dataclass
class Step:
    caption: str
    edges: list[str] = field(default_factory=list)  # "id" forward, "-id" reverse; joined in order
    node: str | None = None  # self step: pulse this node instead of moving a packet
    color: str = PACKET


@dataclass
class Flow:
    id: str
    title: str
    steps: list[Step]


@dataclass
class Card:
    id: str
    name: str
    tier: str
    icon: str
    where: str
    what: str
    duties: list[str]
    talks: list[tuple[str, str]]
    facts: str


# ----------------------------------------------------------------------------- the map

W, MAP_H, PANEL_H = 1240, 770, 96

NODES = {
    n.id: n
    for n in [
        Node("browser", "Browser", "you, anywhere", "external", "user", 140, 65),
        Node("cloudflare", "Cloudflare", "TLS · DNS · DDoS", "edge", "cloud", 350, 65),
        Node("targets", "Monitored targets", "URLs · DNS · TCP", "external", "target", 640, 65),
        Node("smtp", "SMTP relay", "outgoing email", "external", "mail", 900, 65),
        Node("hc", "healthchecks.io", "dead man's switch", "external", "pulse", 1110, 65),
        Node("cloudflared", "cloudflared", "com.cloudflare", "edge", "tunnel", 350, 195),
        Node("agent", "host-agent", "com.homelab.agent", "host", "heart", 640, 195),
        Node("web", "web", "nginx · :8380", "edge", "shield", 350, 335),
        Node("api", "api", "FastAPI · :8000", "app", "bolt", 350, 465),
        Node("redis", "redis", "broker · sessions", "data", "stack", 640, 465),
        Node("beat", "beat", "Celery beat × 1", "tasks", "clock", 1110, 465),
        Node("migrate", "migrate", "alembic · one-shot", "app", "arrow", 140, 620),
        Node("postgres", "postgres", "PostgreSQL 16", "data", "db", 350, 620),
        Node("wc", "worker-checks", "checks · threads×16", "tasks", "gear", 640, 620),
        Node("wd", "worker-default", "default · prefork×2", "tasks", "gear", 890, 620),
        Node("dproxy", "docker-proxy", "GET /containers", "edge", "box", 1110, 620),
        Node("sock", "docker.sock", "read-only mount", "host", "plug", 1110, 712, 170, 34),
    ]
}

EDGES = {
    e.id: e
    for e in [
        Edge("browser-cf", [(230, 65), (260, 65)]),
        Edge("cf-cfd", [(350, 92), (350, 168)], "tunnel", (360, 135), anchor="start"),
        Edge("cfd-web", [(350, 222), (350, 308)], "127.0.0.1:8380", (360, 292), anchor="start"),
        Edge("agent-web", [(640, 222), (640, 335), (440, 335)], "POST heartbeat", (540, 326)),
        Edge("agent-hc", [(730, 190), (1060, 190), (1060, 92)], "ping “mac-mini”", (900, 181), True),
        Edge("web-api", [(350, 362), (350, 438)], "/api/*", (360, 404), anchor="start"),
        Edge("api-pg", [(350, 492), (350, 593)], "SQL", (360, 548), anchor="start"),
        Edge("api-redis", [(440, 465), (550, 465)], "sessions · enqueue", (495, 456)),
        Edge("beat-redis", [(1020, 450), (730, 450)], "beat schedule", (980, 441), anchor="end"),
        Edge("redis-wc", [(640, 492), (640, 593)], "checks queue", (648, 548), anchor="start"),
        Edge("redis-wd", [(730, 480), (850, 480), (850, 593)], "default queue", (858, 548), anchor="start"),
        Edge("wc-pg", [(550, 620), (440, 620)], "results", (495, 611)),
        Edge("wd-pg", [(890, 647), (890, 690), (350, 690), (350, 647)], "SQL", (620, 683)),
        Edge("migrate-pg", [(230, 620), (260, 620)]),
        Edge(
            "wc-targets",
            [(730, 608), (762, 608), (762, 65), (730, 65)],
            "HTTP · DNS · TCP",
            (770, 236),
            anchor="start",
        ),
        Edge("wd-smtp", [(940, 593), (940, 92)], "SMTP", (948, 236), anchor="start"),
        Edge("wd-dproxy", [(980, 620), (1020, 620)]),
        Edge("dproxy-sock", [(1110, 647), (1110, 695)]),
        # ping_healthcheck is scheduled by beat but executed by worker-default.
        Edge(
            "wd-hc",
            [(970, 593), (970, 125), (1110, 125), (1110, 92)],
            "ping “homelab-monitor”",
            (978, 330),
            True,
            "start",
        ),
    ]
}

REGIONS = [
    # (x, y, w, h, title, fill, stroke)
    (14, 18, 1212, 96, "Internet", "#fafbfc", LINE),
    (14, 140, 1212, 615, "Mac mini · macOS (headless, FileVault)", "#f6f8fa", "#94a3b8"),
    (34, 262, 1172, 482, "Colima VM · docker compose", "#ffffff", "#93c5fd"),
]


# ----------------------------------------------------------------------------- icons


def icon(kind: str, cx: float, cy: float, r: float, color: str) -> str:
    """A small white glyph on a coloured disc, drawn in a 24x24 box scaled to radius r."""
    s = r / 12
    glyphs = {
        "user": '<circle cx="12" cy="9" r="3.6"/><path d="M5 19c1.2-3.6 4-5 7-5s5.8 1.4 7 5"/>',
        "cloud": '<path d="M7 17h10a3.5 3.5 0 0 0 .4-7A5 5 0 0 0 8 9.2 4 4 0 0 0 7 17z"/>',
        "target": '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="2.5"/>',
        "mail": '<rect x="5" y="7" width="14" height="10" rx="1.5"/><path d="M5.5 7.8 12 13l6.5-5.2"/>',
        "pulse": '<path d="M4 12h4l2-5 4 10 2-5h4"/>',
        "tunnel": '<path d="M5 18v-5a7 7 0 0 1 14 0v5"/><path d="M9 18v-4a3 3 0 0 1 6 0v4"/>',
        "heart": '<path d="M12 18s-6-3.6-6-8a3.3 3.3 0 0 1 6-1.8A3.3 3.3 0 0 1 18 10c0 4.4-6 8-6 8z"/>',
        "shield": '<path d="M12 4.5 18 7v4.6c0 3.6-2.6 6.3-6 7.4-3.4-1.1-6-3.8-6-7.4V7z"/>',
        "bolt": '<path d="M13 4 7 13h4.5L11 20l6-9h-4.5z"/>',
        "stack": '<path d="M12 5 19 8.5 12 12 5 8.5z"/><path d="M5 12l7 3.5 7-3.5"/><path d="M5 15.5 12 19l7-3.5"/>',
        "clock": '<circle cx="12" cy="12" r="7"/><path d="M12 8v4.3l3 1.8"/>',
        "arrow": '<path d="M12 18V7"/><path d="M7.5 11 12 6.5 16.5 11"/><path d="M7 19h10"/>',
        "db": '<ellipse cx="12" cy="7.5" rx="6" ry="2.5"/><path d="M6 7.5v9c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-9"/><path d="M6 12c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5"/>',
        "gear": '<circle cx="12" cy="12" r="2.6"/><path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2M6.7 6.7l1.6 1.6M15.7 15.7l1.6 1.6M6.7 17.3l1.6-1.6M15.7 8.3l1.6-1.6"/>',
        "box": '<path d="M5 8.5 12 5l7 3.5v7L12 19l-7-3.5z"/><path d="M5 8.5 12 12l7-3.5M12 12v7"/>',
        "plug": '<path d="M9 5v4M15 5v4"/><path d="M7 9h10v2a5 5 0 0 1-10 0z"/><path d="M12 16v3"/>',
    }
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'
        f'<g transform="translate({cx - 12 * s} {cy - 12 * s}) scale({s})" fill="none" '
        f'stroke="#fff" stroke-width="{1.9}" stroke-linecap="round" stroke-linejoin="round">'
        f"{glyphs[kind]}</g>"
    )


# ----------------------------------------------------------------------------- map drawing


def svg_open(width: float, height: float, title: str, desc: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" font-family="{FONT}">'
        f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>"
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="{MUTED}"/></marker>'
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="140%">'
        '<feDropShadow dx="0" dy="1.5" stdDeviation="1.8" flood-color="#0f172a" flood-opacity="0.12"/>'
        "</filter>"
        '<filter id="glow" x="-100%" y="-100%" width="300%" height="300%">'
        '<feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/>'
        '<feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
        f'<rect width="{width}" height="{height}" rx="16" fill="{PAPER}"/>'
    )


def path_d(points: list[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in points)


def draw_regions() -> str:
    out = []
    for x, y, w, h, title, fill, stroke in REGIONS:
        out.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" '
            f'stroke="{stroke}" stroke-dasharray="5 4"/>'
            f'<text x="{x + 12}" y="{y + 17}" font-size="12" font-weight="600" fill="{MUTED}" '
            f'letter-spacing="0.3">{escape(title.upper())}</text>'
        )
    return "".join(out)


def draw_edges(active: set[str] | None = None) -> str:
    out = []
    for e in EDGES.values():
        dim = active is not None and e.id not in active
        opacity = 0.28 if dim else 1
        dash = ' stroke-dasharray="6 4"' if e.dashed else ""
        out.append(
            f'<path id="edge-{e.id}" d="{path_d(e.points)}" fill="none" stroke="{MUTED}" '
            f'stroke-width="1.6"{dash} marker-end="url(#arrow)" opacity="{opacity}"/>'
        )
        if e.label and e.label_at:
            lx, ly = e.label_at
            out.append(
                f'<text x="{lx}" y="{ly}" font-size="11" fill="{MUTED}" text-anchor="{e.anchor}" '
                f'opacity="{opacity}" paint-order="stroke" stroke="{PAPER}" stroke-width="4" '
                f'stroke-linejoin="round">{escape(e.label)}</text>'
            )
    return "".join(out)


def draw_node(n: Node, dim: bool = False) -> str:
    accent, tint, _ = TIERS[n.tier]
    opacity = 0.4 if dim else 1
    small = n.h < 45
    r = 9 if small else 13
    text_x = n.left + (30 if small else 40)
    body = (
        f'<g opacity="{opacity}">'
        f'<rect x="{n.left}" y="{n.top}" width="{n.w}" height="{n.h}" rx="10" fill="{PAPER}" '
        f'stroke="{accent}" stroke-width="1.4" filter="url(#shadow)"/>'
        + icon(n.icon, n.left + (17 if small else 22), n.y, r, accent)
    )
    if small:
        body += (
            f'<text x="{text_x}" y="{n.y + 4}" font-size="12" font-weight="600" fill="{INK}" '
            f'font-family="{MONO}">{escape(n.label)}</text>'
        )
    else:
        body += (
            f'<text x="{text_x}" y="{n.y - 3}" font-size="14" font-weight="700" fill="{INK}">'
            f"{escape(n.label)}</text>"
            f'<text x="{text_x}" y="{n.y + 14}" font-size="11" fill="{MUTED}">{escape(n.sub)}</text>'
        )
    return body + "</g>"


def draw_legend(y: float) -> str:
    out = [f'<text x="30" y="{y + 4}" font-size="12" font-weight="600" fill="{MUTED}">LEGEND</text>']
    x = 100
    for accent, _, name in TIERS.values():
        out.append(f'<rect x="{x}" y="{y - 7}" width="14" height="14" rx="4" fill="{accent}"/>')
        out.append(f'<text x="{x + 20}" y="{y + 4}" font-size="12" fill="{INK}">{escape(name)}</text>')
        x += 40 + len(name) * 7
    out.append(
        f'<path d="M{x + 10} {y} h36" stroke="{MUTED}" stroke-width="1.6" marker-end="url(#arrow)"/>'
        f'<text x="{x + 54}" y="{y + 4}" font-size="12" fill="{INK}">request / message</text>'
        f'<path d="M{x + 190} {y} h36" stroke="{MUTED}" stroke-width="1.6" stroke-dasharray="6 4" '
        f'marker-end="url(#arrow)"/>'
        f'<text x="{x + 234}" y="{y + 4}" font-size="12" fill="{INK}">liveness ping</text>'
    )
    return "".join(out)


def architecture() -> str:
    h = MAP_H + 44
    return (
        svg_open(W, h, "homelab-monitor architecture", "All components and how they connect.")
        + draw_regions()
        + draw_edges()
        + "".join(draw_node(n) for n in NODES.values())
        + draw_legend(MAP_H + 18)
        + "</svg>"
    )


# ----------------------------------------------------------------------------- animated flows

STEP_S = 2.6  # seconds per step
MOVE_S = 1.3  # packet travel time within a step
LEAD_S = 0.4  # pause before the loop starts again


def step_points(step: Step) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for ref in step.edges:
        e = EDGES[ref.lstrip("-")]
        seg = list(reversed(e.points)) if ref.startswith("-") else list(e.points)
        if pts and pts[-1] == seg[0]:
            seg = seg[1:]
        elif pts:
            pts.append(seg[0])  # bridge through the node centre is not needed; join directly
            seg = seg[1:]
        pts += seg
    return pts


def endpoints(step: Step) -> set[str]:
    """Nodes touched by a step: the ones whose box contains a point of the path."""
    if step.node:
        return {step.node}
    pts = step_points(step)
    hit = set()
    for n in NODES.values():
        for x, y in (pts[0], pts[-1]):
            if n.left - 2 <= x <= n.right + 2 and n.top - 2 <= y <= n.bottom + 2:
                hit.add(n.id)
    return hit


def frac(t: float, total: float) -> str:
    return f"{min(max(t / total, 0), 1):.5f}"


def window(start: float, end: float, total: float, on: str = "1", off: str = "0") -> tuple[str, str]:
    """Discrete keyTimes/values that show something only between start and end."""
    if end >= total - 1e-6:
        return f"0;{frac(start, total)}", f"{off};{on}"
    return f"0;{frac(start, total)};{frac(end, total)}", f"{off};{on};{off}"


def wrap_caption(text: str, width: int = 128) -> list[str]:
    return wrap(text, width)[:2]


def flow_svg(flow: Flow) -> str:
    n = len(flow.steps)
    total = LEAD_S + n * STEP_S + 1.2
    used_edges = {ref.lstrip("-") for s in flow.steps for ref in s.edges}
    used_nodes = set().union(*(endpoints(s) for s in flow.steps))
    for s in flow.steps:
        for ref in s.edges:
            used_nodes |= endpoints(Step("", [ref]))
    h = MAP_H + PANEL_H
    out = [
        svg_open(W, h, flow.title, f"Animated flow: {flow.title}"),
        draw_regions(),
        draw_edges(active=used_edges),
        "".join(draw_node(nd, dim=nd.id not in used_nodes) for nd in NODES.values()),
    ]

    # Highlight rings on nodes while they take part in a step.
    for nd in NODES.values():
        if nd.id not in used_nodes:
            continue
        times, values = ["0"], ["0"]
        for i, s in enumerate(flow.steps):
            if nd.id in endpoints(s):
                a = LEAD_S + i * STEP_S
                times += [frac(a, total), frac(a + STEP_S - 0.05, total)]
                values += ["1", "0"]
        if len(times) == 1:
            continue
        accent = TIERS[nd.tier][0]
        out.append(
            f'<rect x="{nd.left - 4}" y="{nd.top - 4}" width="{nd.w + 8}" height="{nd.h + 8}" rx="13" '
            f'fill="none" stroke="{accent}" stroke-width="3" opacity="0">'
            f'<animate attributeName="opacity" dur="{total:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{";".join(times)}" values="{";".join(values)}"/></rect>'
        )

    # Packets.
    for i, s in enumerate(flow.steps):
        a = LEAD_S + i * STEP_S
        if s.node:
            nd = NODES[s.node]
            kt, vals = window(a, a + STEP_S - 0.05, total)
            out.append(
                f'<circle cx="{nd.x}" cy="{nd.y}" r="20" fill="none" stroke="{s.color}" stroke-width="3" opacity="0">'
                f'<animate attributeName="opacity" dur="{total:.2f}s" repeatCount="indefinite" '
                f'calcMode="discrete" keyTimes="{kt}" values="{vals}"/>'
                f'<animate attributeName="r" dur="0.9s" repeatCount="indefinite" values="{nd.h / 2};{nd.w / 2 + 6}"/>'
                f'<animate attributeName="stroke-opacity" dur="0.9s" repeatCount="indefinite" values="0.9;0"/>'
                "</circle>"
            )
            continue
        pts = step_points(s)
        b = a + MOVE_S
        kt_vis, v_vis = window(a, a + STEP_S - 0.15, total)
        out.append(
            f'<path d="{path_d(pts)}" fill="none" stroke="{s.color}" stroke-width="3.2" '
            f'stroke-linecap="round" opacity="0">'
            f'<animate attributeName="opacity" dur="{total:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{kt_vis}" values="{v_vis.replace("1", "0.55")}"/></path>'
            f'<circle r="7" fill="{s.color}" stroke="#fff" stroke-width="2" filter="url(#glow)" opacity="0">'
            f'<animate attributeName="opacity" dur="{total:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{kt_vis}" values="{v_vis}"/>'
            f'<animateMotion dur="{total:.2f}s" repeatCount="indefinite" calcMode="linear" '
            f'path="{path_d(pts)}" keyPoints="0;0;1;1" keyTimes="0;{frac(a, total)};{frac(b, total)};1"/>'
            "</circle>"
        )

    # Caption panel.
    py = MAP_H + 6
    out.append(
        f'<rect x="14" y="{py}" width="{W - 28}" height="{PANEL_H - 20}" rx="12" fill="#0f172a"/>'
        f'<text x="34" y="{py + 26}" font-size="13" font-weight="700" fill="#fdba74" '
        f'letter-spacing="0.4">{escape(flow.title.upper())}</text>'
    )
    for i, s in enumerate(flow.steps):
        a = LEAD_S + i * STEP_S
        end = a + STEP_S if i < n - 1 else total
        kt, vals = window(a if i else 0, end, total)
        lines = wrap_caption(s.caption)
        tspans = "".join(
            f'<tspan x="34" dy="{0 if j == 0 else 19}">{escape(line)}</tspan>' for j, line in enumerate(lines)
        )
        out.append(
            f'<g opacity="{1 if i == 0 else 0}">'
            f'<animate attributeName="opacity" dur="{total:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{kt}" values="{vals}"/>'
            f'<text x="{W - 34}" y="{py + 26}" font-size="12" fill="#94a3b8" text-anchor="end">'
            f"step {i + 1} / {n}</text>"
            f'<text y="{py + 50}" font-size="14.5" fill="#f8fafc">{tspans}</text>'
            "</g>"
        )
    # Progress dots.
    x0 = W - 34 - 14 * n - 70
    for i in range(n):
        a = LEAD_S + i * STEP_S
        kt, vals = window(a, a + STEP_S, total, on="#f97316", off="#334155")
        out.append(
            f'<circle cx="{x0 + i * 14}" cy="{py + 22}" r="4" fill="#334155">'
            f'<animate attributeName="fill" dur="{total:.2f}s" repeatCount="indefinite" '
            f'calcMode="discrete" keyTimes="{kt}" values="{vals}"/></circle>'
        )
    out.append("</svg>")
    return "".join(out)


RED = "#dc2626"
GREEN = "#16a34a"
BLUE = "#2563eb"

FLOWS = [
    Flow(
        "monitor-check",
        "URL check → incident → email",
        [
            Step(
                "Every 15 s Celery beat enqueues schedule_due_checks on the default queue in Redis.",
                ["beat-redis"],
            ),
            Step(
                "worker-default picks it up and takes a short Redis lock (lock:schedule_due_checks), so only one scheduler runs at a time.",
                ["redis-wd"],
            ),
            Step(
                "It claims due monitors (next_check_at <= now(), FOR UPDATE SKIP LOCKED) and moves next_check_at forward by one interval.",
                ["wd-pg"],
            ),
            Step(
                "For each one it enqueues run_check(monitor_id) on the checks queue, with jitter on catch-up and an expiry of one interval.",
                ["-redis-wd"],
            ),
            Step(
                "worker-checks (16 threads, I/O-bound) takes run_check from the checks queue.", ["redis-wc"]
            ),
            Step(
                "It loads the monitor from Postgres and releases the connection before doing any network I/O.",
                ["wc-pg"],
            ),
            Step(
                "Probe the target: http (status, keyword, latency), dns (resolve and match) or tcp (connect to host:port).",
                ["wc-targets"],
                color=BLUE,
            ),
            Step(
                "The target times out or returns an error. A failed check is a result, not a Celery retry: the next interval is the retry.",
                ["-wc-targets"],
                color=RED,
            ),
            Step(
                "Store a check_results row. On the 2nd consecutive failure the monitor goes UP → DOWN, an incident opens and an alerts row is created (pending).",
                ["wc-pg"],
                color=RED,
            ),
            Step(
                "Enqueue send_alert(alert_id) on the default queue. Skipped while a local network outage is open, so one alert replaces N.",
                ["-redis-wc"],
                color=RED,
            ),
            Step(
                "worker-default runs send_alert: acks_late, exponential backoff with jitter, up to 10 retries over about an hour.",
                ["redis-wd"],
                color=RED,
            ),
            Step(
                "The email goes out through SMTP: “monitor DOWN”. Recovery later sends one “recovered” email the same way.",
                ["wd-smtp"],
                color=RED,
            ),
            Step(
                "The alert is marked sent. A unique (incident, kind) constraint means a retry can never send a duplicate.",
                ["wd-pg"],
                color=GREEN,
            ),
        ],
    ),
    Flow(
        "heartbeat",
        "Host agent heartbeat ingest",
        [
            Step(
                "Every 30 s the agent collects kern.boottime, uptime, load, vm_stat memory, disk %, launchctl status of Colima and cloudflared, and the last shutdown cause.",
                node="agent",
                color=BLUE,
            ),
            Step(
                "POST /api/v1/agent/heartbeat to 127.0.0.1:8380 with its Bearer token. Anything still in the local spool goes in the same batch. Nothing leaves the Mac.",
                ["agent-web"],
            ),
            Step("nginx proxies /api/* to the api container.", ["web-api"]),
            Step(
                "The api checks the token (SHA-256), stores host_heartbeats and sets last_seen_at to the server receive time, so a late backlog never looks alive. Host → UP.",
                ["api-pg"],
            ),
            Step(
                "boot_time changed? A boot_event is recorded with the shutdown cause (clean / unexpected / unknown) and the downtime.",
                node="api",
                color=BLUE,
            ),
            Step(
                "Unexpected reboot, disk above 90% or a STALE host that recovered: send_alert is enqueued on the default queue.",
                ["api-redis", "redis-wd"],
                color=RED,
            ),
            Step(
                "worker-default emails the alert through SMTP (same idempotent send_alert as monitor alerts).",
                ["wd-smtp"],
                color=RED,
            ),
            Step(
                "202 Accepted travels back and the agent empties its spool.",
                ["-web-api", "-agent-web"],
                color=GREEN,
            ),
            Step(
                "Finally the agent pings its healthchecks.io check “mac-mini”: macOS itself is alive.",
                ["agent-hc"],
                color=GREEN,
            ),
            Step(
                "If the POST fails (for example Colima is down) the heartbeat is appended to spool.jsonl (max 120 ≈ 1 h, oldest dropped) and sent with the next batch.",
                node="agent",
                color=RED,
            ),
        ],
    ),
    Flow(
        "dashboard-request",
        "Dashboard request from the internet",
        [
            Step(
                "The browser opens the public hostname over HTTPS. Cloudflare terminates TLS (Cloudflare Access can be added here later).",
                ["browser-cf"],
                color=BLUE,
            ),
            Step(
                "Cloudflare sends the request down the tunnel. cloudflared opened that connection from the Mac, so no router port is open.",
                ["cf-cfd"],
                color=BLUE,
            ),
            Step(
                "cloudflared forwards to 127.0.0.1:8380, the only published port of the whole stack.",
                ["cfd-web"],
                color=BLUE,
            ),
            Step(
                "nginx serves / as the static Angular build and adds security headers (CSP, HSTS, X-Frame-Options). /api/* goes on to the api.",
                node="web",
                color=BLUE,
            ),
            Step(
                "GET /api/v1/summary with the hm_session cookie (HttpOnly, Secure, SameSite=Strict). Writes also carry X-XSRF-TOKEN.",
                ["web-api"],
                color=BLUE,
            ),
            Step(
                "The api looks the session up in Redis (24 h idle, 7 days absolute). Logins are rate limited to 5 per minute per CF-Connecting-IP.",
                ["api-redis"],
                color=BLUE,
            ),
            Step(
                "It reads host status, monitors, open incidents and banners from Postgres.",
                ["api-pg"],
                color=BLUE,
            ),
            Step(
                "JSON goes back the same way. The dashboard polls every 15 s.",
                ["-web-api", "-cfd-web", "-cf-cfd", "-browser-cf"],
                color=GREEN,
            ),
        ],
    ),
    Flow(
        "container-snapshot",
        "Container snapshot through the read-only proxy",
        [
            Step("Every 60 s beat enqueues snapshot_containers on the default queue.", ["beat-redis"]),
            Step(
                "Only worker-default runs it, and only worker-default is on the internal docker network.",
                ["redis-wd"],
            ),
            Step(
                "GET /containers/json?all=1 to docker-proxy. The proxy allows container reads only: POST, exec, images and volumes are refused.",
                ["wd-dproxy"],
            ),
            Step("The proxy talks to /var/run/docker.sock, mounted read-only.", ["dproxy-sock"]),
            Step(
                "Back comes every container with name, image, state, health and start time.",
                ["-dproxy-sock", "-wd-dproxy"],
                color=GREEN,
            ),
            Step(
                "Upsert the containers table and write container_events only for changes (started, stopped, unhealthy, removed). Never an email.",
                ["wd-pg"],
                color=GREEN,
            ),
        ],
    ),
    Flow(
        "dead-mans-switch",
        "Dead man's switches (healthchecks.io)",
        [
            Step(
                "Every 60 s beat enqueues ping_healthcheck for → check “homelab-monitor”: Colima, Docker and the app are running.",
                ["beat-redis", "redis-wd"],
                color=GREEN,
            ),
            Step(
                "worker-default sends the HTTP ping to healthchecks.io. If it fails, it just logs; the next minute tries again.",
                ["wd-hc"],
                color=GREEN,
            ),
            Step(
                "Every 30 s the agent pings check “mac-mini”: macOS is running and online.",
                ["agent-hc"],
                color=GREEN,
            ),
            Step(
                "Colima or the app down, Mac up: only “homelab-monitor” goes quiet. The agent keeps buffering heartbeats.",
                node="hc",
                color=RED,
            ),
            Step(
                "Power cut or the Mac is off: both go quiet and healthchecks.io emails the operator itself, because our own SMTP path is down too.",
                node="hc",
                color=RED,
            ),
        ],
    ),
]


# ----------------------------------------------------------------------------- component cards

CARDS = [
    Card(
        "cloudflared",
        "cloudflared",
        "edge",
        "tunnel",
        "macOS · LaunchDaemon com.cloudflare",
        "Cloudflare Tunnel connector, outside this compose stack.",
        [
            "Keeps an outbound tunnel open to Cloudflare, so no router port is forwarded",
            "Forwards the public hostname to 127.0.0.1:8380 (nginx)",
            "Cloudflare in front provides TLS, DNS and DDoS protection; Cloudflare Access later",
            "Its LaunchDaemon status is reported by host-agent in every heartbeat",
        ],
        [("Cloudflare", "tunnel"), ("web", "HTTP 127.0.0.1:8380")],
        "Not in docker-compose.yml on purpose · runs before Colima starts",
    ),
    Card(
        "host-agent",
        "host-agent",
        "host",
        "heart",
        "macOS · LaunchDaemon com.homelab.agent",
        "Native Python agent (stdlib only): sees what Colima containers can't.",
        [
            "Every 30 s: boot time, uptime, load, memory, disk %, Colima and cloudflared status",
            "Reads the macOS “previous shutdown cause” once per boot",
            "POSTs heartbeats to /api/v1/agent/heartbeat with a per-host Bearer token",
            "Buffers up to 120 heartbeats (~1 h) in spool.jsonl when the API is down",
            "Pings healthchecks.io “mac-mini” every cycle",
        ],
        [("web", "POST heartbeat"), ("healthchecks.io", "ping")],
        "Dedicated non-admin user · config /usr/local/etc/homelab-agent.json",
    ),
    Card(
        "web",
        "web",
        "edge",
        "shield",
        "compose · nginx + Angular build",
        "The single entry point and the only published port.",
        [
            "Serves the Angular (Material + ECharts) SPA as static files on /",
            "Reverse-proxies /api/* to the api container: same origin, no CORS",
            "Sets CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, body limits",
            "Receives agent heartbeats on the same port, so the token never leaves the Mac",
        ],
        [("api", "HTTP /api/*"), ("cloudflared", "inbound"), ("host-agent", "inbound")],
        "127.0.0.1:${WEB_PORT} (default 8380) · image homelab-monitor-web",
    ),
    Card(
        "api",
        "api",
        "app",
        "bolt",
        "compose · FastAPI on :8000",
        "Stateless REST API under /api/v1 (OpenAPI, RFC 9457 errors).",
        [
            "Login, logout and sessions (argon2id, session in Redis, CSRF header)",
            "Dashboard, hosts, monitors, incidents and containers endpoints",
            "Agent ingest: stores heartbeats, detects reboots, opens and closes host incidents",
            "Enqueues send_alert and check-now tasks; /healthz and /readyz",
        ],
        [("postgres", "SQL"), ("redis", "sessions · enqueue")],
        "networks data + egress · mem 192 MB · read-only rootfs, cap_drop ALL",
    ),
    Card(
        "migrate",
        "migrate",
        "app",
        "arrow",
        "compose · one-shot (same image as api)",
        "Runs the schema migrations, then exits.",
        [
            "alembic upgrade head before anything else touches the database",
            "api, workers and beat wait for it (service_completed_successfully)",
            "Every schema change ships as an Alembic revision",
        ],
        [("postgres", "DDL")],
        'restart: "no" · depends on postgres being healthy',
    ),
    Card(
        "beat",
        "beat",
        "tasks",
        "clock",
        "compose · Celery beat, exactly one replica",
        "The clock of the system. Enqueues work, never does it.",
        [
            "15 s schedule_due_checks · 60 s evaluate_hosts, snapshot_containers, check_network",
            "60 s ping_healthcheck (“homelab-monitor” dead man's switch)",
            "03:00 rollup_and_prune · 09:00 check_tls_expiry (Europe/Lisbon)",
            "Schedule lives in code; state file in tmpfs",
        ],
        [("redis", "enqueue")],
        "mem 128 MB · a Redis lock guards against a second beat by mistake",
    ),
    Card(
        "worker-checks",
        "worker-checks",
        "tasks",
        "gear",
        "compose · Celery worker, queue “checks”",
        "Runs the monitor checks, nothing else.",
        [
            "run_check(monitor_id): http status/keyword/latency, dns resolve, tcp connect",
            "Threads pool × 16 because checks are I/O-bound",
            "Stores check_results and drives the PENDING / UP / DOWN state machine",
            "Opens incidents and enqueues send_alert on the default queue",
        ],
        [("redis", "consume / enqueue"), ("postgres", "results"), ("targets", "HTTP · DNS · TCP")],
        "No Celery retries: a failure is a result · expires after one interval",
    ),
    Card(
        "worker-default",
        "worker-default",
        "tasks",
        "gear",
        "compose · Celery worker, queue “default”",
        "Everything that isn't a check, isolated from the checks queue.",
        [
            "schedule_due_checks, evaluate_hosts (STALE after 90 s), check_network",
            "snapshot_containers through docker-proxy (the only service that can reach it)",
            "send_alert: SMTP email, acks_late, backoff for ~1 h, idempotent",
            "rollup_and_prune, check_tls_expiry, ping_healthcheck",
        ],
        [("redis", "consume / enqueue"), ("postgres", "SQL"), ("docker-proxy", "GET"), ("SMTP", "email")],
        "Prefork pool × 2 · networks data + egress + docker · mem 256 MB",
    ),
    Card(
        "docker-proxy",
        "docker-proxy",
        "edge",
        "box",
        "compose · tecnativa/docker-socket-proxy",
        "A read-only gate in front of the Docker socket.",
        [
            "Allows GET /containers/* (plus ping and version); POST is disabled",
            "The raw socket would be root on the VM; the proxy limits it to listing",
            "Socket mounted read-only; on an internal network with worker-default only",
        ],
        [("docker.sock", "read-only")],
        "CONTAINERS=1 · POST=0 · mem 32 MB",
    ),
    Card(
        "postgres",
        "postgres",
        "data",
        "db",
        "compose · PostgreSQL 16 (alpine)",
        "System of record. Everything except sessions lives here.",
        [
            "hosts, heartbeats, boot_events, monitors, check_results, incidents, alerts",
            "containers, container_events and daily_uptime",
            "Raw data kept 30 days, daily summaries ~6 months, then pruned",
            "Named volume pgdata survives restarts, redeploys and reboots",
        ],
        [("api / workers / migrate", "inbound SQL")],
        "Internal network only · no backups by choice · mem 256 MB",
    ),
    Card(
        "redis",
        "redis",
        "data",
        "stack",
        "compose · Redis 7 (alpine)",
        "Fast, disposable state. Losing it only logs you out.",
        [
            "Celery broker with two queues: default and checks",
            "Login sessions with expiry (24 h idle, 7 days absolute)",
            "Short-lived locks and flags: scheduler lock, network outage state",
        ],
        [("api / beat / workers", "inbound")],
        "Password-protected · no persistence · internal network · mem 64 MB",
    ),
    Card(
        "healthchecks",
        "healthchecks.io",
        "external",
        "pulse",
        "SaaS · outside the Mac",
        "Watches the watcher: alerts when the pings stop.",
        [
            "“mac-mini” is pinged by host-agent: macOS is up and online",
            "“homelab-monitor” is pinged every minute by the app (beat schedules, worker-default sends)",
            "Emails the operator when a ping is late, and again when it resumes",
            "Tells “the Mac is down” apart from “only Colima is down”",
        ],
        [("operator", "email")],
        "Ping URLs live in .env only",
    ),
    Card(
        "smtp",
        "SMTP relay",
        "external",
        "mail",
        "Any provider · outside the Mac",
        "Delivers the alert emails sent by worker-default.",
        [
            "Monitor down / recovered, host stale / recovered, unexpected reboot",
            "TLS certificate expiring within 14 days, disk above 90%, local network outage",
            "Never for container changes (those are only recorded)",
        ],
        [("operator", "email")],
        "Host, credentials and recipients live in .env only",
    ),
]

CARD_W = 520


def chip_rows(talks: list[tuple[str, str]]) -> list[list[tuple[float, float, str, str]]]:
    rows: list[list[tuple[float, float, str, str]]] = [[]]
    x = 24.0
    for target, how in talks:
        w = (len(target) + 2) * 7.6 + len(how) * 6.9 + 30
        if rows[-1] and x + w > CARD_W - 24:
            rows.append([])
            x = 24.0
        rows[-1].append((x, w, target, how))
        x += w + 8
    return rows


def card_svg(c: Card) -> str:
    accent, tint, tier_name = TIERS[c.tier]
    duty_lines = [wrap(d, 64) for d in c.duties]
    y_duties = 128
    line_h = 19
    n_lines = sum(len(lines) for lines in duty_lines)
    y_talks = y_duties + 22 + n_lines * line_h + len(c.duties) * 4 + 14
    chips = chip_rows(c.talks)
    h = y_talks + 12 + len(chips) * 34 + 50
    out = [
        svg_open(CARD_W, h, f"{c.name} component", f"{c.name}: {c.what}"),
        f'<rect x="1" y="1" width="{CARD_W - 2}" height="{h - 2}" rx="16" fill="{PAPER}" stroke="{LINE}"/>',
        f'<path d="M1 17a16 16 0 0 1 16-16h{CARD_W - 34}a16 16 0 0 1 16 16v59H1z" fill="{tint}"/>',
        icon(c.icon, 46, 39, 23, accent),
        f'<text x="82" y="35" font-size="21" font-weight="700" fill="{INK}">{escape(c.name)}</text>',
        f'<text x="82" y="56" font-size="12.5" fill="{MUTED}">{escape(c.where)}</text>',
    ]
    pill_w = len(tier_name) * 6.6 + 22
    out.append(
        f'<rect x="{CARD_W - 20 - pill_w}" y="16" width="{pill_w}" height="22" rx="11" fill="{accent}"/>'
        f'<text x="{CARD_W - 20 - pill_w / 2}" y="31" font-size="11.5" font-weight="600" fill="#fff" '
        f'text-anchor="middle">{escape(tier_name)}</text>'
    )
    out.append(
        f'<text x="24" y="102" font-size="14" font-style="italic" fill="{INK}">{escape(c.what)}</text>'
    )
    y = y_duties
    out.append(
        f'<text x="24" y="{y}" font-size="11" font-weight="700" fill="{accent}" letter-spacing="0.6">'
        "RESPONSIBILITIES</text>"
    )
    y += 22
    for lines in duty_lines:
        out.append(f'<circle cx="30" cy="{y - 4.5}" r="3" fill="{accent}"/>')
        for line in lines:
            out.append(f'<text x="42" y="{y}" font-size="13.5" fill="{INK}">{escape(line)}</text>')
            y += line_h
        y += 4
    y = y_talks
    out.append(
        f'<text x="24" y="{y}" font-size="11" font-weight="700" fill="{accent}" letter-spacing="0.6">'
        "TALKS TO</text>"
    )
    y += 12
    for row in chips:
        for x, w, target, how in row:
            out.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="26" rx="13" fill="{tint}" stroke="{accent}" stroke-opacity="0.5"/>'
                f'<text x="{x + 12}" y="{y + 17.5}" font-size="12.5" fill="{INK}"><tspan font-weight="700">'
                f'{"←" if how.startswith("inbound") else "→"} {escape(target)}</tspan><tspan fill="{MUTED}" dx="6">{escape(how)}</tspan></text>'
            )
        y += 34
    y += 16
    out.append(f'<line x1="24" x2="{CARD_W - 24}" y1="{y - 16}" y2="{y - 16}" stroke="{LINE}"/>')
    out.append(
        f'<text x="24" y="{y + 2}" font-size="11.5" fill="{MUTED}" font-family="{MONO}">{escape(c.facts)}</text>'
    )
    out.append("</svg>")
    return "".join(out)


# ----------------------------------------------------------------------------- main


def main() -> None:
    (OUT / "components").mkdir(exist_ok=True)
    (OUT / "flows").mkdir(exist_ok=True)
    written = []
    path = OUT / "architecture.svg"
    path.write_text(architecture() + "\n")
    written.append(path)
    for c in CARDS:
        path = OUT / "components" / f"{c.id}.svg"
        path.write_text(card_svg(c) + "\n")
        written.append(path)
    for f in FLOWS:
        path = OUT / "flows" / f"{f.id}.svg"
        path.write_text(flow_svg(f) + "\n")
        written.append(path)
    for p in written:
        print(p.relative_to(OUT.parent.parent))


if __name__ == "__main__":
    main()
