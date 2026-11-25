"""Generates the target architecture diagram: architecture.svg (rendered to PNG) and architecture.drawio (editable).

    python3 docs/architecture/generate.py      # or: make diagram

The SVG embeds the AWS Architecture Icons from ./icons; the draw.io file uses draw.io's built-in AWS shapes.
PNG: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --hide-scrollbars \
       --force-device-scale-factor=2 --window-size=1500,720 --screenshot=architecture.png architecture.svg
"""

from __future__ import annotations

import base64
import html
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
W, H = 1500, 720
INK, MUTED, LINE = "#232F3E", "#5F6B7A", "#545B64"
ICON = 64  # icon size in px; arrows attach to the icon's edges

# id: (title, subtitle, icon file, centre x, centre y, draw.io resIcon or raw "shape=..." style, colour)
NODES = {
    "users": ("Customer", "Browser", "users.png", 100, 300, "shape=mxgraph.aws4.users", INK),
    "cloudfront": ("Amazon CloudFront", "with AWS WAF", "cloudfront.png", 300, 300, "cloudfront", "#8C4FFF"),
    "s3": ("Amazon S3", "Web app files", "s3.png", 300, 540, "s3", "#7AA116"),
    "alb": ("Application LB", "internal (VPC origin)", "elastic-load-balancing.png", 540, 300,
            "elastic_load_balancing", "#8C4FFF"),
    "agent": ("Agent service", "ECS Fargate · AI tool loop", "fargate.png", 760, 300, "fargate", "#ED7100"),
    "dynamodb": ("Amazon DynamoDB", "Chat sessions", "dynamodb.png", 760, 540, "dynamodb", "#C925D1"),
    "bedrock": ("Amazon Bedrock", "LLM (prototype: OpenAI)", "bedrock.png", 1080, 300, "bedrock", "#01A88D"),
    "secrets": ("Secrets Manager", "API keys", "secrets-manager.png", 950, 540, "secrets_manager", "#DD344C"),
    "cloudwatch": ("Amazon CloudWatch", "Logs, metrics", "cloudwatch.png", 1100, 540, "cloudwatch_2", "#E7157B"),
    # Run by its own team; the prototype stands in for it with services/catalog.
    "catalog": ("Catalog & rules API", "prices, options, rules", "external-system.png", 1350, 300,
                "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.general", INK),
}

# (from, to, label, bend points between the two icons, index of the segment that carries the label)
# Labels sit in the middle of their segment; LABEL_AT moves one along it (0 = start, 1 = end).
LABEL_AT = {("users", "cloudfront"): 0.2, ("agent", "bedrock"): 0.6}
EDGES = [
    ("users", "cloudfront", "HTTPS", [], 0),
    ("cloudfront", "s3", "app files", [], 0),
    ("cloudfront", "alb", "/api", [], 0),
    ("alb", "agent", "chat turns", [], 0),
    ("agent", "bedrock", "LLM + tool use", [], 0),
    ("agent", "catalog", "tool calls · HTTPS API", [(760, 205), (1350, 205)], 1),
    ("agent", "dynamodb", "session state · VPC endpoint", [], 0),
]

# (label, x, y, w, h, colour, dashed, draw.io group icon)
GROUPS = [
    ("AWS Cloud · eu-central-1", 190, 120, 1010, 560, INK, False, "group_aws_cloud_alt"),
    ("VPC · private subnets, multi-AZ", 450, 170, 430, 250, "#8C4FFF", False, "group_vpc2"),
    ("Catalog team · own system", 1235, 160, 230, 260, MUTED, True, "group_corporate_data_center"),
]

TITLE = "AI Vehicle Configurator · target architecture on AWS"


