"""The admin side: /api/admin/* (see admin/auth.py for who may use it, docs/ARCHITECTURE.md for
the API surface). English only; every mutation writes an admin_actions row."""

from fastapi import APIRouter

from app.admin import session, stats, switches

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(session.router)
router.include_router(switches.router)
router.include_router(stats.router)
