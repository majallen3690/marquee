"""FastAPI app: one pacing task, N WebSocket subscribers, REST controls."""

import asyncio
import contextlib
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from marquee.server.session import LiveSession

FRAME_INTERVAL_S = 0.05  # 20 frames/sec
VIZ_DIST = Path(__file__).resolve().parents[3] / "viz" / "out"


class PerturbRequest(BaseModel):
    agent_id: int
    param: str
    value: int


class ControlRequest(BaseModel):
    action: str  # pause | resume | speed
    value: float | None = None


def create_app(scenario_path: str | Path, out_dir: str | Path) -> FastAPI:
    session = LiveSession(scenario_path, out_dir)
    subscribers: set[asyncio.Queue] = set()

    async def pacing_loop() -> None:
        loop = asyncio.get_running_loop()
        last = time.monotonic()
        while True:
            await asyncio.sleep(FRAME_INTERVAL_S)
            now = time.monotonic()
            wall_dt, last = now - last, now
            # step() holds the session lock and can churn thousands of engine
            # events — keep it off the event loop.
            frame = await loop.run_in_executor(None, session.step, wall_dt)
            for queue in list(subscribers):
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()  # drop the stale frame, keep latest
                queue.put_nowait(frame)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(pacing_loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="marquee bridge", lifespan=lifespan)
    app.state.session = session

    @app.websocket("/ws")
    async def ws_feed(ws: WebSocket) -> None:
        await ws.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        subscribers.add(queue)
        try:
            while True:
                await ws.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            subscribers.discard(queue)

    @app.get("/api/meta")
    def meta() -> dict:
        return session.meta()

    @app.get("/api/history")
    def history() -> dict:
        return session.history()

    @app.post("/api/perturb")
    def perturb(req: PerturbRequest) -> dict:
        effective = session.perturb(req.agent_id, req.param, req.value)
        return {"effective_ns": effective}

    @app.post("/api/control")
    def control(req: ControlRequest) -> dict:
        if req.action == "pause":
            session.set_paused(True)
        elif req.action == "resume":
            session.set_paused(False)
        elif req.action == "speed":
            if req.value is None:
                raise ValueError("speed requires a value")
            session.set_speed(req.value)
        else:
            raise ValueError(f"unknown action {req.action!r}")
        return {"status": "done" if session.done else ("paused" if session.paused else "live")}

    if VIZ_DIST.is_dir():
        app.mount("/", StaticFiles(directory=VIZ_DIST, html=True), name="viz")

    return app
