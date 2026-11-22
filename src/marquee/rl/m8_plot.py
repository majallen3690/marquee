"""Render the M8 answer as a static SVG for the README (ADR-026).

    uv run python -m marquee.rl.m8_plot docs/m8-results.json docs/m8-softens.svg

One row per arm: every seed's move size as a faint dot, the median as a bar with its
95% bootstrap interval. Same hand-written style and palette as `analysis.lever_plot`.
"""

import json
import sys
from pathlib import Path

W, H = 760, 400
L, R, T, B = 190, 40, 96, 56  # plot margins
X0, X1 = 0, 400  # move size, ticks
ROW = 46

SURFACE = "#171614"
GRID = "#2e2d29"
INK1, INK2, INK3 = "#edebe6", "#b4afa6", "#8c887f"
RULE = "#bf8630"  # amber: a rule-based maker in seat 2
LEARNED = "#2e9d8b"  # teal: the learned maker in seat 2
FONT = "Barlow, 'Segoe UI', Helvetica, Arial, sans-serif"

ROWS = (  # (arm, label, color, lever on)
    ("rule, no lever", "rule-based, no lever", RULE, False),
    ("rule, levered", "rule-based, takes the lever", RULE, True),
    ("rule, holds", "rule-based, holds its quotes", RULE, True),
    ("learned, no lever", "learned, no lever", LEARNED, False),
    ("learned", "learned, decides for itself", LEARNED, True),
)


def sx(x: float) -> float:
    return L + (x - X0) / (X1 - X0) * (W - L - R)


def ry(i: int) -> float:
    return T + 14 + i * ROW + (12 if i >= 3 else 0)  # a gap between the two seat types


def text(x, y, s, size=12, fill=INK2, anchor="start", weight=400) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{s}</text>'
    )


def render(results: dict) -> str:
    arms = results["summary"]["arms"]
    p = results["summary"]["primary: learned vs rule, holds"]
    seeds = {a: [abs(r["move"]) for r in results["runs"] if r["arm"] == a] for a, *_ in ROWS}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" font-family="{FONT}" role="img" aria-labelledby="t d">',
        '<title id="t">M8: a learned market maker under the lever</title>',
        '<desc id="d">Size of the price move in the 5 seconds after the lever, over 30 '
        "seeds, for five versions of the second market-maker seat. Rule-based: "
        f"{arms['rule, no lever']['median_move_size']:.0f} ticks with no lever, "
        f"{arms['rule, levered']['median_move_size']:.0f} when it takes the lever, "
        f"{arms['rule, holds']['median_move_size']:.0f} when it holds its quotes. "
        f"Learned: {arms['learned, no lever']['median_move_size']:.1f} with no lever and "
        f"{arms['learned']['median_move_size']:.1f} with the lever. The learned seat's "
        f"move is smaller than the holding rule-based seat's on {p['learned smaller']} "
        "of 30 seeds.</desc>",
        f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>',
        text(
            40,
            32,
            "A learned maker in one seat: the lever stops moving the price",
            17,
            INK1,
            weight=600,
        ),
        text(
            40,
            54,
            "Size of the price move in the 5 s after the lever · 30 seeds · dots are seeds, "
            "bars are medians with 95% intervals",
            12,
            INK2,
        ),
        text(
            40, 76, "Maker 1 takes the lever in every row but the no-lever twins. Seat 2:", 12, INK3
        ),
    ]
    # grid and x axis
    for x in range(X0, X1 + 1, 100):
        out.append(
            f'<line x1="{sx(x):.1f}" y1="{T}" x2="{sx(x):.1f}" y2="{H - B}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(text(sx(x), H - B + 18, str(x), 11, INK3, "middle"))
    out.append(text((L + W - R) / 2, H - 14, "ticks", 12, INK2, "middle"))
    for i, (arm, label, color, lever) in enumerate(ROWS):
        y = ry(i)
        a = arms[arm]
        m, (lo, hi) = a["median_move_size"], a["move_size_ci"]
        weight = 600 if arm in ("rule, holds", "learned") else 400
        out.append(text(L - 14, y + 4, label, 12, INK1 if lever else INK2, "end", weight))
        # seeds: deterministic vertical jitter so ties stay visible
        for k, v in enumerate(sorted(seeds[arm])):
            jy = y + ((k * 7) % 11 - 5)
            out.append(
                f'<circle cx="{sx(v):.1f}" cy="{jy:.1f}" r="2.5" fill="{color}" '
                'fill-opacity="0.35"/>'
            )
        out.append(
            f'<line x1="{sx(lo):.1f}" y1="{y:.1f}" x2="{sx(hi):.1f}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="3" stroke-linecap="round"/>'
        )
        out.append(
            f'<line x1="{sx(m):.1f}" y1="{y - 10:.1f}" x2="{sx(m):.1f}" y2="{y + 10:.1f}" '
            f'stroke="{INK1}" stroke-width="2.5">'
            f"<title>{label}: median {m:.1f} ticks (95% CI {lo:.1f} to {hi:.1f})</title></line>"
        )
        out.append(
            text(sx(hi) + 10, y + 4, f"{m:.0f}" if m >= 20 else f"{m:.1f}", 12, INK1, weight=weight)
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    results = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(render(results), encoding="utf-8")


if __name__ == "__main__":
    main()
