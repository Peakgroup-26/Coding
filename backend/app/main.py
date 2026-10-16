import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .access import enforce
from .db import SessionLocal, engine
from .migrate import migrate
from .autopilot import recover_interrupted
from .routers import (ai, assistant, auth_users, autopilot, boards, chat, civil, estimate, field, jobs, money, ops, people, polish, pricing,
                      project, purchasing, reports, rules, sales, settings, sheets, takeoff, tender, time, workbook)
from . import scheduler
from .seed import seed

logging.basicConfig(level=logging.INFO)

FRONTEND_DIST = config.BASE_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate(engine)
    with SessionLocal() as db:
        seed(db)
    recover_interrupted()
    scheduler.start()
    yield
    scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Lorojo", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    for r in (auth_users.router, settings.router, jobs.router, sheets.router, takeoff.router, rules.router, estimate.router, pricing.router, ai.router, polish.router,
              autopilot.router, civil.router, tender.router, chat.router, reports.router,
              sales.router, ops.router, time.router, field.router, purchasing.router, project.router, money.router, assistant.router,
              people.router, people.me, people.director, boards.router, boards.field, workbook.router):
        app.include_router(r, dependencies=[Depends(enforce)])  # access.enforce: who can see which job
    app.include_router(money.public)  # feedback forms and the Xero sign-in return: no sign-in needed
    app.include_router(people.public)  # the careers page and job applications
    app.include_router(boards.public)  # board forms anyone can fill in

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
