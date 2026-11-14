"""Audit-only (not in the repo), host-side, cc-opt stack only (API :18000, project cc-opt).
  python3 chaos.py bomb     F-DOS-1: creator uploads a DOCX bomb; a Tutor start must still finish
  python3 chaos.py worker   kill the worker mid study pack, start it again: job swept + refunded?
  python3 chaos.py db       restart Postgres mid study pack: worker survives, job finishes?
Dev auth via X-Dev-User (development only)."""

import io, json, subprocess, sys, time, urllib.error, urllib.request, uuid, zipfile

API = "http://127.0.0.1:18000"
P = "cc-opt"
R = uuid.uuid4().hex[:5]


def call(user, method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"X-Dev-User": user}
    if data is not None:
        h["Content-Type"] = ctype
    req = urllib.request.Request(API + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read()
            return r.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read()
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t[:200]


def docker(*a):
    return subprocess.run(["docker", *a], capture_output=True, text=True).stdout.strip()


def follow(user, job, timeout=300):
    t0, states = time.time(), []
    while time.time() - t0 < timeout:
        s, j = call(user, "GET", f"/api/jobs/{job}")
        snap = (j.get("status"), j.get("stage"), j.get("waiting_reason"), j.get("error")) if s == 200 else (f"http {s}",)
        if not states or states[-1][1:] != snap:
            states.append((round(time.time() - t0),) + snap)
        if s == 200 and j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(2)
    return states, round(time.time() - t0)


def coins(u):
    return call(u, "GET", "/api/wallet")[1].get("coins")


def student(prefix):
    u = f"{prefix}{R}"
    s, w = call(u, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})
    calc = next(c for c in w["courses"] if c["name"].startswith("Calculus"))
    return u, calc["chapters"][0]["id"], w


def docx_bomb():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        para = "<w:p><w:r><w:t>" + "limit " * 50 + "</w:t></w:r></w:p>"
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + para * 600000 + "</w:body></w:document>")
    return buf.getvalue()


def multipart(name, content):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def bomb():
    owner = f"bombowner{R}"
    s, w = call(owner, "POST", "/api/worlds", {"name": f"Bomb {R}"})
    s2, c = call(owner, "POST", f"/api/worlds/{w['id']}/courses", {"name": "Bomb course", "chapters": ["Ch1"]})
    print("create world", s, s2, str(c)[:200])
    if s2 not in (200, 201):
        return {"blocked": f"create course {s2}"}
    ch = c["chapters"][0]["id"]
    data = docx_bomb()
    body, ct = multipart("bomb.docx", data)
    t0 = time.time()
    s, d = call(owner, "POST", f"/api/chapters/{ch}/documents", raw=body, ctype=ct)
    print("upload", s, len(data), "bytes", str(d)[:200])
    u, cch, _ = student("bombvictim")
    time.sleep(3)
    s2, t = call(u, "POST", "/api/tutor/start", {"chapter_id": cch, "level": "beginner"})
    states, secs = follow(u, t["job_id"], 240) if s2 == 200 and t.get("job_id") else ([], 0)
    doc_status = None
    for _ in range(60):
        s3, docs = call(owner, "GET", f"/api/worlds/{w['id']}/indexing")
        doc_status = docs
        if '"ready"' in json.dumps(docs) or '"failed"' in json.dumps(docs):
            break
        time.sleep(3)
    return {"bomb_bytes": len(data), "upload_http": s, "tutor_states": states, "tutor_secs": secs,
            "doc": str(doc_status)[:400], "since_upload_s": round(time.time() - t0)}


def pack_then(action):
    u, ch, _ = student(f"chaos{action}")
    call(u, "POST", "/api/wallet/demo-purchase", {"product": "coin_pack"})
    c0 = coins(u)
    s, g = call(u, "POST", f"/api/studio/{ch}/generate", {"level": "beginner", "pay": "me"})
    print("generate", s, g)
    job = g["job_id"]
    for _ in range(60):  # wait until running
        j = call(u, "GET", f"/api/jobs/{job}")[1]
        if j["status"] == "running":
            break
        time.sleep(0.5)
    t_hit = time.time()
    if action == "worker":
        print(docker("kill", f"{P}-worker-1"))
        time.sleep(5)
        print(docker("start", f"{P}-worker-1"))
    else:
        print(docker("restart", f"{P}-db-1"))
    states, secs = follow(u, job, 300)
    worker_state = docker("inspect", "-f", "{{.State.Status}} restarts={{.RestartCount}}", f"{P}-worker-1")
    return {"action": action, "job_cost": g.get("cost"), "states": states, "secs_after_fault": round(time.time() - t_hit),
            "coins_before_start": c0, "coins_after": coins(u), "worker": worker_state}


if __name__ == "__main__":
    which = sys.argv[1]
    res = {"bomb": bomb, "worker": lambda: pack_then("worker"), "db": lambda: pack_then("db")}[which]()
    print(json.dumps(res, indent=1, default=str))
