"""All job handlers, imported once so they register. Feature handlers join here from M2 on."""

from app.features.quiz import pool  # noqa: F401
from app.jobs import demo  # noqa: F401
from app.rag import indexing, search  # noqa: F401
