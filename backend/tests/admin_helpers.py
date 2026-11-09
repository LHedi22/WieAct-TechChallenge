"""Shared bits for admin tests: a test-only token and the headers scripts and the UI send."""

from app.core.config import get_settings

TOKEN = "test-only-admin-token-0123456789-abcdef"  # 39 chars, long enough for production
READ = {"X-Admin-Token": TOKEN}
ACT = {**READ, "X-Admin-Action": "1"}


def enable_admin(monkeypatch, token: str = TOKEN) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()


async def seed_class(sm) -> dict:
    """A small synthetic class written straight to the tables: 2 students, a world with one course,
    chapter and document, some ledger rows, a job, a quiz set, an arena thread and a cache entry."""
    import uuid  # noqa: PLC0415
    from datetime import date  # noqa: PLC0415

    from app.core.wallet_rules import tunis_day  # noqa: PLC0415
    from app.models import (  # noqa: PLC0415
        AICache,
        Chapter,
        ClassPoolLedger,
        CoinLedger,
        Course,
        Document,
        Job,
        PeerAnswer,
        PeerQuestion,
        PointsLedger,
        QuizSet,
        StudyAsset,
        User,
        World,
        WorldMember,
    )

    today = tunis_day()
    ana = User(id=uuid.uuid4(), nickname="ana_admin", password_hash="!", ui_language="ar")
    bilel = User(id=uuid.uuid4(), nickname="bilel_admin", password_hash="!", ui_language="fr")
    world = World(id=uuid.uuid4(), name="Olive class", join_code="OLV-ADM", creator_id=ana.id)
    course = Course(id=uuid.uuid4(), world_id=world.id, name="Calculus I", color_key="island1")
    chapter = Chapter(id=uuid.uuid4(), course_id=course.id, idx=0, title="Limits")
    doc = Document(
        id=uuid.uuid4(),
        chapter_id=chapter.id,
        world_id=world.id,
        filename="limits.pdf",
        kind="pdf",
        size=1234,
        sha256="0" * 64,
        storage_path="/nowhere/limits.pdf",
        status="failed",
        error="errors.indexing_failed",
    )
    qid, aid = uuid.uuid4(), uuid.uuid4()
    async with sm() as s:
        s.add_all([ana, bilel])
        await s.flush()
        s.add(world)
        await s.flush()
        s.add_all(
            [
                WorldMember(world_id=world.id, user_id=ana.id),
                WorldMember(world_id=world.id, user_id=bilel.id),
                course,
            ]
        )
        await s.flush()
        s.add(chapter)
        await s.flush()
        s.add(doc)
        s.add_all(
            [
                CoinLedger(
                    user_id=ana.id, day=today, bucket="free", kind="daily", delta=20, ref=None
                ),
                CoinLedger(
                    user_id=ana.id, day=today, bucket="free", kind="spend", delta=-3, ref="j1"
                ),
                CoinLedger(
                    user_id=ana.id,
                    day=date(2026, 1, 1),
                    bucket="earned",
                    kind="earned",
                    delta=7,
                    ref="a1",
                ),
                CoinLedger(
                    user_id=ana.id,
                    day=date(2026, 1, 1),
                    bucket="free",
                    kind="daily",
                    delta=20,
                    ref=None,
                ),  # an old day's free coins don't count
                PointsLedger(user_id=ana.id, world_id=world.id, delta=30, reason="quiz", ref="q1"),
                ClassPoolLedger(world_id=world.id, user_id=bilel.id, kind="contribute", delta=15),
                Job(
                    kind="QUIZ",
                    lane="interactive",
                    status="failed",
                    payload={},
                    stages=[],
                    user_id=ana.id,
                    world_id=world.id,
                    cost=3,
                    error="errors.ai_failed",
                ),
                Job(
                    kind="CHUNK_TAG",
                    lane="background",
                    status="queued",
                    payload={},
                    stages=[],
                    world_id=world.id,
                ),
                QuizSet(
                    world_id=world.id,
                    chapter_id=chapter.id,
                    level="intermediate",
                    language="en",
                    seed=1,
                    questions=[{"q": "lim?"}],
                    provider="mock",
                ),
                StudyAsset(
                    world_id=world.id,
                    chapter_id=chapter.id,
                    level="intermediate",
                    language="ar",
                    kind="notes",
                    content={"sections": []},
                    provider="mock",
                ),
                AICache(
                    key="k-notes-1",
                    task_kind="NOTES_WRITE",
                    content={"value": "x"},
                    model_tier="mid",
                    provider="mock",
                    model="mock-mid",
                    hits=4,
                ),
            ]
        )
        await s.flush()
        s.add(
            PeerQuestion(
                id=qid,
                world_id=world.id,
                chapter_id=chapter.id,
                author_id=ana.id,
                text="Why is 0/0 undefined?",
                language="en",
                status="open",
            )
        )
        await s.flush()
        s.add(
            PeerAnswer(
                id=aid,
                question_id=qid,
                author_id=bilel.id,
                text="Because...",
                status="pending_review",
                ai_score=78,
                ai_confidence="low",
                reviewed_by_mid=False,
                rewarded=False,
            )
        )
        await s.commit()
    return {
        "ana": ana.id,
        "bilel": bilel.id,
        "world": world.id,
        "course": course.id,
        "chapter": chapter.id,
        "document": doc.id,
        "question": qid,
        "answer": aid,
    }
