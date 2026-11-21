"""A torch-free subprocess worker for SB3's SubprocVecEnv protocol.

SB3's own worker lives in a stable_baselines3 module, and its env factories travel
wrapped in an SB3 class, so every environment process imports stable_baselines3 and
with it torch, which it never uses. On Windows (spawn) that is several hundred MB of
committed memory per process; sixteen of them exhausted the machine (first in the M7
Stage 1 run, again in the first M7b launch). This module imports only numpy and the
environment, and receives a plain picklable (config, seed) instead of a closure.
The parent side is `train.LeanSubprocVecEnv`.
"""

import multiprocessing as mp

from marquee.rl.env import EnvConfig, MarketMakingEnv


def make_env(cfg: EnvConfig, seed: int) -> MarketMakingEnv:
    env = MarketMakingEnv(cfg)
    env.reset(seed=seed)
    return env


def _is_wrapped(env, wrapper_class) -> bool:
    while env is not None:
        if isinstance(env, wrapper_class):
            return True
        env = getattr(env, "env", None)
    return False


def worker(remote: mp.connection.Connection, parent_remote, cfg: EnvConfig, seed: int) -> None:
    parent_remote.close()
    env = make_env(cfg, seed)
    while True:
        try:
            cmd, data = remote.recv()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "step":
            obs, reward, terminated, truncated, info = env.step(data)
            done = terminated or truncated
            info["TimeLimit.truncated"] = truncated and not terminated
            reset_info: dict = {}
            if done:
                info["terminal_observation"] = obs
                obs, reset_info = env.reset()
            remote.send((obs, reward, done, info, reset_info))
        elif cmd == "reset":
            kwargs = {"options": data[1]} if data[1] else {}
            remote.send(env.reset(seed=data[0], **kwargs))
        elif cmd == "get_spaces":
            remote.send((env.observation_space, env.action_space))
        elif cmd == "env_method":
            remote.send(getattr(env, data[0])(*data[1], **data[2]))
        elif cmd == "get_attr":
            remote.send(getattr(env, data))
        elif cmd == "has_attr":
            remote.send(hasattr(env, data))
        elif cmd == "set_attr":
            setattr(env, data[0], data[1])
            remote.send(None)
        elif cmd == "is_wrapped":
            remote.send(_is_wrapped(env, data))
        elif cmd == "render":
            remote.send(None)
        elif cmd == "close":
            env.close()
            remote.close()
            break
        else:
            raise NotImplementedError(f"`{cmd}` is not implemented in the worker")
