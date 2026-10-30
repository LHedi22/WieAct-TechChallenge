"""All job handlers, imported once so they register. Feature handlers join here from M2 on."""

from app.features.arena import service as arena  # noqa: F401
from app.features.placement import service as placement  # noqa: F401
from app.features.quiz import pool, tagging  # noqa: F401
from app.features.tutor import service as tutor  # noqa: F401
from app.jobs import demo  # noqa: F401
from app.rag import indexing, search  # noqa: F401
