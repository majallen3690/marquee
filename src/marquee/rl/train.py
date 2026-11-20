"""PPO for the learned market maker (RL_DESIGN §10–11). Checkpointed and resumable.

    uv run --group train python -m marquee.rl.train --run runs/s1 --stage 1 --timesteps 2000000
    uv run --group train python -m marquee.rl.train --run runs/s1 --resume --timesteps 4000000

Every --eval-every steps the current policy is saved and scored, deterministic, on the
VALIDATION episodes (never the held-out gate set); the best by risk-adjusted P&L is kept
as best.zip. progress.jsonl records every evaluation and the training episode stats.
--init starts from another run's model (the curriculum: Stage 0, then Stage 1).
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import dataclasses  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.callbacks import BaseCallback  # noqa: E402
from stable_baselines3.common.vec_env import SubprocVecEnv, VecMonitor  # noqa: E402

from marquee.rl.env import EnvConfig, MarketMakingEnv  # noqa: E402
from marquee.rl.evaluate import VALIDATION, describe, run_eval  # noqa: E402

PPO_KWARGS = {
    "learning_rate": 3e-4,
    "n_steps": 512,  # per env; x16 envs = 8192 steps per update
    "batch_size": 512,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "ent_coef": 0.01,
    "policy_kwargs": {"net_arch": {"pi": [64, 64], "vf": [64, 64]}},
}


def _make(cfg: EnvConfig, seed: int):
    def thunk():
        env = MarketMakingEnv(cfg)
        env.reset(seed=seed)
        return env

    return thunk


class Checkpointing(BaseCallback):
    def __init__(self, run: Path, every: int, eval_workers: int) -> None:
        super().__init__()
        self.run = run
        self.every = every
        self.eval_workers = eval_workers
        self.next_at = 0
        self.best = -np.inf
        log = run / "progress.jsonl"
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.best = max(self.best, rec["val_risk_adjusted"])

    def _on_training_start(self) -> None:
        self.next_at = (self.num_timesteps // self.every + 1) * self.every
        self._t = time.perf_counter()
        self._steps0 = self.num_timesteps

    def _on_step(self) -> bool:
        if self.num_timesteps < self.next_at:
            return True
        self.next_at += self.every
        steps = self.num_timesteps
        ckpt = self.run / f"ckpt_{steps:09d}.zip"
        self.model.save(ckpt)
        shutil.copyfile(ckpt, self.run / "latest.zip")
        val = describe(run_eval(("ppo", str(ckpt)), VALIDATION, workers=self.eval_workers))
        infos = list(self.model.ep_info_buffer)
        fps = (steps - self._steps0) / (time.perf_counter() - self._t)
        rec = {
            "steps": steps,
            "fps": round(fps, 1),
            "train_ep_reward": float(np.mean([i["r"] for i in infos])) if infos else None,
            "val_mean_pnl": val["mean_pnl"],
            "val_std_pnl": val["std_pnl"],
            "val_risk_adjusted": val["risk_adjusted"],
            "val_spread_capture": val["spread_capture"],
            "val_inventory_pnl": val["inventory_pnl"],
        }
        if val["risk_adjusted"] > self.best:
            self.best = val["risk_adjusted"]
            shutil.copyfile(ckpt, self.run / "best.zip")
            rec["best"] = True
        with open(self.run / "progress.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
        return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--stage", type=int, default=1, choices=(0, 1))
    ap.add_argument("--timesteps", type=int, default=2_000_000, help="total, across resumes")
    ap.add_argument("--n-envs", type=int, default=16)
    ap.add_argument("--max-start-s", type=float, default=40.0, help="training start cap")
    ap.add_argument("--eval-every", type=int, default=100_000)
    ap.add_argument("--eval-workers", type=int, default=4)
    ap.add_argument("--gamma-inv", type=float, default=EnvConfig().gamma, help="inventory γ")
    ap.add_argument("--eta", type=float, default=EnvConfig().eta)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--init", type=Path, help="start from this model (curriculum)")
    args = ap.parse_args()

    torch.set_num_threads(1)
    args.run.mkdir(parents=True, exist_ok=True)
    cfg = dataclasses.replace(
        EnvConfig(),
        stage=args.stage,
        gamma=args.gamma_inv,
        eta=args.eta,
        max_start_s=args.max_start_s,
    )
    meta = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}
    meta["env"] = {k: str(v) for k, v in dataclasses.asdict(cfg).items()}
    meta["ppo"] = PPO_KWARGS
    (args.run / "config.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    base_seed = args.seed * 1000
    venv = VecMonitor(
        SubprocVecEnv([_make(cfg, base_seed + i) for i in range(args.n_envs)], start_method="spawn")
    )
    latest = args.run / "latest.zip"
    if args.resume and latest.exists():
        model = PPO.load(latest, env=venv, device="cpu")
        print(f"resumed at {model.num_timesteps} steps", flush=True)
    elif args.init:
        model = PPO.load(args.init, env=venv, device="cpu")
        model.num_timesteps = 0
        print(f"initialised from {args.init}", flush=True)
    else:
        model = PPO("MlpPolicy", venv, seed=args.seed, device="cpu", verbose=0, **PPO_KWARGS)
    remaining = args.timesteps - model.num_timesteps
    if remaining > 0:
        model.learn(
            remaining,
            callback=Checkpointing(args.run, args.eval_every, args.eval_workers),
            reset_num_timesteps=False,
        )
    model.save(latest)
    venv.close()


if __name__ == "__main__":
    main()
