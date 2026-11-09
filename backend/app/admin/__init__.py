"""The admin side: /api/admin/* (see admin/auth.py for who may use it, docs/ARCHITECTURE.md for
the API surface). English only; every mutation writes an admin_actions row."""

from fastapi import APIRouter

from app.admin import (
    actions,
    browse,
    bundle,
    debug,
    economy_admin,
    inspect,
    session,
    stats,
    switches,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(session.router)
router.include_router(switches.router)
router.include_router(stats.router)
router.include_router(browse.router)
router.include_router(actions.router)
router.include_router(economy_admin.router)
router.include_router(debug.router)
router.include_router(inspect.router)
router.include_router(bundle.router)
