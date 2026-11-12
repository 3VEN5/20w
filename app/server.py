"""申请进度助手 · 试用版后台。

启动：  uvicorn server:app --host 127.0.0.1 --port 8000
建机构： python manage.py new-agency
所有操作都走 POST /api/act（字段 op 是操作名），后台执行后写留痕，再把最新数据整份返回给页面。
"""
import csv, io, json, os, re, secrets, time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

import ai, db

HERE = Path(__file__).parent
STATIC = HERE / "static"
DEADLINES_JS = Path(os.environ.get("DEADLINES_JS", HERE.parent / "爬虫" / "data" / "deadlines_web.js"))
SECURE_COOKIE = os.environ.get("SECURE_COOKIE", "1") == "1"   # 本地调试用 http 时设成 0
SESSION_DAYS = 30
OWNERS = {"学生", "家长", "学校", "机构"}
FAM = {"学生", "家长"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
db.init()


# ------------------------------------------------------------------ 工具
def bad(msg, code=400):
    raise HTTPException(code, msg)


def txt(v, name, maxlen=200, required=True):
    v = str(v or "").strip()
    if required and not v:
        bad(f"{name}不能为空")
    if len(v) > maxlen:
        bad(f"{name}太长了（最多 {maxlen} 字）")
    return v


def date(v, name="日期"):
    v = str(v or "").strip()
    if not DATE_RE.match(v):
        bad(f"{name}格式不对")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        bad(f"{name}不存在")
    return v


def md(d):
    return f"{int(d[5:7])}月{int(d[8:10])}日"


# ------------------------------------------------------------------ 登录
_fails = {}   # 登录失败次数，防止猜密码


def current_user(request: Request):
    tok = request.cookies.get("sid")
    if not tok:
        bad("请先登录", 401)
    with db.connect() as con:
        u = con.execute("""SELECT u.*, a.name AS agency FROM session s JOIN user u ON u.id = s.user_id JOIN agency a ON a.id = u.agency_id
                           WHERE s.token = ? AND s.expires > ? AND u.active = 1""", (tok, db.stamp())).fetchone()
    if not u:
        bad("登录已过期，请重新登录", 401)
    return dict(u)


@app.middleware("http")
async def guard(request: Request, call_next):
    # 写操作必须带这个请求头：别的网站伪造的表单提交带不上它
    if request.method == "POST" and request.url.path.startswith("/api/") and request.headers.get("x-app") != "1":
        return Response("forbidden", status_code=403)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.post("/api/login")
async def login(request: Request, response: Response):
    body = await request.json()
    lg, pw = str(body.get("login", "")).strip(), str(body.get("password", ""))
    ip = request.client.host if request.client else "?"
    recent = [t for t in _fails.get(ip, []) if t > time.time() - 900]
    if len(recent) >= 10:
        bad("尝试次数太多，请 15 分钟后再试", 429)
    with db.connect() as con:
        u = con.execute("SELECT * FROM user WHERE login = ? AND active = 1", (lg,)).fetchone()
        if not u or not db.check_pw(pw, u["pw"]):
            _fails[ip] = recent + [time.time()]
            bad("账号或密码不对", 401)
        tok = secrets.token_urlsafe(32)
        exp = (db.now() + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M")
        con.execute("DELETE FROM session WHERE expires < ?", (db.stamp(),))
        con.execute("INSERT INTO session VALUES (?,?,?)", (tok, u["id"], exp))
    response.set_cookie("sid", tok, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=SECURE_COOKIE)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    with db.connect() as con:
        con.execute("DELETE FROM session WHERE token = ?", (request.cookies.get("sid", ""),))
    response.delete_cookie("sid")
    return {"ok": True}


# ------------------------------------------------------------------ 页面和静态文件
@app.get("/")
def index(request: Request):
    try:
        current_user(request)
    except HTTPException:
        return RedirectResponse("/login")
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/config.js")
def config_js():
    return FileResponse(STATIC / "config.js", media_type="text/javascript")


@app.get("/deadlines.js")
def deadlines_js(u=Depends(current_user)):
    if not DEADLINES_JS.exists():
        return Response("window.DEADLINES = {schools:{}, info:{}};", media_type="text/javascript")
    return FileResponse(DEADLINES_JS, media_type="text/javascript")


# ------------------------------------------------------------------ 读数据
def state(u):
    aid, today = u["agency_id"], db.today()
    with db.connect() as con:
        users = [dict(r) for r in con.execute("SELECT id, name, login, role, active FROM user WHERE agency_id = ? ORDER BY id", (aid,))]
        uname = {x["id"]: x["name"] for x in users}
        studs = [dict(r) for r in con.execute("SELECT * FROM student WHERE agency_id = ? AND archived = 0 ORDER BY id", (aid,))]
        sname = {s["id"]: s["name"] for s in studs}
        items = [dict(r) for r in con.execute("SELECT * FROM item WHERE agency_id = ? AND deleted = 0 ORDER BY due, id", (aid,))]
        chases = {}
        for r in con.execute("SELECT c.item_id, c.date FROM chase c JOIN item i ON i.id = c.item_id WHERE i.agency_id = ? ORDER BY c.date, c.id", (aid,)):
            chases.setdefault(r["item_id"], []).append(r["date"])
        logs = [dict(r) for r in con.execute("SELECT * FROM log WHERE agency_id = ? ORDER BY id DESC LIMIT 3000", (aid,))]
        mem = {}
        for r in con.execute("SELECT * FROM custom_school WHERE agency_id = ? ORDER BY school", (aid,)):
            m = mem.setdefault(r["school"], {"d": {}, "by": r["by"], "on": r["on_date"], "src": r["src"], "region": r["region"]})
            m["d"][r["round"]] = r["date"]
    cons_of = {s["id"]: uname.get(s["consultant_id"], "") for s in studs}
    undo_after = (db.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    return {
        "me": {"id": u["id"], "name": u["name"], "role": u["role"]}, "agency": u["agency"], "today": today, "ai": ai.enabled(), "aiImages": ai.enabled() and ai.images_enabled(),
        "users": [{k: x[k] for k in ("id", "name", "role", "active")} | ({"login": x["login"]} if u["role"] == "owner" else {}) for x in users],
        "students": [{"id": s["id"], "name": s["name"], "parent": s["parent"], "consultant": cons_of[s["id"]], "consultant_id": s["consultant_id"]} for s in studs],
        "items": [{"id": i["id"], "student": sname[i["student_id"]], "what": i["what"], "owner": i["owner"], "due": i["due"], "created": i["created"],
                   "agreed": i["agreed"], "replied": i["replied"], "replyText": i["reply_text"], "done": i["done"], "school": i["school"],
                   "round": i["round"] or "", "sdl": i["sdl"] or "", "region": i["region"] or "", "rolling": bool(i["rolling"]),
                   "chases": chases.get(i["id"], [])} for i in items if i["student_id"] in sname],
        "logs": [{"id": l["id"], "date": l["at"][:10], "time": l["at"][11:], "who": l["who"], "src": l["src"], "act": l["act"],
                  "student": sname.get(l["student_id"], ""), "consultant": cons_of.get(l["student_id"], ""), "undone": bool(l["undone"]),
                  "canUndo": bool(l["undo"]) and not l["undone"] and l["user_id"] == u["id"] and l["at"] >= undo_after} for l in logs],
        "memory": mem,
    }


@app.get("/api/state")
def get_state(u=Depends(current_user)):
    return state(u)


# ------------------------------------------------------------------ 写操作
class Ctx:
    def __init__(self, con, u):
        self.con, self.u, self.aid, self.today = con, u, u["agency_id"], db.today()

    def student(self, sid):
        s = self.con.execute("SELECT * FROM student WHERE id = ? AND agency_id = ? AND archived = 0", (sid, self.aid)).fetchone()
        return s or bad("找不到这个学生")

    def item(self, iid):
        i = self.con.execute("SELECT * FROM item WHERE id = ? AND agency_id = ? AND deleted = 0", (iid, self.aid)).fetchone()
        return i or bad("找不到这个事项")

    def log(self, student_id, src, act, who=None, undo=None):
        self.con.execute("INSERT INTO log (agency_id, student_id, at, user_id, who, src, act, undo) VALUES (?,?,?,?,?,?,?,?)",
                         (self.aid, student_id, db.stamp(), self.u["id"], who or self.u["name"], src, act, json.dumps(undo) if undo else None))

    def add_item(self, sid, what, owner, due, school=None, rnd=None, sdl=None, region=None, rolling=False):
        what, due = txt(what, "事项", 120), date(due, "截止日")
        if owner not in OWNERS:
            bad("负责人只能是学生、家长、学校或机构")
        cur = self.con.execute("INSERT INTO item (agency_id, student_id, what, owner, due, created, school, round, sdl, region, rolling) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (self.aid, sid, what, owner, due, self.today, school, rnd, sdl, region, int(bool(rolling))))
        return cur.lastrowid


def owner_only(c):
    if c.u["role"] != "owner":
        bad("只有老板账号能做这个操作", 403)


def a_chased(c, b):
    it = c.item(b.get("item"))
    cid = c.con.execute("INSERT INTO chase (item_id, date) VALUES (?,?)", (it["id"], c.today)).lastrowid
    n = c.con.execute("SELECT COUNT(*) FROM chase WHERE item_id = ?", (it["id"],)).fetchone()[0]
    school = it["owner"] == "学校"
    c.log(it["student_id"], "跟进" if school else "提醒", f"{'跟进学校' if school else '已发提醒'}（第 {n} 次）：{it['what']}", undo={"t": "chase", "id": cid})


def a_done(c, b):
    it = c.item(b.get("item"))
    if it["done"]:
        bad("这件事已经是完成状态")
    c.con.execute("UPDATE item SET done = ? WHERE id = ?", (c.today, it["id"]))
    c.log(it["student_id"], "完成", f"完成「{it['what']}」（{c.u['name']}记录）", who=c.u["name"] if it["owner"] == "机构" else it["owner"], undo={"t": "done", "id": it["id"]})


def a_agreed(c, b):
    s = c.student(b.get("student"))
    rows = c.con.execute("SELECT id, what FROM item WHERE student_id = ? AND deleted = 0 AND done IS NULL AND agreed IS NULL AND owner IN ('学生','家长')", (s["id"],)).fetchall()
    if not rows:
        bad("没有需要发约定的事项")
    c.con.executemany("UPDATE item SET agreed = ? WHERE id = ?", [(c.today, r["id"]) for r in rows])
    c.log(s["id"], "约定", "已发约定给家长：" + "、".join(f"「{r['what']}」" for r in rows), undo={"t": "agreed", "ids": [r["id"] for r in rows]})


def a_replied(c, b):
    it = c.item(b.get("item"))
    d = date(b.get("date") or c.today)
    t = txt(b.get("text"), "家长原话", 300, required=False)
    c.con.execute("UPDATE item SET replied = ?, reply_text = ? WHERE id = ?", (d, t or None, it["id"]))
    parent = c.student(it["student_id"])["parent"]
    c.log(it["student_id"], "微信回复", f"家长 {md(d)} 回复{'：“' + t + '”' if t else ''}（{c.u['name']}记录）", who=parent,
          undo={"t": "replied", "id": it["id"], "old": [it["replied"], it["reply_text"]]})


def a_parentnote(c, b):
    s = c.student(b.get("student"))
    t = txt(b.get("text"), "家长原话", 300)
    c.log(s["id"], "微信回复", f"家长回复：“{t}”（{c.u['name']}记录，不对应具体事项）", who=s["parent"], undo={"t": "none"})


def a_sent(c, b):
    s = c.student(b.get("student"))
    c.log(s["id"], "反馈家长", f"已发{txt(b.get('what'), '内容', 20)}给家长", undo={"t": "none"})


def a_additems(c, b):
    s = c.student(b.get("student"))
    items = b.get("items") or bad("没有要写入的事项")
    ids = [c.add_item(s["id"], x.get("what"), x.get("owner"), x.get("due")) for x in items[:50]]
    label = txt(b.get("from") or "手动添加", "来源", 30)
    quotes = [x.get("quote") for x in items if x.get("quote")]
    c.log(s["id"], "录入", f"{label}，确认 {len(ids)} 条事项：" + "；".join(f"{x['what']}（{x['owner']}，{md(x['due'])}）" for x in items[:50])
          + (f"。原话：" + " / ".join(f"“{q[:80]}”" for q in quotes) if quotes else ""), undo={"t": "items", "ids": ids})


def a_found(c, b):
    s = c.student(b.get("student"))
    for f in (b.get("found") or [])[:20]:
        if f.get("kind") == "note":                            # 家长的回复对不上具体事项，只留痕
            t = txt(f.get("text") or f.get("quote"), "家长原话", 300)
            c.log(s["id"], "微信回复", f"家长回复：“{t}”（从粘贴的内容识别，{c.u['name']}确认，不对应具体事项）", who=s["parent"], undo={"t": "none"})
            continue
        it = c.item(f.get("item"))
        if it["student_id"] != s["id"]:
            bad("事项不属于这个学生")
        q = txt(f.get("quote"), "原话", 300, required=False)
        if f.get("kind") == "replied":
            d = date(f.get("date") or c.today)
            c.con.execute("UPDATE item SET replied = ?, reply_text = ? WHERE id = ?", (d, txt(f.get("text"), "原话", 300, required=False) or None, it["id"]))
            c.log(s["id"], "微信回复", f"家长 {md(d)} 回复：“{q}”（从粘贴的聊天识别，{c.u['name']}确认）", who=s["parent"],
                  undo={"t": "replied", "id": it["id"], "old": [it["replied"], it["reply_text"]]})
        elif f.get("kind") == "done" and not it["done"]:
            c.con.execute("UPDATE item SET done = ? WHERE id = ?", (c.today, it["id"]))
            c.log(s["id"], "完成", f"完成「{it['what']}」：“{q}”（从粘贴的聊天识别，{c.u['name']}确认）", who=it["owner"], undo={"t": "done", "id": it["id"]})


def a_addschool(c, b):
    s = c.student(b.get("student"))
    school, rnd = txt(b.get("school"), "学校", 100), txt(b.get("round"), "轮次", 40)
    deadline = date(b.get("deadline"), "学校截止日")
    db_deadline = b.get("db_deadline") or None
    source = txt(b.get("source"), "来源", 200, required=False)
    reason = txt(b.get("reason"), "改动原因", 200, required=False)
    steps = b.get("steps") or bad("没有要写入的事项")
    region = txt(b.get("region"), "地区", 20, required=False) or "其他"
    rolling = rnd == "滚动录取" or bool(b.get("rolling"))
    ids = [c.add_item(s["id"], x.get("what"), x.get("owner"), x.get("due"), school, rnd, deadline, region, rolling) for x in steps[:20]]
    if db_deadline and db_deadline != deadline:
        dl = f"日期库是 {db_deadline}，{c.u['name']}改为 {deadline}" + (f"（{reason}）" if reason else "")
    elif db_deadline:
        dl = f"截止日 {deadline}（日期库，{c.u['name']}已核对）"
    elif rnd == "滚动录取" or b.get("rolling"):
        dl = f"滚动录取，计划递交日 {deadline} 由{c.u['name']}和学生商定"
    else:
        dl = f"截止日 {deadline}，{c.u['name']}自填"
    edited = [x for x in steps if x.get("edited")]
    c.log(s["id"], "加学校", f"加入 {school}（{region}，{rnd}），{dl}{'，来源：' + source if source else ''}；写入 {len(ids)} 条事项："
          + "；".join(f"{x['what']} {md(x['due'])}" for x in steps[:20]) + (f"。其中 {len(edited)} 条的截止日由顾问改过" if edited else ""),
          undo={"t": "items", "ids": ids})
    if b.get("remember") and not db_deadline and not rolling:
        c.con.execute("INSERT OR REPLACE INTO custom_school (agency_id, school, round, date, by, on_date, src, region) VALUES (?,?,?,?,?,?,?,?)",
                      (c.aid, school, rnd, deadline, c.u["name"], c.today, source, region))


def a_editdue(c, b):
    it = c.item(b.get("item"))
    new = date(b.get("due"), "新截止日")
    if new == it["due"]:
        bad("日期没有变化")
    reason = txt(b.get("reason"), "改动原因", 200, required=False)
    c.con.execute("UPDATE item SET due = ? WHERE id = ?", (new, it["id"]))
    c.log(it["student_id"], "改截止日", f"「{it['what']}」截止日从 {it['due']} 改为 {new}" + (f"（{reason}）" if reason else ""), undo={"t": "due", "id": it["id"], "old": it["due"]})


def a_edititem(c, b):
    it = c.item(b.get("item"))
    what, owner, due = txt(b.get("what"), "事项", 120), b.get("owner"), date(b.get("due"), "截止日")
    if owner not in OWNERS:
        bad("负责人只能是学生、家长、学校或机构")
    ch = []
    if what != it["what"]:
        ch.append(f"名称改为「{what}」")
    if owner != it["owner"]:
        ch.append(f"负责人从{it['owner']}改为{owner}")
    if due != it["due"]:
        ch.append(f"截止日从 {it['due']} 改为 {due}")
    if not ch:
        bad("没有改动")
    reason = txt(b.get("reason"), "改动原因", 200, required=False)
    c.con.execute("UPDATE item SET what = ?, owner = ?, due = ? WHERE id = ?", (what, owner, due, it["id"]))
    c.log(it["student_id"], "修改事项", f"「{it['what']}」{'，'.join(ch)}" + (f"（{reason}）" if reason else ""),
          undo={"t": "edit", "id": it["id"], "old": {"what": it["what"], "owner": it["owner"], "due": it["due"]}})


def a_removeschool(c, b):
    s = c.student(b.get("student"))
    school = txt(b.get("school"), "学校", 100)
    reason = txt(b.get("reason"), "移除原因", 200, required=False)
    ids = [r["id"] for r in c.con.execute("SELECT id FROM item WHERE student_id = ? AND agency_id = ? AND school = ? AND deleted = 0", (s["id"], c.aid, school))]
    if not ids:
        bad("这个学生没有这所学校的事项")
    c.con.executemany("UPDATE item SET deleted = 1 WHERE id = ?", [(i,) for i in ids])
    c.log(s["id"], "移除学校", f"移除 {school}，连同 {len(ids)} 条事项" + (f"，原因：{reason}" if reason else ""), undo={"t": "restore", "ids": ids})


def a_deleteitem(c, b):
    it = c.item(b.get("item"))
    reason = txt(b.get("reason"), "删除原因", 200, required=False)
    c.con.execute("UPDATE item SET deleted = 1 WHERE id = ?", (it["id"],))
    c.log(it["student_id"], "删除事项", f"删除「{it['what']}」（原截止 {it['due']}）" + (f"，原因：{reason}" if reason else ""), undo={"t": "undelete", "id": it["id"]})


def a_undo(c, b):
    l = c.con.execute("SELECT * FROM log WHERE id = ? AND agency_id = ?", (b.get("log"), c.aid)).fetchone()
    if not l or not l["undo"] or l["undone"] or l["user_id"] != c.u["id"]:
        bad("这条记录不能撤销")
    if l["at"] < (db.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"):
        bad("超过 30 分钟的操作不能撤销，请直接修改")
    u = json.loads(l["undo"])
    t = u["t"]
    if t == "chase":
        c.con.execute("DELETE FROM chase WHERE id = ?", (u["id"],))
    elif t == "done":
        c.con.execute("UPDATE item SET done = NULL WHERE id = ? AND agency_id = ?", (u["id"], c.aid))
    elif t == "agreed":
        c.con.executemany("UPDATE item SET agreed = NULL WHERE id = ? AND agency_id = ?", [(i, c.aid) for i in u["ids"]])
    elif t == "replied":
        c.con.execute("UPDATE item SET replied = ?, reply_text = ? WHERE id = ? AND agency_id = ?", (*u["old"], u["id"], c.aid))
    elif t == "items":
        c.con.executemany("UPDATE item SET deleted = 1 WHERE id = ? AND agency_id = ?", [(i, c.aid) for i in u["ids"]])
    elif t == "due":
        c.con.execute("UPDATE item SET due = ? WHERE id = ? AND agency_id = ?", (u["old"], u["id"], c.aid))
    elif t == "undelete":
        c.con.execute("UPDATE item SET deleted = 0 WHERE id = ? AND agency_id = ?", (u["id"], c.aid))
    elif t == "edit":
        o = u["old"]
        c.con.execute("UPDATE item SET what = ?, owner = ?, due = ? WHERE id = ? AND agency_id = ?", (o["what"], o["owner"], o["due"], u["id"], c.aid))
    elif t == "restore":
        c.con.executemany("UPDATE item SET deleted = 0 WHERE id = ? AND agency_id = ?", [(i, c.aid) for i in u["ids"]])
    # 留痕不删，只标成"已撤销"，老板仍然看得到
    c.con.execute("UPDATE log SET undone = 1 WHERE id = ?", (l["id"],))


def a_addstudent(c, b):
    name, parent = txt(b.get("name"), "学生称呼", 30), txt(b.get("parent"), "家长称呼", 30)
    cid = int(b.get("consultant") or c.u["id"]) if c.u["role"] == "owner" else c.u["id"]
    if not c.con.execute("SELECT 1 FROM user WHERE id = ? AND agency_id = ? AND active = 1", (cid, c.aid)).fetchone():
        bad("找不到这个顾问")
    if c.con.execute("SELECT 1 FROM student WHERE agency_id = ? AND name = ?", (c.aid, name)).fetchone():
        bad("已经有同名学生了，可以加个区分，比如“张同学 A”")
    sid = c.con.execute("INSERT INTO student (agency_id, name, parent, consultant_id, created) VALUES (?,?,?,?,?)",
                        (c.aid, name, parent, cid, c.today)).lastrowid
    cname = c.con.execute("SELECT name FROM user WHERE id = ?", (cid,)).fetchone()[0]
    c.log(sid, "学生", f"新建学生 {name}，家长称呼 {parent}，负责顾问 {cname}")


def a_archivestudent(c, b):
    s = c.student(b.get("student"))
    c.con.execute("UPDATE student SET archived = 1 WHERE id = ?", (s["id"],))
    c.log(s["id"], "学生", f"{s['name']} 已结案（不再显示，记录保留）")


def a_forget(c, b):
    school = txt(b.get("school"), "学校", 100)
    c.con.execute("DELETE FROM custom_school WHERE agency_id = ? AND school = ?", (c.aid, school))
    c.log(None, "学校记忆", f"删除自填学校 {school} 的日期")


def a_adduser(c, b):
    owner_only(c)
    name, lg, pw = txt(b.get("name"), "姓名", 20), txt(b.get("login"), "登录名", 40), str(b.get("password") or "")
    if len(pw) < 8:
        bad("密码至少 8 位")
    if c.con.execute("SELECT 1 FROM user WHERE login = ?", (lg,)).fetchone():
        bad("这个登录名已被使用")
    role = "owner" if b.get("role") == "owner" else "consultant"
    c.con.execute("INSERT INTO user (agency_id, name, login, pw, role) VALUES (?,?,?,?,?)", (c.aid, name, lg, db.hash_pw(pw), role))
    c.log(None, "账号", f"新建{'老板' if role == 'owner' else '顾问'}账号：{name}")


def a_setpw(c, b):
    target = int(b.get("user") or c.u["id"])
    if target != c.u["id"]:
        owner_only(c)
    pw = str(b.get("password") or "")
    if len(pw) < 8:
        bad("密码至少 8 位")
    r = c.con.execute("UPDATE user SET pw = ? WHERE id = ? AND agency_id = ?", (db.hash_pw(pw), target, c.aid))
    if not r.rowcount:
        bad("找不到这个账号")
    c.con.execute("DELETE FROM session WHERE user_id = ? AND token != ?", (target, c.u.get("_tok", "")))
    c.log(None, "账号", "修改了密码" if target == c.u["id"] else "重置了一个顾问的密码")


def a_deactivate(c, b):
    owner_only(c)
    target = int(b.get("user") or 0)
    if target == c.u["id"]:
        bad("不能停用自己的账号")
    c.con.execute("UPDATE user SET active = 0 WHERE id = ? AND agency_id = ?", (target, c.aid))
    c.con.execute("DELETE FROM session WHERE user_id = ?", (target,))
    c.log(None, "账号", "停用了一个账号")


ACTIONS = {k[2:]: v for k, v in globals().items() if k.startswith("a_")}


@app.post("/api/act")
async def act(request: Request, u=Depends(current_user)):
    b = await request.json()
    fn = ACTIONS.get(b.get("op")) or bad("未知操作")
    u["_tok"] = request.cookies.get("sid", "")
    with db.connect() as con:
        fn(Ctx(con, u), b)
    return state(u)


# ------------------------------------------------------------------ AI 整理
@app.post("/api/extract")
async def extract(request: Request, u=Depends(current_user)):
    b = await request.json()
    images = b.get("images") or []
    if not isinstance(images, list) or len(images) > 4:
        bad("一次最多 4 张图片")
    for im in images:
        if not isinstance(im, str) or not re.match(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$", im) or len(im) > 4_000_000:
            bad("图片格式不对，请换一张（jpg、png）")
    text = txt(b.get("text"), "内容", 6000, required=not images)
    with db.connect() as con:
        s = Ctx(con, u).student(b.get("student"))
        open_items = [dict(r) for r in con.execute("SELECT id, what, owner, due FROM item WHERE student_id = ? AND deleted = 0 AND done IS NULL", (s["id"],))]
    if not ai.enabled():
        bad("还没有配置 AI 服务，请用手动添加")
    if images and not ai.images_enabled():
        bad("还没有开通图片识别，请把文字贴进来")
    try:
        return ai.extract(text, s["name"], s["parent"], open_items, db.today(), images)
    except ai.AIError as e:
        bad(str(e), 502)


# ------------------------------------------------------------------ 导出（老板）
@app.get("/api/export.csv")
def export(kind: str = "items", u=Depends(current_user)):
    if u["role"] != "owner":
        bad("只有老板账号能导出", 403)
    st = state(u)
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "logs":
        w.writerow(["日期", "时间", "学生", "谁", "类型", "内容", "已撤销"])
        for l in reversed(st["logs"]):
            w.writerow([l["date"], l["time"], l["student"], l["who"], l["src"], l["act"], "是" if l["undone"] else ""])
    else:
        w.writerow(["学生", "事项", "负责", "截止", "录入", "约定", "家长回复", "提醒次数", "完成", "学校"])
        for i in st["items"]:
            w.writerow([i["student"], i["what"], i["owner"], i["due"], i["created"], i["agreed"] or "", i["replied"] or "", len(i["chases"]), i["done"] or "", i["school"] or ""])
    data = "﻿" + buf.getvalue()
    name = f"{'留痕' if kind == 'logs' else '事项'}-{db.today()}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse').parse.quote(name)}"})
