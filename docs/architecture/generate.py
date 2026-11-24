"""Generates the target architecture diagram as draw.io (editable) and SVG (rendered to PNG).

Single source of truth for both formats:
    python docs/architecture/generate.py
    # PNG: render architecture.svg with any browser, e.g. Chrome headless (see README)
"""

from __future__ import annotations

import html
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
W, H = 1760, 1130

COLORS = {  # AWS category colours
    "user": ("#232F3E", "#F2F3F3"),
    "edge": ("#8C4FFF", "#F4EEFF"),
    "security": ("#DD344C", "#FDEBEE"),
    "compute": ("#ED7100", "#FFF3E8"),
    "data": ("#C925D1", "#FBEAFC"),
    "ai": ("#01A88D", "#E6F7F4"),
    "integration": ("#E7157B", "#FDE8F2"),
    "ops": ("#3F8624", "#EDF6E9"),
    "external": ("#545B64", "#FFFFFF"),
}

# id: (title, subtitle, x, y, w, h, kind)
NODES = {
    "user": ("Customer", "Browser / mobile", 30, 470, 150, 70, "user"),
    "cf": ("Amazon CloudFront", "+ AWS WAF & Shield, TLS", 230, 390, 190, 70, "edge"),
    "s3web": ("Amazon S3", "Static web client (OAC)", 230, 520, 190, 60, "data"),
    "apigw": ("Amazon API Gateway", "HTTP API: auth, throttling,\nrequest validation", 470, 390, 200, 76, "edge"),
    "cognito": ("Amazon Cognito", "Optional sign-in; anonymous\nsessions via signed token", 470, 560, 200, 76, "security"),
    "bedrock": ("Amazon Bedrock · Claude", "Tool use via VPC endpoint,\nin-region, no training on data", 760, 170, 270, 76, "ai"),
    "guard": ("Bedrock Guardrails", "PII redaction, denied topics,\nprompt-attack filter", 1080, 175, 260, 66, "ai"),
    "agent": ("Agent Orchestrator", "ECS Fargate · autoscaling\nLLM tool loop, guardrails,\nadaptive-UI composer, guided fallback", 740, 360, 260, 106, "compute"),
    "catalog": ("Configuration & Catalog Service", "ECS Fargate · autoscaling\nrules engine, pricing,\nrecommendation & trade-offs", 1080, 360, 260, 106, "compute"),
    "ddb": ("Amazon DynamoDB", "Session state & conversation\n(TTL, KMS-encrypted)", 740, 560, 260, 70, "data"),
    "catstore": ("Catalog & Rules Store", "Aurora PostgreSQL (versioned\ncatalog) + in-process cache", 1080, 560, 260, 70, "data"),
    "bus": ("Amazon EventBridge", "configuration.completed\n(only with customer consent)", 740, 700, 260, 70, "integration"),
    "sync": ("Catalog Sync", "EventBridge Scheduler + Lambda:\nvalidate & publish catalog version", 1080, 700, 260, 70, "integration"),
    "secrets": ("Secrets Manager · KMS · IAM", "No keys in code; least-privilege\ntask roles; encryption at rest", 740, 830, 260, 70, "security"),
    "pim": ("Product / Pricing / Feasibility", "Existing enterprise systems\n(PIM, price lists, buildability)", 1430, 690, 290, 76, "external"),
    "dealer": ("Dealer / Order / CRM", "Lead hand-over, order entry", 1430, 850, 290, 70, "external"),
    "cw": ("CloudWatch", "Logs, metrics, alarms,\ndashboards", 230, 1000, 230, 70, "ops"),
    "xray": ("X-Ray / ADOT", "OpenTelemetry traces across\nweb → agent → catalog → LLM", 490, 1000, 250, 70, "ops"),
    "llmops": ("LLM telemetry & evals", "Tokens, latency, tool errors,\nfallback rate; offline eval set", 770, 1000, 250, 70, "ops"),
    "lake": ("S3 audit & analytics", "PII-redacted transcripts,\nconversion funnel (Athena)", 1050, 1000, 250, 70, "ops"),
    "cicd": ("CI/CD", "GitHub Actions → ECR →\nECS blue/green deploys", 30, 830, 160, 70, "ops"),
}

