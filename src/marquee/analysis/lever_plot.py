"""Render the lever study's dose-response as a static SVG for the README (ADR-022).

    uv run python -m marquee.analysis.lever_plot docs/lever-study.json docs/lever-dose.svg

Hand-written SVG, no plotting dependency. Colors are validated for a dark surface
(dataviz validator: lightness band, chroma, CVD and normal-vision separation, contrast).
"""

import json
import sys
from pathlib import Path

W, H = 760, 430
L, R, T, B = 64, 150, 92, 64  # plot margins
X0, X1 = 2, 12  # maker 1 half-spread, ticks
Y0, Y1 = 0, 200  # median 5 s move, ticks

SURFACE = "#171614"
GRID = "#2e2d29"
INK1, INK2, INK3 = "#edebe6", "#b4afa6", "#8c887f"
SPREAD = "#bf8630"  # amber: the active ingredient
FULL = "#2e9d8b"  # teal: the committed four-part lever
FONT = "Barlow, 'Segoe UI', Helvetica, Arial, sans-serif"


def sx(x: float) -> float:
    return L + (x - X0) / (X1 - X0) * (W - L - R)


def sy(y: float) -> float:
    return H - B - (y - Y0) / (Y1 - Y0) * (H - T - B)


def series(study: dict, key: str) -> list[tuple[int, float, float, float]]:
    """(maker-1 half-spread, median move, ci lo, ci hi), starting from the control.
    Dose 0.1 leaves maker 1 at its normal 2 ticks, so it is not plotted."""
    c = study["control"]
    pts = [(2, c["median_move"], *c["median_move_ci"])]
    for d in study[key].values():
        hs = d["params"]["1.half_spread"]
        if hs > 2:
            pts.append((hs, d["median_move"], *d["median_move_ci"]))
    return pts


def text(x, y, s, size=12, fill=INK2, anchor="start", weight=400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{s}</text>'
    )


def render(study: dict) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" font-family="{FONT}" role="img" aria-labelledby="t d">',
        '<title id="t">Lever study: dose-response</title>',
        '<desc id="d">Median price move in the 5 seconds after the lever, over 30 seeds, '
        "against how far the market makers quote from the best price. Widening quotes "
        "alone raises the move steadily from 27 to 152 ticks; the full lever, which also "
        "cuts size and inventory limits, levels off near 65.</desc>",
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        text(
            L,
            32,
            "Distance, not depth: how far makers step back sets the move",
            17,
            INK1,
            weight=600,
        ),
        text(
            L,
            54,
            "Median price move in the 5 s after the lever · 30 seeds · bars are 95% "
            "bootstrap intervals",
            12,
            INK2,
        ),
    ]
    # legend, one row
    lx = L
    for color, label in (
        (SPREAD, "widen quotes only"),
        (FULL, "full lever (also cuts size and limits)"),
    ):
        out.append(
            f'<line x1="{lx}" y1="74" x2="{lx + 18}" y2="74" stroke="{color}" stroke-width="2"/>'
        )
        out.append(
            f'<circle cx="{lx + 9}" cy="74" r="4" fill="{color}" stroke="{SURFACE}" '
            'stroke-width="2"/>'
        )
        out.append(text(lx + 24, 78, label, 12, INK2))
        lx += 24 + 7 * len(label) + 28
    # grid and y axis
    for y in range(Y0, Y1 + 1, 50):
        out.append(
            f'<line x1="{L}" y1="{sy(y):.1f}" x2="{W - R}" y2="{sy(y):.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(text(L - 8, sy(y) + 4, str(y), 11, INK3, "end"))
    out.append(text(L - 8, T - 12, "ticks", 11, INK3, "end"))
    # x axis
    for x in (2, 3, 4, 5, 7, 9, 12):
        out.append(text(sx(x), H - B + 18, str(x), 11, INK3, "middle"))
    out.append(text(sx(2), H - B + 32, "normal", 11, INK3, "middle"))
    out.append(
        text(
            (L + W - R) / 2,
            H - 14,
            "Maker 1 quoting distance after the lever (ticks from the best price)",
            12,
            INK2,
            "middle",
        )
    )
    # control reference
    c = study["control"]["median_move"]
    out.append(
        f'<line x1="{L}" y1="{sy(c):.1f}" x2="{W - R}" y2="{sy(c):.1f}" '
        f'stroke="{INK3}" stroke-width="1.5" stroke-dasharray="4 4"/>'
    )
    out.append(text(W - R + 16, sy(c) + 4, f"no lever {c:.0f}", 12, INK2))
    # series: interval bars, then line, then markers on top
    for key, color, dx in (("doses", FULL, 0.09), ("spread_doses", SPREAD, -0.09)):
        pts = series(study, key)
        for x, _m, lo, hi in pts[1:]:
            out.append(
                f'<line x1="{sx(x + dx):.1f}" y1="{sy(lo):.1f}" x2="{sx(x + dx):.1f}" '
                f'y2="{sy(hi):.1f}" stroke="{color}" stroke-width="1.5" '
                'stroke-opacity="0.55" stroke-linecap="round"/>'
            )
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(x + (dx if i else 0)):.1f},{sy(m):.1f}"
            for i, (x, m, _lo, _hi) in enumerate(pts)
        )
        out.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
            'stroke-linejoin="round"/>'
        )
        for i, (x, m, lo, hi) in enumerate(pts):
            out.append(
                f'<circle cx="{sx(x + (dx if i else 0)):.1f}" cy="{sy(m):.1f}" r="4" '
                f'fill="{color}" stroke="{SURFACE}" stroke-width="2">'
                f"<title>{x} ticks: median {m:.1f} (95% CI {lo:.1f} to {hi:.1f})</title>"
                "</circle>"
            )
        x, m, _lo, _hi = pts[-1]
        label = "widen only" if key == "spread_doses" else "full lever"
        out.append(text(W - R + 16, sy(m) + 4, f"{label} {m:.0f}", 12, INK1))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    study = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(render(study), encoding="utf-8")


if __name__ == "__main__":
    main()
