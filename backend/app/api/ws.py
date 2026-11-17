"""Optional WebSocket push. Polling remains the fallback: the dashboard works without this endpoint.

The server only announces *that* something changed ({"type": "update", "version": n, "tick": t}); clients then refetch the
REST endpoints. No data is duplicated over the socket, so REST stays the single source of truth."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["live"])


@router.websocket("/api/ws")
async def updates(ws: WebSocket):
    await ws.accept()
    p = ws.app.state.pipeline
    last = -1
    try:
        while True:
            if p.version != last:
                last = p.version
                await ws.send_json({"type": "update", "version": last, "tick": p.sim.tick, "running": p.sim.running})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        return
