"""Do building pages survive a reload / direct link? Enter each building via the island dialog,
note the URL, reload, and check the main content is still there."""
import sys, uuid, json
sys.path.insert(0, "audit/tools")
from contract_probe import student, WEB  # noqa: E402  (module import runs nothing heavy? see guard)
from playwright.sync_api import sync_playwright

nick, cookie, w = student("en")
course = next(c for c in w["courses"] if c["name"].startswith("Calculus"))
C = f"/worlds/{w['id']}/courses/{course['id']}"
rows = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    n, v = cookie.split("=", 1)
    ctx.add_cookies([{"name": n, "value": v, "domain": "localhost", "path": "/"}])
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    for key in ("quiz_hall", "socratic_tutor", "study_studio", "audio_studio", "teachback_arena"):
        page.goto(WEB + C)
        page.locator(f'[data-building="{key}"]').click()
        page.get_by_role("dialog").get_by_role("button", name="Enter", exact=True).click()
        page.wait_for_timeout(4000)
        url = page.url
        main_before = len(page.locator("main").inner_text()) if page.locator("main").count() else len(page.locator("body").inner_text())
        page.reload()
        page.wait_for_timeout(4000)
        main_after = len(page.locator("main").inner_text()) if page.locator("main").count() else len(page.locator("body").inner_text())
        page.screenshot(path=f"audit/artifacts/contract/reload-{key}.png")
        rows.append({"building": key, "url": url.replace(WEB, ""), "chars_before": main_before, "chars_after_reload": main_after})
        print(rows[-1])
    b.close()
print("console errors:", errs[:5])
json.dump(rows, open("audit/logs/reload_probe.json", "w"), indent=1)