GROUPS = [  # (label, x, y, w, h, colour)
    ("AWS Cloud · eu-central-1 (EU data residency)", 200, 110, 1200, 1000, "#232F3E"),
    ("Edge", 215, 360, 220, 240, "#8C4FFF"),
    ("Generative AI (managed)", 740, 130, 620, 135, "#01A88D"),
    ("VPC (private, 3 AZs)", 715, 300, 650, 630, "#00A4A6"),
    ("Observability (all services)", 215, 965, 1120, 130, "#3F8624"),
]

# (src, dst, label, dashed)
EDGES = [
    ("user", "cf", "① HTTPS", False, {"t": 0.35, "dy": -14}),
    ("cf", "s3web", "static assets", False),
    ("cf", "apigw", "② /api/*", False),
    ("apigw", "cognito", "JWT (optional)", True),
    ("apigw", "agent", "③ turn", False, {"dy": -16}),
    ("agent", "bedrock", "④ LLM + tools", False, {"t": 0.3, "dx": 62}),
    ("bedrock", "guard", "", True),
    ("agent", "catalog", "⑤ tool calls", False, {"dy": -16}),
    ("agent", "ddb", "⑥ session state", False),
    ("catalog", "catstore", "", False),
    ("sync", "catstore", "⑦ publish", False),
    ("pim", "sync", "pull / events", False, {"t": 0.35, "dy": -16}),
    ("ddb", "bus", "⑧ streams → pipes", True),
    ("bus", "dealer", "hand-over", False),
]

NOTES = [
    "① SPA served via CloudFront from S3",
    "② Same-origin API; WAF + throttling",
    "③ Each turn is free text or a structured",
    "   UI action (card click, toggle, slider)",
    "④ Claude interprets needs, plans tool calls",
    "   and chooses adaptive UI components",
    "⑤ Prices, rules and compatibility only come",
    "   from the deterministic engine; the agent",
    "   never invents them (grounded UI)",
    "⑥ Stateless containers scale out; state",
    "   lives in DynamoDB with TTL",
    "⑦ Catalog versions pass integrity checks",
    "   before they are published",
    "⑧ Hand-over only with consent",
    "",
    "Resilience: LLM timeout/outage → guided",
    "rule-based mode; retries with backoff;",
    "multi-AZ; health checks; autoscaling",
    "Privacy: no PII in prompts or logs,",
    "Guardrails PII filter, EU region",
    "",
    "Prototype mapping: nginx → CloudFront/S3;",
    "agent & catalog containers → ECS;",
    "in-memory sessions → DynamoDB;",
    "Anthropic API → Bedrock",
]


def center(n):
    _, _, x, y, w, h, _ = NODES[n]
    return x + w / 2, y + h / 2


def clip(n, tx, ty):
    """Point where the segment from node centre to (tx, ty) leaves the node rectangle."""
    _, _, x, y, w, h, _ = NODES[n]
    cx, cy = x + w / 2, y + h / 2
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (w / 2) / abs(dx) if dx else float("inf")
    sy = (h / 2) / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


# --------------------------------------------------------------------------- SVG


