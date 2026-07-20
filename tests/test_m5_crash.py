"""M5 core gate: the flash crash emerges from the committed scenario and the
perturbed run is fully reproducible (ADR-010 replay mode c, config-scheduled).

The crash is asserted by script criteria committed in the scenario file: a
calm pre-market, then a post-perturbation move that dwarfs the market's own
worst normal burst. The live-insertion variant of replay (c) — perturbations
injected from the UI mid-run — lands with the M5 bridge.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from marquee.analysis import compute_run_stats
from marquee.analysis.stylized_facts import sample_mid_series
from marquee.sim import run_scenario
from marquee.sim.scenario import load_scenario

SCENARIO = Path(__file__).parents[1] / "scenarios" / "m5-flash-crash.yaml"
WORKER = Path(__file__).parent / "_scenario_worker.py"


def run_and_criteria(tmp_path):
    config, raw = load_scenario(SCENARIO)
    criteria = yaml.safe_load(raw)["crash_criteria"]
    out = run_scenario(SCENARIO, tmp_path / "run")
    return config, criteria, out


def test_flash_crash_emerges_and_dwarfs_normal_bursts(tmp_path) -> None:
    config, criteria, out = run_and_criteria(tmp_path)
    interval = 100_000_000
    mids = sample_mid_series(out, config.self_trade_policy, config.horizon_ns, interval)

    t_index = criteria["perturbation_t_ns"] // interval
    pre_len = criteria["pre_window_ns"] // interval
    post_len = criteria["post_window_ns"] // interval

    pre = mids[t_index - pre_len : t_index]
    post = mids[t_index : t_index + post_len]
    mid_at_t = mids[t_index - 1]

    post_move = max(abs(m - mid_at_t) for m in post)
    pre_worst = max(
        max(pre[i : i + post_len]) - min(pre[i : i + post_len])
        for i in range(0, len(pre) - post_len, post_len // 5)
    )

    assert post_move >= criteria["min_post_move_ticks"], (
        f"no crash: post move {post_move:.1f} ticks < {criteria['min_post_move_ticks']}"
    )
    assert post_move >= criteria["min_amplification"] * pre_worst, (
        f"crash does not dwarf normal bursts: post {post_move:.1f} vs "
        f"pre worst {pre_worst:.1f} (need {criteria['min_amplification']}x)"
    )

    # The market survives as a market — crashed, not dead.
    stats = compute_run_stats(out, config.self_trade_policy, config.horizon_ns)
    assert stats.two_sided_pct >= criteria["min_two_sided_pct"]


def test_perturbations_recorded_match_schedule_roundtrip(tmp_path) -> None:
    """events.jsonl must contain exactly the configured perturbations, with
    heap keys — the extraction half of replay mode (c)."""
    config, _, out = run_and_criteria(tmp_path)
    recorded = []
    with open(out / "events.jsonl", encoding="utf-8", newline="\n") as f:
        for line in f:
            ev = json.loads(line)
            if ev["k"] == "prt":
                assert {"t", "p", "s", "aid", "prm", "v"} <= set(ev)
                recorded.append((ev["t"], ev["aid"], ev["prm"], ev["v"]))
    expected = [(p.t_ns, p.agent_id, p.param, p.value) for p in config.perturbations]
    assert recorded == expected


def test_perturbed_run_replays_byte_identically(tmp_path) -> None:
    """Replay mode (c): same seed + config + perturbation schedule, two
    subprocesses, different PYTHONHASHSEED → identical output bytes."""

    def run(hash_seed: str, out_dir: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = hash_seed
        result = subprocess.run(
            [sys.executable, str(WORKER), str(SCENARIO), str(out_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=600,
        )
        return dict(line.split(":", 1) for line in result.stdout.strip().splitlines())

    assert run("1", tmp_path / "a") == run("2", tmp_path / "b")