def icon_data(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode((OUT / "icons" / name).read_bytes()).decode()


def anchor(nid: str, towards: tuple[float, float]) -> tuple[float, float]:
    """Point on the icon's edge facing `towards` (icons are square, arrows are horizontal or vertical)."""
    _, _, _, cx, cy, *_ = NODES[nid]
    dx, dy = towards[0] - cx, towards[1] - cy
    half = ICON / 2 + 6
    if abs(dx) >= abs(dy):
        return (cx + (half if dx > 0 else -half), cy)
    # Going down, start below the title and subtitle under the icon.
    return (cx, cy + (ICON / 2 + 52 if dy > 0 else -half))


def edge_points(src: str, dst: str, bends: list[tuple[int, int]]) -> list[tuple[float, float]]:
    s, d = NODES[src], NODES[dst]
    first = bends[0] if bends else (d[3], d[4])
    last = bends[-1] if bends else (s[3], s[4])
    return [anchor(src, first), *bends, anchor(dst, last)]


# --------------------------------------------------------------------------- SVG


def svg() -> str:
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         'font-family="Helvetica Neue, Helvetica, Arial, sans-serif">',
         '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>',
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
         f'<text x="40" y="70" font-size="26" font-weight="700" fill="{INK}">{escape(TITLE)}</text>']
    for label, x, y, w, h, color, dashed, _ in GROUPS:
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width="1.5"{dash}/>')
        p.append(f'<rect x="{x}" y="{y}" width="{len(label) * 7.6 + 24}" height="26" fill="{color}"/>')
        p.append(f'<text x="{x + 12}" y="{y + 18}" font-size="13" font-weight="700" fill="#FFFFFF">{escape(label)}</text>')
    for src, dst, label, bends, seg in EDGES:
        pts = edge_points(src, dst, bends)
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.0f},{y:.0f}" for i, (x, y) in enumerate(pts))
        p.append(f'<path d="{path}" fill="none" stroke="{LINE}" stroke-width="1.8" marker-end="url(#arrow)"/>')
        (x1, y1), (x2, y2) = pts[seg], pts[seg + 1]
        t = LABEL_AT.get((src, dst), 0.5)
        mx, my = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        bw = len(label) * 7 + 14
        p.append(f'<rect x="{mx - bw / 2:.0f}" y="{my - 11:.0f}" width="{bw:.0f}" height="22" rx="11" '
                 f'fill="#FFFFFF" stroke="#D5DBDB"/>')
        p.append(f'<text x="{mx:.0f}" y="{my + 4.5:.0f}" font-size="12.5" fill="{INK}" text-anchor="middle">{escape(label)}</text>')
    for title, sub, icon, cx, cy, *_ in NODES.values():
        p.append(f'<image href="{icon_data(icon)}" x="{cx - ICON / 2}" y="{cy - ICON / 2}" width="{ICON}" height="{ICON}"/>')
        p.append(f'<text x="{cx}" y="{cy + ICON / 2 + 22}" font-size="14" font-weight="700" fill="{INK}" '
                 f'text-anchor="middle">{escape(title)}</text>')
        p.append(f'<text x="{cx}" y="{cy + ICON / 2 + 40}" font-size="12.5" fill="{MUTED}" text-anchor="middle">{escape(sub)}</text>')
    p.append("</svg>")
    return "\n".join(p)


# --------------------------------------------------------------------------- draw.io


def drawio() -> str:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>',
             f'<mxCell id="title" value="{html.escape(TITLE)}" style="text;fontSize=24;fontStyle=1;align=left;" '
             'vertex="1" parent="1"><mxGeometry x="30" y="40" width="900" height="34" as="geometry"/></mxCell>']
    for i, (label, x, y, w, h, color, dashed, gr_icon) in enumerate(GROUPS):
        style = (f"points=[];outlineConnect=0;html=1;whiteSpace=wrap;fontSize=12;fontStyle=1;container=0;"
                 f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};strokeColor={color};fillColor=none;"
                 f"verticalAlign=top;align=left;spacingLeft=30;fontColor={color};dashed={int(dashed)};")
        cells.append(f'<mxCell id="g{i}" value="{html.escape(label)}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    for nid, (title, sub, _icon, cx, cy, res_icon, color) in NODES.items():
        value = html.escape(f"<b>{escape(title)}</b><br><font color='{MUTED}'>{escape(sub)}</font>")
        common = ("outlineConnect=0;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
                  f"fontSize=12;fontColor={INK};aspect=fixed;")
        if res_icon.startswith("shape="):
            style = f"{common}{res_icon};fillColor={color};strokeColor=#ffffff;"
        else:
            style = f"{common}shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon};fillColor={color};strokeColor=#ffffff;"
        cells.append(f'<mxCell id="{nid}" value="{value}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{cx - ICON / 2}" y="{cy - ICON / 2}" width="{ICON}" height="{ICON}" as="geometry"/></mxCell>')
    for i, (src, dst, label, bends, _seg) in enumerate(EDGES):
        style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor={LINE};"
                 "strokeWidth=1.5;fontSize=11;labelBackgroundColor=#FFFFFF;")
        points = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in bends)
        geometry = (f'<mxGeometry relative="1" as="geometry"><Array as="points">{points}</Array></mxGeometry>' if bends
                    else '<mxGeometry relative="1" as="geometry"/>')
        cells.append(f'<mxCell id="e{i}" value="{html.escape(label)}" style="{style}" edge="1" parent="1" '
                     f'source="{src}" target="{dst}">{geometry}</mxCell>')
    return ('<mxfile host="generate.py"><diagram name="Target architecture" id="arch">'
            f'<mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" pageWidth="{W}" pageHeight="{H}">'
            f'<root>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>')


if __name__ == "__main__":
    (OUT / "architecture.svg").write_text(svg(), encoding="utf-8")
    (OUT / "architecture.drawio").write_text(drawio(), encoding="utf-8")
    print("wrote architecture.svg and architecture.drawio")
