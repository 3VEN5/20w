"""End-to-end smoke test. Starts its OWN throwaway demo, never resets an existing instance."""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

here = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument("--shots", type=Path)
p.add_argument("--chrome", default=None)
opts = p.parse_args()
if opts.shots: opts.shots.mkdir(parents=True, exist_ok=True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
base = f"http://127.0.0.1:{port}"
proc = subprocess.Popen([sys.executable,str(here/"run.py"),"--demo","--port",str(port)], stdout=subprocess.DEVNULL)
try:
    for _ in range(100):
        try:
            with urlopen(base+"/login", timeout=1): break
        except OSError: time.sleep(.1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=opts.chrome)
        ctx = browser.new_context(viewport={"width":1200,"height":900}, locale="zh-CN")
        page = ctx.new_page()
        errors=[]
        page.on("pageerror",lambda e: errors.append(str(e)))
        def click(action): page.locator('[data-act="'+action+'"]').first.click(timeout=6000)
        def state(): return ctx.request.get(base+"/api/state").json()
        def shot(name):
            if opts.shots: page.screenshot(path=str(opts.shots/(name+".png")), animations="disabled")
        page.goto(base)
        page.get_by_text("进入顾问工作台").click()
        expect(page.locator('[data-tab="today"]')).to_have_attribute("aria-current","page")
        click("demoMail");click("organize")
        expect(page.locator('[data-act="confirmcap"]')).to_be_visible()
        assert not state()["items"]
        shot("01-mail")
        click("confirmcap")
        expect(page.get_by_text("核对并记录学生承诺")).to_be_visible()
        page.locator('[data-tab="today"]').click()
        before=state()
        click("copy")
        assert state()["logs"]==before["logs"] and not state()["items"][0]["agreed"]
        click("confirmsent")
        expect(page.locator('[data-act="confirmsent"]')).to_have_count(0)
        assert state()["items"][0]["agreed"]
        click("openWorkflow");click("promise")
        expect(page.get_by_text("去移交给陈老师")).to_be_visible()
        i=state()["items"][0]
        assert not i["done"] and (i["follow"]["promised_on"],i["follow"]["review_on"],i["due"])==("2026-11-16","2026-11-17","2026-11-20")
        page.evaluate("window.scrollTo(0,0)");shot("02-promise")
        old=browser.new_context(storage_state=ctx.storage_state())
        click("handoff");click("tomorrow")
        expect(page.locator("#whome")).to_have_text("陈老师")
        expect(page.locator(".briefing")).to_contain_text("复查 11月17日")
        assert state()["me"]["id"]!=old.request.get(base+"/api/state").json()["me"]["id"]
        assert old.request.post(base+"/api/act",headers={"X-App":"1"},data={"op":"review","item":i["id"],"review":"2026-11-18"}).status==403
        expect(page.locator('[data-act="review"]')).to_be_visible()
        shot("03-handoff")
        page.set_viewport_size({"width":390,"height":844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        shot("04-mobile")
        page.set_viewport_size({"width":1200,"height":900})
        click("review")
        expect(page.locator('[data-act="review"]')).to_have_count(0)
        expect(page.locator(".briefing")).to_contain_text("复查 11月18日")
        assert not state()["items"][0]["done"]
        page.reload()
        expect(page.locator(".briefing")).to_contain_text("复查 11月18日")
        click("resetDemo")
        expect(page.locator("#whome")).to_have_text("王老师")
        st=state()
        assert st["today"]=="2026-11-16" and not any(st[k] for k in ("items","logs","outcomes"))
        # Same numeric/string ID path used by the supervisor selector, with only one overdue task.
        resp=ctx.request.post(base+"/api/act",headers={"X-App":"1"},data={"op":"additems","student":1,"items":[{"what":"逾期回归","owner":"机构","due":"2026-11-15"}]})
        assert resp.ok
        page.reload()
        expect(page.locator("main")).to_contain_text("逾期回归")
        page.locator('[data-tab="overview"]').click()
        expect(page.locator("main")).to_contain_text("今天要跟进 1 件事")
        # Fixture only elevates the displayed role; no supervisor credentials or DB mutations.
        page.evaluate("D.me.role='owner'; render()")
        page.locator('[data-viewas="1"]').click()
        expect(page.locator('[data-viewas="1"]')).to_have_attribute("aria-pressed","true")
        expect(page.locator("main")).to_contain_text("林同学")
        assert not errors, errors
        browser.close()
        print("PASS: mail > confirmation > copy/send > promise > real reassignment > next-day review > live summary > reset; overdue and advisor filter")
finally:
    proc.terminate();proc.wait(timeout=15)
