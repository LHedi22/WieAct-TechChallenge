"""Kill processes whose cmdline contains argv[1] (for slim images without ps/pkill). Prints the tree."""
import os, signal, sys
pat = sys.argv[1] if len(sys.argv) > 1 else ""
for pid in sorted(int(p) for p in os.listdir("/proc") if p.isdigit()):
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode().strip()
    except Exception:
        continue
    if not cmd: continue
    hit = pat and pat in cmd and "kill_proc" not in cmd
    print(("KILL " if hit else "     ") + f"{pid} {cmd[:110]}")
    if hit:
        os.kill(pid, signal.SIGKILL)
