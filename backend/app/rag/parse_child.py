"""Parse one uploaded file in a child process (audit F-DOS-1).

    python -m app.rag.parse_child <path> <kind>

Started by `rag/indexing.py::_parse` with a memory limit, an idle timeout and an overall deadline,
so a hostile or huge file can be killed without touching the worker's event loop. Writes one JSON
object per line on stdout:
    {"total": n}                                 once, after opening the file
    {"n": i, "page": {"ref","text","ocr"}|null}  after each unit (page, slide, section…)
    {"error": "errors.…"}                        a user-safe failure (exit code 2)
    {"done": true}                               success (exit code 0)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.rag.parsing import ParseError, page_steps
from app.rag.safety import check_archive


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    path, kind = Path(argv[1]), argv[2]
    try:
        check_archive(path, kind)
        total, steps = page_steps(path, kind)
        _emit({"total": total})
        for n, step in enumerate(steps, start=1):
            page = step()
            _emit(
                {
                    "n": n,
                    "page": None
                    if page is None
                    else {"ref": page.ref, "text": page.text, "ocr": page.ocr},
                }
            )
    except ParseError as e:
        _emit({"error": e.key})
        return 2
    _emit({"done": True})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
