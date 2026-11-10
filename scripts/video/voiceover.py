"""Voiceover lines → docs/report/video/vo/NN.mp3 with edge-tts (skipped if voiceover.wav exists)."""
import asyncio
import subprocess
from pathlib import Path

import edge_tts

OUT = Path(__file__).resolve().parents[2] / "docs/report/video/vo"
VOICE = "en-US-AndrewNeural"
LINES = [
    "What if your courses became a world you explore with your class?",
    "Pick a nickname, take a one-minute style test, build your explorer.",
    "Upload your course, share the code, and your whole class lands on the same islands.",
    "Every course is an island. Daily challenges and streaks keep you coming back.",
    "Each island has five buildings, all grounded in your own material.",
    "In the Quiz Hall, a wrong answer earns a hint, not the answer. Every mistake becomes a weak spot and a next step.",
    "The Socratic Tutor never hands you the solution. Stuck twice? A stronger model steps in and asks better questions.",
    "Notes and flashcards are generated once, then free for the whole class, on any phone, in any language.",
    "In Teach-Back, you learn by explaining. AI scores your answers, and the class's common mistakes become anonymous tips.",
    "Underneath: smart model routing, caching, queueing, offline mode, and no real names, ever.",
    "Learning World. Learn it, explain it, own it.",
]


async def main(rate: str = "+0%"):
    OUT.mkdir(parents=True, exist_ok=True)
    for i, line in enumerate(LINES, 1):
        f = OUT / f"{i:02d}.mp3"
        for n in range(8):  # the free service drops requests now and then
            if f.exists() and f.stat().st_size > 0:
                break
            try:
                await edge_tts.Communicate(line, VOICE, rate=rate).save(str(f))
            except edge_tts.exceptions.NoAudioReceived:
                f.unlink(missing_ok=True)
                await asyncio.sleep(3 + 3 * n)
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True).stdout.strip()
        print(f"{i:02d} {float(d):5.2f}s  {line}")
    (OUT / "lines.txt").write_text("\n".join(LINES), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
