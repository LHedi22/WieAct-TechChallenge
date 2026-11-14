"""Audit OPT-02 (N-6 root cause): pick_context round-robined over each chunk's first tag in
document order. When most chunks have distinct first tags (the Stacks-and-queues deck: 12 slides,
11 different first tags) that is just "the first 6 chunks": slides 1-5 + 7, and the notes, audio
and quiz never saw queues. It now spreads over the start, middle and end of the chapter
(round-robin over concepts inside each part, vector hits first) and fills a character budget."""

import uuid

from app.features.quiz.pool import CONTEXT_CHARS, pick_context
from app.models import Chunk

DOC = uuid.uuid4()
# logs/40-stacks-chunks-mock.txt: (slide, first tag, text)
SLIDES = [
    (1, "plates", "Stacks A stack is a LIFO structure: last in, first out."),
    (2, "operations", "Stack operations push(x) adds on top, pop() removes the top."),
    (3, "array", "Array-based stack Keep an array and a top index."),
    (4, "capacity", "Linked stack Each push creates a node pointing to the previous one."),
    (5, "balanced", "Uses of stacks Undo history, the call stack, balanced brackets."),
    (6, "balanced", "Balanced brackets Push every opening bracket; pop on a closing one."),
    (7, "bakery", "Queues A queue is FIFO: first in, first out, like a line at a bakery."),
    (8, "dequeue", "Queue operations enqueue(x) adds at the back, dequeue() removes."),
    (9, "around", "Circular buffer An array with head and tail indices that wrap."),
    (10, "dequeue", "Linked queue Keep pointers to head and tail nodes."),
    (11, "buffering", "Uses of queues Printer jobs, BFS on graphs, task scheduling."),
    (12, "queue", "Stack vs queue Stack: LIFO, one end. Queue: FIFO, two ends."),
]


def deck(texts=None) -> list[Chunk]:
    return [
        Chunk(
            id=uuid.UUID(int=n),
            document_id=DOC,
            idx=n - 1,
            text=(texts or {}).get(n, text),
            page_ref=f"slide:{n}",
            tags=[tag],
        )
        for n, tag, text in SLIDES
    ]


def slides(picked) -> list[int]:
    return [int(c.page_ref.split(":")[1]) for c in picked]


def test_the_context_covers_start_middle_and_end_of_the_chapter():
    picked = slides(pick_context(deck(), k=6))
    assert len(picked) == 6 and picked == sorted(picked)
    assert any(s <= 4 for s in picked)  # start
    assert any(5 <= s <= 8 for s in picked)  # middle
    assert any(s >= 9 for s in picked)  # end
    assert sum(s >= 7 for s in picked) >= 2  # queues, the second half, are really there


def test_two_per_chapter_takes_one_from_each_half():
    first, second = slides(pick_context(deck(), k=2))  # placement: 2 chunks per chapter
    assert first <= 6 < second


def test_the_character_budget_fills_long_chapters_and_holds():
    long = {n: f"slide {n}: " + "detail " * 300 for n in range(1, 13)}  # ~2,100 chars each
    picked = pick_context(deck(long))
    assert sum(len(c.text) for c in picked) <= CONTEXT_CHARS
    got = slides(picked)
    assert got[0] <= 4 and got[-1] >= 9  # still spread over the chapter
    assert len(slides(pick_context(deck()))) == 12  # a short deck fits whole


def test_deterministic_and_a_new_seed_looks_elsewhere_first():
    assert slides(pick_context(deck(), k=6)) == slides(pick_context(deck(), k=6))
    assert slides(pick_context(deck(), k=6, offset=1)) != slides(pick_context(deck(), k=6))


def test_vector_hits_come_first_within_their_part():
    hit = uuid.UUID(int=10)  # slide 10, an end-of-chapter chunk the search ranked first
    assert 10 in slides(pick_context(deck(), k=3, prefer=[hit]))
