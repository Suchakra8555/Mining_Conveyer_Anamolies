from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import analysis, conveyors, simulation, system, vision
from app.core.config import Settings, get_settings
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
        task = asyncio.create_task(_loop(p))
        log.info("conveyor monitoring ready (vision detector: %s)", p.detector.kind)
        yield
        task.cancel()

    app = FastAPI(title="Mining Conveyor Monitoring API", version="1.0", lifespan=lifespan,
                  description="Simulated conveyor monitoring: research-based anomaly detection, failure-risk prediction, vision.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    for r in (system.router, conveyors.router, analysis.router, vision.router, simulation.router):
        app.include_router(r)

    @app.exception_handler(Exception)
    async def _err(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app


app = create_app()
