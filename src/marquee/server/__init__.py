"""M5 live bridge: FastAPI + WebSocket around a stepped kernel (ADR-015).

Everything here is OUTSIDE the sim path (ADR-002): wall-clock pacing decides
how far to step the kernel, never in what order events process — proven by the
stepping-equivalence byte test. Live perturbations go through
kernel.schedule_perturbation and are therefore recorded and replayable.
"""

from marquee.server.session import LiveSession

__all__ = ["LiveSession"]
