"""AI 整理：把顾问的笔记或粘贴的微信聊天，整理成"待确认的事项"。

- 只抽取事项和进展，不写、不改、不翻译任何文书内容。
- 每一条都必须带原文里的原话；程序检查原话确实出现在原文里，对不上的直接丢掉。
- 日期由程序再检查一遍；AI 给的事项只是建议，顾问确认后才写入。
- 原文不保存，只把整理结果返回给页面。

配置（环境变量）：AI_API_KEY（必填，不填就只能手动添加）、AI_BASE_URL（默认 DeepSeek）、AI_MODEL（默认 deepseek-chat）。
任何兼容 OpenAI 接口的服务都能用，比如 DeepSeek、通义千问。
"""
import json, os, re
from datetime import datetime

import httpx

OWNERS = {"学生", "家长", "学校", "机构"}


class AIError(Exception):
    pass


def enabled():
    return bool(os.environ.get("AI_API_KEY"))


PROMPT = """你是留学申请机构的助理，只做一件事：从顾问给的文字里找出"谁要在哪天前做什么"，以及已有事项的进展。
今天是 {today}。学生：{student}；家长称呼：{parent}。

这个学生现在没完成的事项（id、事项、负责人、截止）：
{items}

规则：
1. 只抽取明确的待办事项。负责人只能是：学生、家长、学校、机构（机构=顾问或机构自己）。
2. 截止日写成 YYYY-MM-DD。原文是"22 号""下周一"这类说法时，按今天推算；原文没有日期就填空字符串，不要猜。
3. 每一条都要附原文里的原话（quote），必须一字不差地从原文复制，不要改写、不要合并多句。
4. 如果原文显示上面某个已有事项"家长已回复确认"或"已经完成"，放进 found，写明对应的 id。不要把已有事项再当成新事项。
5. 不写、不改、不翻译任何文书、活动描述、推荐信的内容。
6. 只输出 JSON，格式：
{{"newItems":[{{"what":"...","owner":"家长","due":"2026-11-22","quote":"..."}}],
  "found":[{{"kind":"replied 或 done","item":12,"date":"YYYY-MM-DD","text":"家长原话","quote":"..."}}]}}

原文：
<<<
{text}
>>>"""


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _date_ok(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def extract(text, student, parent, open_items, today):
    items = "\n".join(f"{i['id']}｜{i['what']}｜{i['owner']}｜{i['due']}" for i in open_items) or "（没有）"
    body = {"model": os.environ.get("AI_MODEL", "deepseek-chat"), "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.format(today=today, student=student, parent=parent, items=items, text=text)}]}
    base = os.environ.get("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, timeout=60,
                       headers={"Authorization": f"Bearer {os.environ['AI_API_KEY']}"})
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
    except httpx.HTTPError as e:
        raise AIError(f"AI 服务暂时连不上（{type(e).__name__}），请稍后再试或手动添加")
    except (KeyError, ValueError, json.JSONDecodeError):
        raise AIError("AI 返回的格式不对，请再试一次或手动添加")
    return check(out, text, open_items)


def check(out, text, open_items):
    """程序检查：原话必须在原文里；负责人、日期、事项 id 必须合法。不合格的丢掉并计数。"""
    src, ids = _norm(text), {i["id"] for i in open_items}
    new, found, dropped = [], [], 0
    for x in out.get("newItems") or []:
        q = str(x.get("quote") or "")
        if not q or _norm(q) not in src or x.get("owner") not in OWNERS or not str(x.get("what") or "").strip():
            dropped += 1
            continue
        due = x.get("due") if _date_ok(x.get("due")) else ""
        new.append({"what": str(x["what"]).strip()[:120], "owner": x["owner"], "due": due, "quote": q[:300]})
    for x in out.get("found") or []:
        q = str(x.get("quote") or "")
        if x.get("kind") not in ("replied", "done") or x.get("item") not in ids or not q or _norm(q) not in src:
            dropped += 1
            continue
        found.append({"kind": x["kind"], "item": x["item"], "date": x.get("date") if _date_ok(x.get("date")) else "",
                      "text": str(x.get("text") or "")[:300], "quote": q[:300]})
    return {"newItems": new, "found": found, "dropped": dropped}
