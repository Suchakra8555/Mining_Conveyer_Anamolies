from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import analysis, conveyors, simulation, system, vision
from app.core.config import REPO_ROOT, Settings, get_settings
from app.services.pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("conveyor.api")


async def _loop(p: Pipeline):
    while True:
        try:
            if p.sim.running:
                await asyncio.to_thread(p.tick)
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(p.sim.cfg.interval_s)


async def _inference_loop(p: Pipeline, every_s: float):
    """Background inference task: independent of ingestion; idempotent via per-station watermarks."""
    while True:
        try:
            await asyncio.to_thread(p.process_pending)
        except Exception:
            log.exception("inference run failed")
        await asyncio.sleep(every_s)


def create_app(settings: Settings | None = None, warm_start: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        p = Pipeline(settings)
        app.state.pipeline = p
        if warm_start:
            await asyncio.to_thread(p.setup)
        if settings.autostart:
            p.sim.start_simulation()
        tasks = [asyncio.create_task(_loop(p)), asyncio.create_task(_inference_loop(p, settings.inference_interval_s))]
        log.info("conveyor monitoring ready (vision detector: %s)", p.detector.kind)
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="Mining Conveyor Monitoring API", version="1.0", lifespan=lifespan,
                  description="Simulated conveyor monitoring: research-based anomaly detection, failure-risk prediction, vision.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    for r in (system.router, conveyors.router, analysis.router, vision.router, simulation.router):
        app.include_router(r)

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():   # single-process demo: serve the built dashboard (SPA fallback) next to the API
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    @app.exception_handler(Exception)
    async def _err(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app


app = create_app()
