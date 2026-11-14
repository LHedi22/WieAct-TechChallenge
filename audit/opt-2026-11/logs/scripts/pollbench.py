"""Audit-only: polling load on the API like N open loading screens (GET /api/jobs/{id} every 1.5 s each)
for D seconds; reports request rate and p50/p95/max latency. Runs inside the cc-opt backend container."""
import asyncio, os, statistics, time
import httpx

API = os.environ.get("API", "http://backend:8000")
N, D = int(os.environ.get("N", "30")), float(os.environ.get("D", "30"))


async def main():
    async with httpx.AsyncClient(base_url=API, timeout=30, limits=httpx.Limits(max_connections=200)) as c:
        jobs = []
        for i in range(N):  # one queued job per student (background demo job, mock)
            r = await c.post("/api/dev/demo-jobs", json={"lane": "background", "topic": f"poll {i} {time.time()}"},
                             headers={"X-Dev-User": f"pollb{i}"})
            jobs.append((f"pollb{i}", r.json()["job_id"]))
        lat, t_end = [], time.monotonic() + D

        async def poller(u, j):
            while time.monotonic() < t_end:
                t0 = time.monotonic()
                await c.get(f"/api/jobs/{j}", headers={"X-Dev-User": u})
                lat.append((time.monotonic() - t0) * 1000)
                await asyncio.sleep(max(0, 1.5 - (time.monotonic() - t0)))

        await asyncio.gather(*(poller(u, j) for u, j in jobs))
        for u, j in jobs:  # don't leave 30 demo jobs behind
            await c.post(f"/api/jobs/{j}/cancel", headers={"X-Dev-User": u})
        lat.sort()
        print({"students": N, "seconds": D, "requests": len(lat), "rps": round(len(lat) / D, 1),
               "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(lat[int(.95 * (len(lat) - 1))], 1),
               "max_ms": round(lat[-1], 1)})


asyncio.run(main())
