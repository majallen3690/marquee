"""PPO for the learned market maker (RL_DESIGN §10–11). Checkpointed and resumable.

    uv run --group train python -m marquee.rl.train --run runs/s1 --stage 1 --timesteps 2000000
    uv run --group train python -m marquee.rl.train --run runs/s1 --resume --timesteps 4000000

Every --eval-every steps the current policy is saved and scored, deterministic, on the
VALIDATION episodes (never the held-out gate set); the best by risk-adjusted P&L is kept
as best.zip. progress.jsonl records every evaluation and the training episode stats.
--init starts from another run's model (the curriculum: Stage 0, then Stage 1).

torch and SB3 are imported inside main(), and environment processes run
`marquee.rl.vec.worker`, which imports neither: copies of torch that the workers never
use exhausted memory twice (the first Stage 1 run, the first M7b launch). Validation
runs in this process, on the live model, for the same reason.
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

from marquee.rl.env import EnvConfig  # noqa: E402
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


def _checkpointing(run: Path, every: int):
    from stable_baselines3.common.callbacks import BaseCallback

    class Checkpointing(BaseCallback):
        def __init__(self) -> None:
            super().__init__()
            self.best = -np.inf
            log = run / "progress.jsonl"
            if log.exists():
                for line in log.read_text(encoding="utf-8").splitlines():
                    self.best = max(self.best, json.loads(line)["val_risk_adjusted"])

        def _on_training_start(self) -> None:
            self.next_at = (self.num_timesteps // every + 1) * every
            self.t0 = time.perf_counter()
            self.steps0 = self.num_timesteps

        def _on_step(self) -> bool:
            if self.num_timesteps < self.next_at:
                return True
            self.next_at += every
            steps = self.num_timesteps
            ckpt = run / f"ckpt_{steps:09d}.zip"
            self.model.save(ckpt)
            shutil.copyfile(ckpt, run / "latest.zip")
            val = describe(run_eval(("model", self.model), VALIDATION, workers=1))
            infos = list(self.model.ep_info_buffer)
            rec = {
                "steps": steps,
                "fps": round((steps - self.steps0) / (time.perf_counter() - self.t0), 1),
                "train_ep_reward": float(np.mean([i["r"] for i in infos])) if infos else None,
                "val_mean_pnl": val["mean_pnl"],
                "val_std_pnl": val["std_pnl"],
                "val_risk_adjusted": val["risk_adjusted"],
                "val_spread_capture": val["spread_capture"],
                "val_inventory_pnl": val["inventory_pnl"],
            }
            if val["risk_adjusted"] > self.best:
                self.best = val["risk_adjusted"]
                shutil.copyfile(ckpt, run / "best.zip")
                rec["best"] = True
            with open(run / "progress.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
            return True

    return Checkpointing()


def _lean_vec_env(cfgs_seeds):
    """SubprocVecEnv whose processes never import SB3 or torch (see marquee.rl.vec)."""
    import multiprocessing as mp

    from stable_baselines3.common.vec_env import SubprocVecEnv
    from stable_baselines3.common.vec_env.base_vec_env import VecEnv

    from marquee.rl import vec

    class LeanSubprocVecEnv(SubprocVecEnv):
        def __init__(self, items) -> None:
            self.waiting = False
            self.closed = False
            ctx = mp.get_context("spawn")
            self.remotes, self.work_remotes = zip(*[ctx.Pipe() for _ in items], strict=True)
            self.processes = []
            for work_remote, remote, (cfg, seed) in zip(
                self.work_remotes, self.remotes, items, strict=True
            ):
                proc = ctx.Process(
                    target=vec.worker, args=(work_remote, remote, cfg, seed), daemon=True
                )
                proc.start()
                self.processes.append(proc)
                work_remote.close()
            self.remotes[0].send(("get_spaces", None))
            observation_space, action_space = self.remotes[0].recv()
            VecEnv.__init__(self, len(items), observation_space, action_space)

        def env_is_wrapped(self, wrapper_class, indices=None):
            # no wrappers by construction; asking would send an SB3 class to the workers
            return [False] * len(self._get_indices(indices))

    return LeanSubprocVecEnv(cfgs_seeds)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--stage", type=int, default=1, choices=(0, 1))
    ap.add_argument("--timesteps", type=int, default=2_000_000, help="total, across resumes")
    ap.add_argument("--n-envs", type=int, default=16)
    ap.add_argument("--max-start-s", type=float, default=40.0, help="training start cap")
    ap.add_argument("--eval-every", type=int, default=100_000)
    ap.add_argument("--gamma-inv", type=float, default=EnvConfig().gamma, help="inventory γ")
    ap.add_argument("--eta", type=float, default=EnvConfig().eta)
    ap.add_argument("--lr", type=float, default=PPO_KWARGS["learning_rate"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--init", type=Path, help="start from this model (curriculum)")
    args = ap.parse_args()

    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import VecMonitor

    torch.set_num_threads(1)
    args.run.mkdir(parents=True, exist_ok=True)
    cfg = dataclasses.replace(
        EnvConfig(),
        stage=args.stage,
        gamma=args.gamma_inv,
        eta=args.eta,
        max_start_s=args.max_start_s,
    )
    ppo_kwargs = {**PPO_KWARGS, "learning_rate": args.lr}
    meta = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}
    meta["env"] = {k: str(v) for k, v in dataclasses.asdict(cfg).items()}
    meta["ppo"] = ppo_kwargs
    (args.run / "config.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    base_seed = args.seed * 1000
    venv = VecMonitor(_lean_vec_env([(cfg, base_seed + i) for i in range(args.n_envs)]))
    latest = args.run / "latest.zip"
    if args.resume and latest.exists():
        model = PPO.load(latest, env=venv, device="cpu")
        print(f"resumed at {model.num_timesteps} steps", flush=True)
    elif args.init:
        model = PPO.load(args.init, env=venv, device="cpu", learning_rate=args.lr)
        model.num_timesteps = 0
        print(f"initialised from {args.init}", flush=True)
    else:
        model = PPO("MlpPolicy", venv, seed=args.seed, device="cpu", verbose=0, **ppo_kwargs)
    remaining = args.timesteps - model.num_timesteps
    if remaining > 0:
        model.learn(
            remaining, callback=_checkpointing(args.run, args.eval_every), reset_num_timesteps=False
        )
    model.save(latest)
    venv.close()


if __name__ == "__main__":
    main()
