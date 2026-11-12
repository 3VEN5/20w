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


# 提示词：系统提示词讲规则和格式（固定不变），用户消息放这一次的材料。DeepSeek、通义千问、豆包、Kimi、智谱等国内模型都能直接用。
# 同一份提示词的说明在 app/prompts.md；改了这里，记得同步改 artifact/store.js。
SYSTEM_PROMPT = """你是留学申请机构顾问的助理。顾问会给你一段材料，可能是见面笔记、微信聊天记录、家长的回复、学校或考试机构的邮件，也可能是这些内容的截图或照片。
你的任务只有一个：把材料里和申请事项有关的信息整理成 JSON，供顾问核对后写入系统。你不直接面对家长和学生，不要寒暄，不要给建议。

【要找的三类信息】
一、新事项 newItems：材料里明确提到、但“已有事项”里没有的待办。写清做什么（what）、谁负责（owner）、最晚哪天（due）。
二、已有事项的进展 found：
  - 家长或学生对某个已有事项表示知道了、同意、会去办：kind 写 "replied"，item 写那个事项的 id。
  - 某个已有事项已经办完：kind 写 "done"，item 写那个事项的 id。
  - 家长的回复和任何已有事项都对不上，但值得留个记录（比如“收到，谢谢老师”）：kind 写 "note"，item 写 null。
三、图片转写 transcript：有图片时，先把图片里和申请事项有关的文字逐字抄下来。

【规则】
1. owner 只能是这四个词之一：学生、家长、学校、机构。“机构”指顾问或机构自己要做的事；“学校”指学生所在中学要做的事，比如成绩单、推荐信。
2. due 写成 YYYY-MM-DD。材料里是“22 号”“下周一”“月底”这类说法时，按“今天”的日期推算。材料里没有提到时间就写空字符串 ""，不要猜。
3. 每一条都必须带 quote：从材料原文或你的 transcript 里一字不差复制的一小段原话，作为依据。不要改写，不要翻译，不要把两句拼成一句。找不到原话依据的内容不要输出。
4. 不要把已有事项重复当成新事项。闲聊、没有明确动作的话，不要整理成事项。
5. what 用简短的动宾短语，不超过 20 个字，比如“付托福送分费”“交 UCL 文书终稿”。
6. found 里的 text 写家长或学生的原话，date 写这句话是哪天说的，材料里看不出来就写今天。
7. 红线：不写、不改、不翻译、不评价任何文书、活动描述、推荐信的内容。材料里出现这些正文时直接跳过，transcript 里也不要抄。
8. 有图片时，transcript 照抄图片里的文字，保留是谁说的（比如“家长：”“顾问：”），看不清的地方写 [看不清]。没有图片时 transcript 写 ""。
9. 只输出一个 JSON 对象。不要输出解释，不要用 ``` 包起来。没有内容的数组写 []。

【输出格式】
{"transcript":"","newItems":[{"what":"","owner":"","due":"","quote":""}],"found":[{"kind":"replied 或 done 或 note","item":"已有事项的 id，note 时写 null","date":"YYYY-MM-DD","text":"","quote":""}]}

【例子】
输入：
今天：2026-11-12。学生：张同学；家长称呼：张妈妈。
已有事项（id｜事项｜负责人｜截止）：
17｜付 UC 申请费｜家长｜2026-11-19
材料：
<<<
顾问：张妈妈，UC 申请费记得 19 号前付
张妈妈：好的，明天就付。对了托福送分是不是也要弄？
顾问：对，送分要 30 美元，您 22 号前付一下
张妈妈：行，辛苦老师
>>>
输出：
{"transcript":"","newItems":[{"what":"付托福送分费","owner":"家长","due":"2026-11-22","quote":"送分要 30 美元，您 22 号前付一下"}],"found":[{"kind":"replied","item":"17","date":"2026-11-12","text":"好的，明天就付","quote":"好的，明天就付"},{"kind":"note","item":null,"date":"2026-11-12","text":"行，辛苦老师","quote":"行，辛苦老师"}]}"""

USER_PROMPT = """今天：{today}。学生：{student}；家长称呼：{parent}。
已有事项（id｜事项｜负责人｜截止）：
{items}
材料{imgnote}：
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


def extract(text, student, parent, open_items, today, images=()):
    items = "\n".join(f"{i['id']}｜{i['what']}｜{i['owner']}｜{i['due']}" for i in open_items) or "（没有）"
    user = (USER_PROMPT.replace("{today}", today).replace("{student}", student).replace("{parent}", parent).replace("{items}", items)
            .replace("{imgnote}", f"（另附 {len(images)} 张图片）" if images else "").replace("{text}", text or "（没有文字，只有图片）"))
    if images:
        model, base = os.environ["AI_VISION_MODEL"], os.environ.get("AI_VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        key = os.environ.get("AI_VISION_API_KEY") or os.environ["AI_API_KEY"]
        content = [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
        body = {"model": model, "temperature": 0, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]}
    else:
        model, base, key = os.environ.get("AI_MODEL", "deepseek-chat"), os.environ.get("AI_BASE_URL", "https://api.deepseek.com"), os.environ["AI_API_KEY"]
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]}
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
        q, kind, item = str(x.get("quote") or ""), x.get("kind"), x.get("item")
        if isinstance(item, str) and item.isdigit():
            item = int(item)                                   # 有的模型把 id 写成字符串
        if kind not in ("replied", "done", "note") or not q or _norm(q) not in src or (kind != "note" and item not in ids):
            dropped += 1
            continue
        found.append({"kind": kind, "item": None if kind == "note" else item, "date": x.get("date") if _date_ok(x.get("date")) else "",
                      "text": str(x.get("text") or q)[:300], "quote": q[:300]})
    return {"newItems": new, "found": found, "dropped": dropped}
