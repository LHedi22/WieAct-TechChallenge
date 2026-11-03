"""Phase 3.6/3.7: hostile uploads and stored XSS (mock profile).
    PYTHONIOENCODING=utf-8 C:\\Python311\\python.exe audit/tools/upload_xss_probe.py"""

import io
import json
import sys
import time
import uuid
import zipfile

import fitz  # PyMuPDF (host)

sys.path.insert(0, "audit/tools")
from acl_probe import call, check, multipart, RESULTS  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

R = uuid.uuid4().hex[:5]
XSS = '<img src=x onerror="window.__xss=1">'
CREATOR = f"up_{R}"


def pdf(pages=1, text="Limits: substitute, factor, cancel. " * 20, encrypt=False):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page()
        p.insert_text((50, 72), f"Page {i + 1}. {text}"[:900], fontsize=9)
    buf = io.BytesIO()
    if encrypt:
        d.save(buf, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    else:
        d.save(buf)
    return buf.getvalue()


def docx_bomb():
    """A DOCX whose document.xml inflates to ~200 MB from a few hundred KB."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        body = "<w:p><w:r><w:t>" + "A" * 1000 + "</w:t></w:r></w:p>"
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body * 200_000 + "</w:body></w:document>")
    return buf.getvalue()


s, w = call(CREATOR, "POST", "/api/worlds", {"name": f"Upload lab {R} {XSS}"})
W = w["id"]
s, c = call(CREATOR, "POST", f"/api/worlds/{W}/courses", {"name": f"Course {XSS}", "chapters": [f"Chapter {XSS}", "Big files"]})
CH, CH2 = c["chapters"][0]["id"], c["chapters"][1]["id"]

cases = [
    ("empty.txt", b"", "text/plain", "reject"),
    ("virus.exe", b"MZ" + b"\0" * 500, "application/octet-stream", "reject"),
    ("../../../etc/passwd.txt", b"limits and derivatives " * 40, "text/plain", "accept-safe-name"),
    ("دروس_النهايات.txt", "النهاية عندما يقترب x من a. نحلل البسط والمقام ثم نختصر. ".encode() * 30, "text/plain", "accept"),
    ("corrupt.pdf", b"%PDF-1.4\n" + b"\x00garbage" * 300, "application/pdf", "fail-cleanly"),
    ("protected.pdf", pdf(2, encrypt=True), "application/pdf", "fail-cleanly"),
    ("fake.pdf", b"just text pretending to be a pdf " * 50, "application/pdf", "fail-cleanly"),
    (f"name{XSS}.txt", b"derivatives are slopes " * 40, "text/plain", "accept"),
    ("bomb.docx", docx_bomb(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "fail-cleanly"),
    ("long500.pdf", pdf(500), "application/pdf", "accept"),
]
doc_ids = {}
for name, data, ctype, expect in cases:
    body, ct = multipart(name, data, ctype)
    t0 = time.time()
    s, r = call(CREATOR, "POST", f"/api/chapters/{CH if 'long' not in name else CH2}/documents", raw=body, ctype=ct)
    print(f"{name[:30]:30} {len(data)/1024:9.0f} KB -> {s} {json.dumps(r, ensure_ascii=False)[:160]} ({time.time()-t0:.1f}s)")
    if isinstance(r, dict) and r.get("document"):
        doc_ids[name] = r["document"]["id"]
    if expect == "reject":
        check(f"upload {name} rejected", s, {400, 413, 415, 422})

# 51 MB boundary (UPLOAD_MAX_MB=50)
big = b"x" * (51 * 1024 * 1024)
body, ct = multipart("big.txt", big, "text/plain")
s, r = call(CREATOR, "POST", f"/api/chapters/{CH2}/documents", raw=body, ctype=ct)
check("51 MB upload refused", s, {400, 413}, json.dumps(r)[:120])
# duplicate of the same file in the same chapter
body, ct = multipart("dup.txt", b"duplicate content about limits " * 40, "text/plain")
s1, r1 = call(CREATOR, "POST", f"/api/chapters/{CH}/documents", raw=body, ctype=ct)
s2, r2 = call(CREATOR, "POST", f"/api/chapters/{CH}/documents", raw=body, ctype=ct)
print("duplicate:", s1, json.dumps(r1)[:120], "|", s2, json.dumps(r2)[:160])

# wait for indexing and collect final states
time.sleep(5)
for i in range(60):
    s, idx = call(CREATOR, "GET", f"/api/worlds/{W}/indexing")
    docs = [d for ch in idx.get("chapters", []) for d in ch.get("documents", [])] if isinstance(idx, dict) else []
    if not docs:
        docs = idx.get("documents", []) if isinstance(idx, dict) else []
    pending = [d for d in docs if d.get("status") not in ("ready", "failed", "error")]
    if not pending:
        break
    time.sleep(5)
print("\nfinal indexing states:")
for d in docs:
    print(f"   {d.get('filename','?')[:40]:40} {d.get('status')} {d.get('error') or ''} {d.get('detail') or ''}")
json.dump(idx, open("audit/logs/upload_indexing.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# arena post with XSS + rendering in the browser
s, j = call(CREATOR, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})
olive_ch = next(c for c in j["courses"] if c["name"].startswith("Calculus"))["chapters"][0]["id"]
s, q = call(CREATOR, "POST", "/api/arena/questions", {"chapter_id": olive_ch, "text": f"Why factor first? {XSS} <script>window.__xss=2</script>"})
print("xss arena question:", s, q)

with sync_playwright() as pw:
    from contract_probe import WEB  # noqa: E402
    b = pw.chromium.launch()
    ctx = b.new_context()
    # sign in this dev user through a real password account instead: create one
    nick = f"xv_{R}"
    import urllib.request
    req = urllib.request.Request("http://localhost:8000/api/auth/signup", data=json.dumps({"nickname": nick, "password": "audit-pass-123"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        cookie = r.headers["set-cookie"].split(";")[0]
    n, v = cookie.split("=", 1)
    ctx.add_cookies([{"name": n, "value": v, "domain": "localhost", "path": "/"}])
    page = ctx.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    # join the XSS world by code to view its names
    code = w["join_code"]
    urllib.request.urlopen(urllib.request.Request("http://localhost:8000/api/worlds/join", data=json.dumps({"code": code}).encode(), headers={"Content-Type": "application/json", "Cookie": cookie}, method="POST"))
    for url in (f"/worlds/{W}", f"/worlds/{W}/indexing", f"/worlds/{W}/courses/{c['id']}"):
        page.goto(WEB + url)
        page.wait_for_timeout(2500)
        fired = page.evaluate("window.__xss || 0")
        imgs = page.locator('img[src="x"]').count()
        check(f"stored XSS not executed on {url.split('/')[-1] or 'map'}", 200 if not fired and not imgs else 500, {200}, f"fired={fired} injected_imgs={imgs}")
    page.screenshot(path="audit/artifacts/contract/xss-island.png")
    b.close()
print(f"\n{sum(not r['pass'] for r in RESULTS)} fail / {len(RESULTS)}")
