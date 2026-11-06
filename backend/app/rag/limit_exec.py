"""Run a command under a memory limit (audit F-DOS-1).

    python -m app.rag.limit_exec <mem_mb> <command> [args…]

Sets RLIMIT_DATA in this fresh process, then replaces itself with the command (`os.execv` keeps
the limit). Used instead of `preexec_fn`, which can deadlock between fork and exec when the parent
(the worker) has threads.

RLIMIT_DATA, not RLIMIT_AS: PyMuPDF starts about one thread per CPU, and each thread reserves stack
and a malloc arena of address space. Under RLIMIT_AS those reservations hit the cap and the child
deadlocks in a futex instead of failing (measured during the F-DOS-1 fix). RLIMIT_DATA counts memory
actually written, so a real memory hog still gets MemoryError at once."""

from __future__ import annotations

import os
import shutil
import sys


def main(argv: list[str]) -> None:
    mem_mb, cmd = int(argv[1]), argv[2:]
    if os.name == "posix":
        import resource  # noqa: PLC0415 (POSIX only)

        limit = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
    exe = cmd[0] if os.path.isabs(cmd[0]) else (shutil.which(cmd[0]) or cmd[0])
    os.execv(exe, cmd)


if __name__ == "__main__":
    main(sys.argv)
