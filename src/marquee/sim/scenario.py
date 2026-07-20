"""Scenario loading and running (config schema per ADR-008/011, manifest per ADR-006)."""

import hashlib
import json

# subprocess: manifest git provenance only, constant argv (see _git_info)
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from marquee.engine import MatchingEngine, SelfTradePolicy
from marquee.sim.kernel import SimKernel
from marquee.sim.protocols import Agent
from marquee.sim.recorder import JsonlRecorder


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_class: str
    agent_id: int
    mean_wake_interval_ns: int
    params: dict


@dataclass(frozen=True, slots=True)
class PerturbationSpec:
    t_ns: int
    agent_id: int
    param: str
    value: int


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    name: str
    master_seed: int
    horizon_ns: int
    self_trade_policy: SelfTradePolicy
    agent_to_exchange_ns: int
    exchange_to_agent_ns: int
    latency_jitter_ns: int
    agents: tuple[AgentSpec, ...]
    perturbations: tuple[PerturbationSpec, ...] = ()


def load_scenario(path: str | Path) -> tuple[ScenarioConfig, bytes]:
    """Returns (config, raw file bytes). The hash covers the raw bytes as
    committed — never a re-serialization (ADR-006)."""
    raw = Path(path).read_bytes()
    doc = yaml.safe_load(raw)
    latency = doc.get("latency", {})
    config = ScenarioConfig(
        name=doc["name"],
        master_seed=int(doc["master_seed"]),
        horizon_ns=int(doc["horizon_ns"]),
        self_trade_policy=SelfTradePolicy[doc.get("self_trade_policy", "ALLOW")],
        agent_to_exchange_ns=int(latency.get("agent_to_exchange_ns", 1_000_000)),
        exchange_to_agent_ns=int(latency.get("exchange_to_agent_ns", 1_000_000)),
        latency_jitter_ns=int(latency.get("jitter_ns", 0)),
        agents=tuple(
            AgentSpec(
                agent_class=a["class"],
                agent_id=int(a["id"]),
                mean_wake_interval_ns=int(a["mean_wake_interval_ns"]),
                params=a.get("params", {}),
            )
            for a in doc["agents"]
        ),
        perturbations=tuple(
            PerturbationSpec(
                t_ns=int(p["t_ns"]),
                agent_id=int(p["agent_id"]),
                param=p["param"],
                value=int(p["value"]),
            )
            for p in doc.get("perturbations", [])
        ),
    )
    return config, raw


def _git_info(repo_root: Path) -> dict:
    # Constant argv, no shell, git resolved from PATH — reviewed, not injectable.
    def run(*args: str) -> str:
        return subprocess.run(  # nosec B603 B607
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=30
        ).stdout.strip()

    sha = run("rev-parse", "HEAD")
    dirty = bool(run("status", "--porcelain"))
    diff_hash = ""
    if dirty:
        diff = subprocess.run(  # nosec B603 B607
            ["git", "diff", "HEAD"], cwd=repo_root, capture_output=True, timeout=30
        ).stdout
        diff_hash = hashlib.sha256(diff).hexdigest()
    return {"git_sha": sha, "dirty": dirty, "dirty_diff_sha256": diff_hash}


def write_manifest(out_dir: Path, config_raw: bytes, config: ScenarioConfig) -> None:
    manifest = {
        "scenario_name": config.name,
        "master_seed": config.master_seed,
        "config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "config_text": config_raw.decode("utf-8"),
        "python_version": sys.version,
        "numpy_version": np.__version__,
        **_git_info(Path(__file__).resolve().parents[3]),
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        f.write("\n")


def build_agent(spec: AgentSpec) -> Agent:
    # Local import: agents depend on sim protocols; scenario loading must not
    # create an import cycle at module import time.
    from marquee.agents import AGENT_REGISTRY

    factory = AGENT_REGISTRY.get(spec.agent_class)
    if factory is None:
        raise KeyError(
            f"unknown agent class {spec.agent_class!r}; registered: {sorted(AGENT_REGISTRY)}"
        )
    return factory(spec.agent_id, spec.params)


def run_scenario(config_path: str | Path, out_dir: str | Path) -> Path:
    """Run a scenario end to end; writes events.jsonl, trades.jsonl, manifest.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    config, raw = load_scenario(config_path)
    engine = MatchingEngine(self_trade_policy=config.self_trade_policy)
    recorder = JsonlRecorder(out / "events.jsonl", out / "trades.jsonl")
    kernel = SimKernel(
        master_seed=config.master_seed,
        engine=engine,
        recorder=recorder,
        horizon_ns=config.horizon_ns,
        agent_to_exchange_ns=config.agent_to_exchange_ns,
        exchange_to_agent_ns=config.exchange_to_agent_ns,
        latency_jitter_ns=config.latency_jitter_ns,
    )
    for spec in config.agents:
        kernel.register_agent(build_agent(spec), spec.mean_wake_interval_ns)
    for perturbation in config.perturbations:
        kernel.schedule_perturbation(
            perturbation.t_ns, perturbation.agent_id, perturbation.param, perturbation.value
        )
    try:
        kernel.run()
    finally:
        recorder.close()
    write_manifest(out, raw, config)
    return out
