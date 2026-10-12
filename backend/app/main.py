import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import SessionLocal, engine
from .migrate import migrate
from .routers import ai, auth_users, estimate, jobs, polish, pricing, rules, settings, sheets, takeoff
from .seed import seed

logging.basicConfig(level=logging.INFO)

FRONTEND_DIST = config.BASE_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate(engine)
    with SessionLocal() as db:
        seed(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Peak Hydraulic Take-off", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    for r in (auth_users.router, settings.router, jobs.router, sheets.router, takeoff.router, rules.router, estimate.router, pricing.router, ai.router, polish.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # Serve the built frontend from the same origin when it exists.
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = FRONTEND_DIST / path
            if path and f.is_file() and FRONTEND_DIST.resolve() in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
