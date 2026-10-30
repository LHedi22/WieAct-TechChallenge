from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, dev, economy, health, jobs, system
from app.core.config import get_settings
from app.features.auth import router as auth
from app.features.leaderboard import router as leaderboard
from app.features.onboarding import router as onboarding
from app.features.placement import router as placement
from app.features.quiz import router as quiz
from app.features.tutor import router as tutor
from app.features.wallet import router as wallet
from app.features.wallet.service import InsufficientCoins
from app.features.worlds import map as world_map
from app.features.worlds import router as worlds


def create_app() -> FastAPI:
    # Validates settings first: refuses to start in production unless LLM_PROVIDER=cloud.
    settings = get_settings()
    app = FastAPI(
        title="Learning World API",
        docs_url="/api/docs" if settings.APP_ENV != "production" else None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(InsufficientCoins)
    async def _no_coins(_: Request, e: InsufficientCoins) -> JSONResponse:
        # Any paid start without enough coins: the UI opens the out-of-coins screen.
        return JSONResponse(status_code=402, content={"detail": e.key})

    app.include_router(health.router)
    app.include_router(system.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)
    app.include_router(auth.router)
    app.include_router(economy.router)
    app.include_router(wallet.router)
    app.include_router(leaderboard.router)
    app.include_router(onboarding.router)
    app.include_router(placement.router)
    app.include_router(quiz.router)
    app.include_router(tutor.router)
    app.include_router(worlds.router)
    app.include_router(world_map.router)
    if settings.APP_ENV != "production":
        app.include_router(dev.router)
    return app


app = create_app()