def svg() -> str:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             'font-family="Helvetica, Arial, sans-serif">',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#545B64"/></marker></defs>',
             f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
             '<text x="30" y="50" font-size="26" font-weight="700" fill="#232F3E">AI Vehicle Configurator – Target Architecture (AWS)</text>',
             '<text x="30" y="80" font-size="15" fill="#545B64">Conversational agent + deterministic configuration engine + adaptive UI. '
             'Fictional catalog; integration points to enterprise product systems shown on the right.</text>']
    for label, x, y, w, h, color in GROUPS:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="none" stroke="{color}" '
                     f'stroke-width="1.5" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{x + 12}" y="{y + 20}" font-size="13" font-weight="700" fill="{color}">{escape(label)}</text>')
    for src, dst, label, dashed, *extra in EDGES:
        pos = extra[0] if extra else {}
        (tx, ty), (sx0, sy0) = center(dst), center(src)
        x1, y1 = clip(src, tx, ty)
        x2, y2 = clip(dst, sx0, sy0)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#545B64" '
                     f'stroke-width="1.6"{dash} marker-end="url(#arrow)"/>')
        if label:
            t = pos.get("t", 0.5)
            mx = x1 + (x2 - x1) * t + pos.get("dx", 0)
            my = y1 + (y2 - y1) * t + pos.get("dy", 0)
            lines = label.split("\n")
            bw = max(len(line) for line in lines) * 6.6 + 10
            bh = 16 * len(lines) + 4
            parts.append(f'<rect x="{mx - bw / 2:.1f}" y="{my - bh / 2:.1f}" width="{bw:.1f}" height="{bh}" rx="4" '
                         'fill="#FFFFFF" fill-opacity="0.92"/>')
            for i, line in enumerate(lines):
                yy = my - bh / 2 + 14 + i * 16
                parts.append(f'<text x="{mx:.1f}" y="{yy:.1f}" font-size="12" fill="#232F3E" text-anchor="middle">{escape(line)}</text>')
    for title, sub, x, y, w, h, kind in NODES.values():
        stroke, fill = COLORS[kind]
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{stroke}"/>')
        parts.append(f'<text x="{x + 16}" y="{y + 22}" font-size="14" font-weight="700" fill="#232F3E">{escape(title)}</text>')
        for i, line in enumerate(sub.split("\n")):
            parts.append(f'<text x="{x + 16}" y="{y + 41 + i * 16}" font-size="12" fill="#3B4450">{escape(line)}</text>')
    parts.append('<text x="1430" y="150" font-size="14" font-weight="700" fill="#232F3E">Flow &amp; key decisions</text>')
    for i, note in enumerate(NOTES):
        parts.append(f'<text x="1430" y="{172 + i * 18}" font-size="12.5" fill="#3B4450" xml:space="preserve">{escape(note)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- draw.io


def drawio() -> str:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    cells.append('<mxCell id="title" value="AI Vehicle Configurator – Target Architecture (AWS)" '
                 'style="text;fontSize=24;fontStyle=1;align=left;verticalAlign=middle;" vertex="1" parent="1">'
                 '<mxGeometry x="30" y="30" width="900" height="34" as="geometry"/></mxCell>')
    for i, (label, x, y, w, h, color) in enumerate(GROUPS):
        style = (f"rounded=1;arcSize=2;dashed=1;fillColor=none;strokeColor={color};fontColor={color};fontStyle=1;"
                 "align=left;verticalAlign=top;spacingLeft=10;spacingTop=4;container=0;")
        cells.append(f'<mxCell id="g{i}" value="{html.escape(label)}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    for nid, (title, sub, x, y, w, h, kind) in NODES.items():
        stroke, fill = COLORS[kind]
        value = html.escape(f"<b>{escape(title)}</b><br><font style='font-size:11px'>{escape(sub).replace(chr(10), '<br>')}</font>")
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=2;"
                 "align=left;verticalAlign=top;spacingLeft=10;spacingTop=4;fontSize=13;")
        cells.append(f'<mxCell id="{nid}" value="{value}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    for i, (src, dst, label, dashed, *_pos) in enumerate(EDGES):
        style = ("endArrow=block;endFill=1;html=1;strokeColor=#545B64;strokeWidth=1.5;fontSize=11;"
                 "labelBackgroundColor=#FFFFFF;" + ("dashed=1;" if dashed else ""))
        cells.append(f'<mxCell id="e{i}" value="{html.escape(label).replace(chr(10), "&lt;br&gt;")}" style="{style}" '
                     f'edge="1" parent="1" source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    notes = "<b>Flow &amp; key decisions</b><br>" + "<br>".join(escape(n) for n in NOTES)
    cells.append(f'<mxCell id="notes" value="{html.escape(notes)}" style="text;html=1;align=left;verticalAlign=top;'
                 f'fontSize=12;whiteSpace=wrap;" vertex="1" parent="1"><mxGeometry x="1420" y="130" width="330" height="480" '
                 'as="geometry"/></mxCell>')
    body = "".join(cells)
    return ('<mxfile host="generate.py"><diagram name="Target architecture" id="arch">'
            f'<mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" pageWidth="{W}" pageHeight="{H}">'
            f'<root>{body}</root></mxGraphModel></diagram></mxfile>')


if __name__ == "__main__":
    (OUT / "architecture.svg").write_text(svg(), encoding="utf-8")
    (OUT / "architecture.drawio").write_text(drawio(), encoding="utf-8")
    print("wrote architecture.svg and architecture.drawio")
