"""AI 整理：把顾问的笔记或粘贴的微信聊天，整理成"待确认的事项"。

- 只抽取事项和进展，不写、不改、不翻译任何文书内容。
- 每一条都必须带原文里的原话；程序检查原话确实出现在原文里，对不上的直接丢掉。
- 日期由程序再检查一遍；AI 给的事项只是建议，顾问确认后才写入。
- 原文不保存，只把整理结果返回给页面。

配置（环境变量）：AI_API_KEY（必填，不填就只能手动添加）、AI_BASE_URL（默认 DeepSeek）、AI_MODEL（默认 deepseek-chat）。
任何兼容 OpenAI 接口的服务都能用，比如 DeepSeek、通义千问。

图片识别（可选）：DeepSeek 不能看图，要另配一个能看图的模型。填了 AI_VISION_MODEL 才开通。
  AI_VISION_MODEL（比如 qwen-vl-max）、AI_VISION_BASE_URL（默认通义千问 https://dashscope.aliyuncs.com/compatible-mode/v1）、
  AI_VISION_API_KEY（不填就用 AI_API_KEY）。
图片里的原话核对的是模型自己转写出的文字，所以页面会把转写给顾问对照图片看。图片不保存。
"""
import json, os, re
from datetime import datetime

import httpx

OWNERS = {"学生", "家长", "学校", "机构"}


class AIError(Exception):
    pass


def enabled():
    return bool(os.environ.get("AI_API_KEY"))


def images_enabled():
    return bool(os.environ.get("AI_VISION_MODEL") and (os.environ.get("AI_VISION_API_KEY") or os.environ.get("AI_API_KEY")))


REPLY_NOTE = """
这段内容是家长在微信里的回复。重点判断它是在回复上面哪个已有事项（放进 found，kind 写 replied，text 写家长的原话）；家长说已经办好的写 done。只有家长明确提到新的待办时才放进 newItems。
"""

IMG_NOTE = """
另附 {n} 张图片（可能是微信聊天截图、学校或考试机构的邮件截图、手写笔记照片）。
先把图片里和申请事项有关的文字逐字转写进 transcript：照抄，不翻译、不改写；看不清的地方写[看不清]；文书、作文、推荐信正文不要转写。
quote 可以从下面的原文或 transcript 里一字不差地复制。
"""


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
{imgnote}6. 只输出 JSON，格式：
{{"transcript":"图片转写，没有图片就填空字符串","newItems":[{{"what":"...","owner":"家长","due":"2026-11-22","quote":"..."}}],
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


def _json(content):
    """有的模型会在 JSON 外面包一层 ```json，取第一个 { 到最后一个 }。"""
    content = content or ""
    a, b = content.find("{"), content.rfind("}")
    return json.loads(content[a:b + 1] if a >= 0 and b > a else content)


def extract(text, student, parent, open_items, today, images=(), reply=False):
    items = "\n".join(f"{i['id']}｜{i['what']}｜{i['owner']}｜{i['due']}" for i in open_items) or "（没有）"
    prompt = PROMPT.format(today=today, student=student, parent=parent, items=items,
                           imgnote=(IMG_NOTE.format(n=len(images)) if images else "") + (REPLY_NOTE if reply else ""), text=text or "（没有文字，只有图片）")
    if images:
        model, base = os.environ["AI_VISION_MODEL"], os.environ.get("AI_VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        key = os.environ.get("AI_VISION_API_KEY") or os.environ["AI_API_KEY"]
        content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
        body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": content}]}
    else:
        model, base, key = os.environ.get("AI_MODEL", "deepseek-chat"), os.environ.get("AI_BASE_URL", "https://api.deepseek.com"), os.environ["AI_API_KEY"]
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]}
    try:
        r = httpx.post(f"{base.rstrip('/')}/chat/completions", json=body, timeout=90, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        out = _json(r.json()["choices"][0]["message"]["content"])
    except httpx.HTTPError as e:
        raise AIError(f"AI 服务暂时连不上（{type(e).__name__}），请稍后再试或手动添加")
    except (KeyError, IndexError, TypeError, ValueError):
        raise AIError("AI 返回的格式不对，请再试一次或手动添加")
    transcript = str(out.get("transcript") or "")[:4000] if images else ""
    return check(out, (text or "") + "\n" + transcript, open_items) | {"transcript": transcript}


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
