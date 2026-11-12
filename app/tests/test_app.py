"""后台测试：python -m pytest tests -q（在 app/ 目录下运行）"""
import os, sys, tempfile
from pathlib import Path

os.environ["APP_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ["SECURE_COOKIE"] = "0"
os.environ.pop("AI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

import ai, db, server

H = {"X-App": "1"}


def make_agency(name, login):
    with db.connect() as con:
        aid = con.execute("INSERT INTO agency (name, created) VALUES (?,?)", (name, db.today())).lastrowid
        con.execute("INSERT INTO user (agency_id, name, login, pw, role) VALUES (?,?,?,?, 'owner')", (aid, "老板" + name, login, db.hash_pw("password1")))


def client(login, pw="password1"):
    c = TestClient(server.app)
    r = c.post("/api/login", json={"login": login, "password": pw}, headers=H)
    assert r.status_code == 200, r.text
    return c


def act(c, op, **kw):
    r = c.post("/api/act", json={"op": op, **kw}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def setup():
    make_agency("甲", "boss_a")
    make_agency("乙", "boss_b")
    a = client("boss_a")
    st = act(a, "adduser", name="王老师", login="wang", password="password2")
    wang = client("wang", "password2")
    wid = next(u["id"] for u in st["users"] if u["name"] == "王老师")
    st = act(a, "addstudent", name="张同学", parent="张妈妈", consultant=wid)
    sid = st["students"][0]["id"]
    return a, wang, sid


def test_login_required_and_header():
    c = TestClient(server.app)
    assert c.get("/api/state").status_code == 401
    assert c.get("/", follow_redirects=False).status_code in (302, 307)
    assert c.post("/api/login", json={"login": "x", "password": "y"}).status_code == 403   # 缺 X-App 头
    assert c.post("/api/login", json={"login": "boss_a", "password": "wrong"}, headers=H).status_code in (401, 429)


def test_addschool_with_edited_deadline_and_steps(setup):
    a, wang, sid = setup
    steps = [{"what": "交 UCL 文书终稿", "owner": "学生", "due": "2026-12-30"},
             {"what": "确认 UCL 推荐信已上传", "owner": "学校", "due": "2027-01-05", "edited": True},
             {"what": "UCL 送分（语言、标化）", "owner": "机构", "due": "2026-12-20", "edited": True},
             {"what": "递交 UCL（UCAS 1 月截止）", "owner": "机构", "due": "2027-01-08"}]
    st = act(wang, "addschool", student=sid, school="UCL", round="UCAS 1 月截止", deadline="2027-01-10",
             db_deadline="2027-01-13", reason="经济学专业要求更早", source="UCAS", steps=steps)
    its = [i for i in st["items"] if i["school"] == "UCL"]
    assert len(its) == 4 and {i["owner"] for i in its} == {"学生", "学校", "机构"}
    log = st["logs"][0]["act"]
    assert "日期库是 2027-01-13，王老师改为 2027-01-10（经济学专业要求更早）" in log
    assert "2 条的截止日由顾问改过" in log


def test_editdue_logs_and_undo(setup):
    a, wang, sid = setup
    st = act(wang, "additems", student=sid, items=[{"what": "付雅思送分费", "owner": "家长", "due": "2026-12-01"}])
    iid = next(i["id"] for i in st["items"] if i["what"] == "付雅思送分费")
    st = act(wang, "editdue", item=iid, due="2026-11-28", reason="学校提前了")
    assert next(i for i in st["items"] if i["id"] == iid)["due"] == "2026-11-28"
    assert "从 2026-12-01 改为 2026-11-28（学校提前了）" in st["logs"][0]["act"]
    lid = st["logs"][0]["id"]
    assert st["logs"][0]["canUndo"]
    st = act(wang, "undo", log=lid)
    assert next(i for i in st["items"] if i["id"] == iid)["due"] == "2026-12-01"
    assert next(l for l in st["logs"] if l["id"] == lid)["undone"]      # 留痕保留，只标已撤销


def test_chase_agree_done_flow(setup):
    a, wang, sid = setup
    st = act(wang, "agreed", student=sid)
    fam = [i for i in st["items"] if i["owner"] in ("学生", "家长")]
    assert all(i["agreed"] for i in fam)
    iid = fam[0]["id"]
    st = act(wang, "chased", item=iid)
    assert len(next(i for i in st["items"] if i["id"] == iid)["chases"]) == 1
    st = act(wang, "replied", item=iid, text="收到")
    assert st["logs"][0]["who"] == "张妈妈"
    st = act(wang, "done", item=iid)
    assert next(i for i in st["items"] if i["id"] == iid)["done"]


def test_custom_school_memory(setup):
    a, wang, sid = setup
    steps = [{"what": "递交 Toronto（RD）", "owner": "机构", "due": "2027-01-12"}]
    st = act(wang, "addschool", student=sid, school="University of Toronto", round="RD", deadline="2027-01-15", steps=steps, remember=True, source="官网")
    assert st["memory"]["University of Toronto"]["d"] == {"RD": "2027-01-15"}
    st = act(a, "addschool", student=sid, school="Rolling U", round="滚动录取", deadline="2027-02-01", steps=steps, remember=True, rolling=True)
    assert "Rolling U" not in st["memory"]                                 # 滚动录取的计划日只属于这个学生
    st = act(wang, "forget", school="University of Toronto")
    assert "University of Toronto" not in st["memory"]


def test_agency_isolation(setup):
    a, wang, sid = setup
    b = client("boss_b")
    st = b.get("/api/state").json()
    assert st["students"] == [] and st["items"] == [] and st["memory"] == {}
    r = b.post("/api/act", json={"op": "addschool", "student": sid, "school": "X", "round": "RD", "deadline": "2027-01-01",
                                 "steps": [{"what": "x", "owner": "机构", "due": "2027-01-01"}]}, headers=H)
    assert r.status_code == 400                                            # 不能动别的机构的学生
    iid = a.get("/api/state").json()["items"][0]["id"]
    assert b.post("/api/act", json={"op": "done", "item": iid}, headers=H).status_code == 400


def test_permissions_and_validation(setup):
    a, wang, sid = setup
    r = wang.post("/api/act", json={"op": "adduser", "name": "x", "login": "x2", "password": "password9"}, headers=H)
    assert r.status_code == 403
    r = wang.post("/api/act", json={"op": "additems", "student": sid, "items": [{"what": "x", "owner": "老师", "due": "2027-01-01"}]}, headers=H)
    assert r.status_code == 400
    r = wang.post("/api/act", json={"op": "additems", "student": sid, "items": [{"what": "x", "owner": "家长", "due": "2027-02-30"}]}, headers=H)
    assert r.status_code == 400
    assert wang.get("/api/export.csv").status_code == 403
    r = a.get("/api/export.csv?kind=logs")
    assert r.status_code == 200 and "留痕" not in r.text[:5] and "王老师" in r.text


def test_ai_check_drops_unquoted():
    text = "托福送分还没下单，得让家长这周把 30 美元付了，最晚 22 号。"
    out = {"newItems": [{"what": "付托福送分费", "owner": "家长", "due": "2026-11-22", "quote": "得让家长这周把 30 美元付了，最晚 22 号"},
                        {"what": "编出来的", "owner": "家长", "due": "2026-11-23", "quote": "原文里没有这句"},
                        {"what": "日期不对", "owner": "家长", "due": "2026-13-40", "quote": "托福送分还没下单"}],
           "found": [{"kind": "done", "item": 999, "quote": "托福送分还没下单"}]}
    r = ai.check(out, text, [{"id": 1}])
    assert [x["what"] for x in r["newItems"]] == ["付托福送分费", "日期不对"]
    assert r["newItems"][1]["due"] == ""                                  # 不合法的日期清空，让顾问填
    assert r["dropped"] == 2


def test_pages_served(setup):
    a, wang, sid = setup
    assert "申请进度助手" in a.get("/").text
    assert a.get("/deadlines.js").status_code == 200
    assert "window.CFG" in a.get("/config.js").text


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_image_extract(setup, monkeypatch):
    a, wang, sid = setup
    st = wang.get("/api/state").json()
    assert st["aiImages"] is False
    r = wang.post("/api/extract", json={"student": sid, "text": "", "images": [PNG]}, headers=H)
    assert r.status_code == 400                                           # 没配 AI 不能识别
    monkeypatch.setenv("AI_API_KEY", "k")
    r = wang.post("/api/extract", json={"student": sid, "text": "", "images": [PNG]}, headers=H)
    assert r.status_code == 400 and "图片识别" in r.json()["detail"]       # 只配了 DeepSeek，没配看图模型
    monkeypatch.setenv("AI_VISION_MODEL", "qwen-vl-max")
    assert wang.get("/api/state").json()["aiImages"] is True
    assert wang.post("/api/extract", json={"student": sid, "images": ["data:text/html;base64,AAAA"]}, headers=H).status_code == 400
    assert wang.post("/api/extract", json={"student": sid, "images": [PNG] * 5}, headers=H).status_code == 400

    sent = {}
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"transcript": "张妈妈：雅思送分费我 20 号前交", '
                    '"newItems": [{"what": "付雅思送分费", "owner": "家长", "due": "2026-11-20", "quote": "雅思送分费我 20 号前交"},'
                    '{"what": "编的", "owner": "家长", "due": "2026-11-21", "quote": "图里没有这句"}], "found": []}\n```'}}]}
    def post(url, json, timeout, headers):
        sent.update(url=url, body=json); return R()
    monkeypatch.setattr(ai.httpx, "post", post)
    r = wang.post("/api/extract", json={"student": sid, "text": "", "images": [PNG]}, headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [x["what"] for x in out["newItems"]] == ["付雅思送分费"] and out["dropped"] == 1
    assert "雅思送分费" in out["transcript"]
    assert sent["url"].startswith("https://dashscope.aliyuncs.com") and sent["body"]["model"] == "qwen-vl-max"
    assert sent["body"]["messages"][0]["content"][1]["image_url"]["url"] == PNG


def test_school_region_and_parent_note(setup):
    a, wang, sid = setup
    steps = [{"what": "递交 NUS（主批）", "owner": "机构", "due": "2027-02-10"}]
    st = act(wang, "addschool", student=sid, school="NUS", round="主批", deadline="2027-02-15", region="新加坡", steps=steps, remember=True)
    it = next(i for i in st["items"] if i["school"] == "NUS")
    assert (it["region"], it["round"], it["sdl"], it["rolling"]) == ("新加坡", "主批", "2027-02-15", False)
    assert st["memory"]["NUS"]["region"] == "新加坡"
    assert "加入 NUS（新加坡，主批）" in st["logs"][0]["act"]
    st = act(wang, "parentnote", student=sid, text="好的，下周我们去开存款证明")
    assert st["logs"][0]["src"] == "微信回复" and st["logs"][0]["who"] == "张妈妈" and "存款证明" in st["logs"][0]["act"]
    assert wang.post("/api/act", json={"op": "parentnote", "student": sid, "text": ""}, headers=H).status_code == 400
