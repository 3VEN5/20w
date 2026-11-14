"""AI 整理：把顾问的笔记、粘贴的微信聊天、学校来信（offer、补材料、面试、拒信、候补），整理成"待确认的事项"和"录取结果与条件"。

- 只抽取事项和进展，不写、不改、不翻译任何文书内容。
- 每一条都必须带原文里的原话；程序检查原话确实出现在原文里，对不上的直接丢掉。
- 日期由程序再检查一遍；AI 给的事项只是建议，顾问确认后才写入。
- 原文不保存，只把整理结果返回给页面。

配置（环境变量）：AI_API_KEY（必填，不填就只能手动添加）、AI_BASE_URL（默认 DeepSeek）、AI_MODEL（默认 deepseek-chat）。
任何兼容 OpenAI 接口的服务都能用，比如 DeepSeek、通义千问。

图片识别：默认也用 DeepSeek，模型 deepseek-flash（能看图），和文字用同一个密钥，不用另外配。
  想换别家：AI_VISION_MODEL（比如 qwen-vl-max）、AI_VISION_BASE_URL、AI_VISION_API_KEY。AI_VISION_MODEL=off 关掉图片识别。
图片里的原话核对的是模型自己转写出的文字，所以页面会把转写给顾问对照图片看。图片不保存。
"""
import json, os, re
from datetime import datetime

import httpx

OWNERS = {"学生", "家长", "学校", "机构"}
VISION_MODEL = "deepseek-flash"      # DeepSeek 能看图的模型（官方文档 api-docs.deepseek.com/guides/vision）


class AIError(Exception):
    pass


def enabled():
    return bool(os.environ.get("AI_API_KEY"))


def images_enabled():
    return os.environ.get("AI_VISION_MODEL", VISION_MODEL) != "off" and bool(os.environ.get("AI_VISION_API_KEY") or os.environ.get("AI_API_KEY"))


# 提示词：系统提示词讲规则和格式（固定不变），用户消息放这一次的材料。DeepSeek、通义千问、豆包、Kimi、智谱等国内模型都能直接用。
# 同一份提示词的说明在 提示词/信息整理提示词.md；改了这里，记得同步改 artifact/store.js。
SYSTEM_PROMPT = """你是留学申请机构顾问的助理。顾问会给你一段材料，可能是见面笔记、微信聊天记录、家长的回复，也可能是学校发来的录取通知（offer）、补材料邮件、面试邀请、拒信、候补通知，或者这些内容的截图、照片、PDF 里的文字。材料可能是中文，也可能是英文。
你的任务只有一个：把材料里和申请事项有关的信息整理成 JSON，供顾问核对后写入系统。你不直接面对家长和学生，不要寒暄，不要给建议。

【要找的四类信息】
一、新事项 newItems：材料里明确提到、但“已有事项”里没有的待办。写清做什么（what）、谁负责（owner）、最晚哪天（due）、属于哪所学校（school，不属于某所学校就写 ""）。
二、已有事项的进展 found：
  - 家长或学生对某个已有事项表示知道了、同意、会去办：kind 写 "replied"，item 写那个事项的 id。
  - 某个已有事项已经办完：kind 写 "done"，item 写那个事项的 id。
  - 顾问、家长或学校说某个已有事项不用做了、取消了、不需要了（比如“不用补交成绩单了”“这所不申了，申请费不用付”）：kind 写 "cancel"，item 写那个事项的 id。只是推迟、改时间不算取消。
  - 某个已有事项的截止时间变了（推迟、提前、改到某天，比如“成绩单推迟到下周五再交”“学校把推荐信截止延到 12 月 1 号”）：kind 写 "due"，item 写那个事项的 id，due 写新的截止日（YYYY-MM-DD，按“今天”推算；只说“晚点”“过几天”算不出具体哪天就写 ""）。
  - 某个已有事项换了负责人（比如“申请费改成学生自己付”）：kind 写 "owner"，item 写那个事项的 id，owner 写新的负责人（学生、家长、学校、机构之一）。
  - 状态是“已取消”的事项又要做了（比如“送分还是要送的，之前说错了”）：kind 写 "restore"，item 写那个已取消事项的 id。不要为它新建事项。
  - 整所学校不申请了（比如“LSE 不申了”），并且这所学校在“已报名学校”里：kind 写 "dropschool"，school 照抄“已报名学校”里的写法，item 写 null。不要再逐条取消它的事项。
  - 学校整体的申请截止日变了（比如“港大第一批截止延到 12 月 5 号”）：kind 写 "sdl"，school 照抄“已报名学校”里的写法，due 写新的学校截止日，item 写 null。只是其中某一件事改时间，用上面的 "due"。
  - 和任何已有事项都对不上，但值得留个记录的话（比如家长说“收到，谢谢老师”，或顾问自己记的一句情况）：kind 写 "note"，item 写 null，by 写这句话是谁说的：家长、学生、学校、顾问。材料是顾问自己写的笔记、没有标明是谁说的，就写“顾问”。
  - replied、done、cancel、due、owner 只能用在状态是“待办”的事项上。
三、学校来信 doc：材料是学校发给学生的正式通知时才填，否则 doc 写 null。
  - type 只能是：offer（录取通知）、补材料、面试、拒信、候补、其他。
  - school：学校名。“已报名学校”里有同一所学校时，照抄那里的写法；没有就照抄材料里的写法。
  - program：专业或项目名，照抄材料，没有写 ""。
  - result 只能是：有条件录取、无条件录取、延期、拒绝、候补、""（不是录取结果时写 ""）。延期指提前批没有录取、转到常规轮再审（deferred），这时 type 写“其他”。
  - conditions：录取条件或学校提出的要求，一条写一项。text 用中文简要概括（成绩、分数、科目、证书名照抄原文，不要换算），due 是这一条要求的最晚日期，quote 是原话。接受录取的截止日、开学日期、学费金额不算条件，不要写进 conditions。只写学生要达到的标准（成绩、语言分数、毕业、学位等），“请登录系统确认”“请回复”这类办手续的提醒不算条件。
  - quote：材料里说明这是什么通知的那句原话。
四、图片转写 transcript：有图片时，先把图片里和申请事项有关的文字逐字抄下来。

【学校来信要生成哪些新事项】
材料里写了日期的，才生成事项；没写日期的不要自己编，系统会另外提示顾问。事项名称一律用简体中文，学校用顾问平时的叫法（港大、港科大、剑桥、曼大）。
- offer：接受录取的截止日 → “接受 XX 录取”（学生）；押金、留位费、学费首付的截止日 → “付 XX 留位费”（家长）；每一条带日期的录取条件 → “达到 XX 录取条件并提交成绩”或“提交 XX 语言成绩”等（学生）；要求补交文件的截止日 → “提交 XX 最终成绩单”等（学校或学生）。开学或报到日期写成“XX 开学报到”（学生）。
- 补材料：每一份要补的材料一条事项，按材料归谁办来定负责人（成绩单、推荐信是学校；护照、资金证明是家长；作品集、问卷是学生）。
- 面试：有回复或预约截止日 → “预约 XX 面试时间”（学生）；有面试日期 → “参加 XX 面试”（学生）。
- 候补：要求在某天前回复是否留在候补名单 → “回复 XX 是否留在候补名单”（学生）。
- 延期：要求在某天前提交期中成绩或补充材料 → “提交 XX 期中成绩”（学校）或“向 XX 提交补充材料”（学生）。
- 拒信：不生成事项，只填 doc。

【规则】
1. owner 只能是这四个词之一：学生、家长、学校、机构。“机构”指顾问或机构自己要做的事；“学校”指学生所在中学要做的事，比如成绩单、推荐信。
2. due 写成 YYYY-MM-DD。材料里是“22 号”“下周一”“月底”这类说法时，按“今天”的日期推算；英文日期（March 31, 2025）直接换成这个格式，年份照材料写，不要改。材料里只给了一段时间范围、还没定具体哪天的（比如“面试在 9 日到 13 日之间”），due 也写 ""，让顾问定下来后自己填；“某天之前”这种截止日照常写那一天。材料里明明有这件事、但日期被遮住或看不清的（比如“If we do not hear from you by [看不清]”），事项照常生成，due 写 ""，让顾问对照原件填。材料里没有提到时间就写空字符串 ""，不要猜。
3. 每一条都必须带 quote：从材料原文或你的 transcript 里一字不差复制的一小段原话，作为依据。原文是英文就复制英文，不要翻译，不要改写，不要把两句拼成一句。找不到原话依据的内容不要输出。
4. 不要把已有事项重复当成新事项。闲聊、没有明确动作的话，不要整理成事项。
5. what 用简短的动宾短语，不超过 20 个字，比如“付托福送分费”“接受港大录取”。
6. found 里的 text 写家长或学生的原话，date 写这句话是哪天说的，材料里看不出来就写今天。
7. 红线：不写、不改、不翻译、不评价任何文书、活动描述、推荐信的内容。材料里出现这些正文时直接跳过，transcript 里也不要抄。
8. 有图片时，transcript 照抄图片里的文字，保留是谁说的（比如“家长：”“顾问：”），看不清的地方写 [看不清]。没有图片时 transcript 写 ""。
9. 只输出一个 JSON 对象。不要输出解释，不要用 ``` 包起来。没有内容的数组写 []。

【输出格式】
{"transcript":"","doc":null 或 {"type":"","school":"","program":"","result":"","conditions":[{"text":"","due":"","quote":""}],"quote":""},"newItems":[{"what":"","owner":"","due":"","school":"","quote":""}],"found":[{"kind":"replied、done、cancel、due、owner、restore、dropschool、sdl、note 之一","item":"已有事项的 id，note 时写 null","date":"YYYY-MM-DD","due":"kind 是 due 或 sdl 时写新日期","owner":"kind 是 owner 时写新负责人","school":"kind 是 dropschool 或 sdl 时写学校","by":"kind 是 note 时写谁说的","text":"","quote":""}]}

【例子一：聊天记录】
输入：
今天：2026-11-12。学生：张同学；家长称呼：张妈妈。
已报名学校：UCLA
已有事项（id｜事项｜负责人｜截止｜状态）：
17｜付 UC 申请费｜家长｜2026-11-19｜待办
材料：
<<<
顾问：张妈妈，UC 申请费记得 19 号前付
张妈妈：好的，明天就付。对了托福送分是不是也要弄？
顾问：对，送分要 30 美元，您 22 号前付一下
张妈妈：行，辛苦老师
>>>
输出：
{"transcript":"","doc":null,"newItems":[{"what":"付托福送分费","owner":"家长","due":"2026-11-22","school":"","quote":"送分要 30 美元，您 22 号前付一下"}],"found":[{"kind":"replied","item":"17","date":"2026-11-12","text":"好的，明天就付","quote":"好的，明天就付"},{"kind":"note","item":null,"date":"2026-11-12","text":"行，辛苦老师","quote":"行，辛苦老师"}]}

【例子二：录取通知】
输入：
今天：2027-03-22。学生：陈同学；家长称呼：陈爸爸。
已报名学校：香港大学 HKU、UCL
已有事项（id｜事项｜负责人｜截止｜状态）：
（没有）
材料：
<<<
THE UNIVERSITY OF HONG KONG
Offer of admission
It is my great pleasure to offer you admission to the University of Hong Kong. This is a conditional offer with details as set out below:
Programme 6729 - Bachelor of Science
Start of teaching September 1, 2027
This offer is conditional upon your obtaining the following on or before August 17, 2027:
A*AA or better in three GCE Advanced Level subjects, including A or better in Mathematics
If we do not hear from you by March 31, 2027, our offer will no longer be valid.
>>>
输出：
{"transcript":"","doc":{"type":"offer","school":"香港大学 HKU","program":"6729 - Bachelor of Science","result":"有条件录取","conditions":[{"text":"三门 GCE A-Level 达到 A*AA 或以上，其中数学 A 或以上","due":"2027-08-17","quote":"A*AA or better in three GCE Advanced Level subjects, including A or better in Mathematics"}],"quote":"This is a conditional offer with details as set out below"},"newItems":[{"what":"接受港大录取","owner":"学生","due":"2027-03-31","school":"香港大学 HKU","quote":"If we do not hear from you by March 31, 2027, our offer will no longer be valid."},{"what":"达到港大录取条件并提交成绩","owner":"学生","due":"2027-08-17","school":"香港大学 HKU","quote":"This offer is conditional upon your obtaining the following on or before August 17, 2027"},{"what":"港大开学报到","owner":"学生","due":"2027-09-01","school":"香港大学 HKU","quote":"Start of teaching September 1, 2027"}],"found":[]}"""

USER_PROMPT = """今天：{today}。学生：{student}；家长称呼：{parent}。
已报名学校：{schools}
已有事项（id｜事项｜负责人｜截止｜状态）：
{items}
材料{imgnote}：
<<<
{text}
>>>"""

FOUND_KINDS = {"replied", "done", "cancel", "due", "owner", "restore", "dropschool", "sdl", "note"}
NOTE_BY = {"家长", "学生", "学校", "顾问"}
DOC_TYPES = {"offer", "补材料", "面试", "拒信", "候补", "其他"}
DOC_RESULTS = {"有条件录取", "无条件录取", "延期", "拒绝", "候补", ""}


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


def extract(text, student, parent, open_items, today, images=(), schools=()):
    items = "\n".join(f"{i['id']}｜{i['what']}｜{i['owner']}｜{i['due']}｜{'已取消' if i.get('cancelled') else '待办'}" for i in open_items) or "（没有）"
    user = (USER_PROMPT.replace("{today}", today).replace("{student}", student).replace("{parent}", parent).replace("{items}", items).replace("{schools}", "、".join(schools) or "（还没有）")
            .replace("{imgnote}", f"（另附 {len(images)} 张图片）" if images else "").replace("{text}", text or "（没有文字，只有图片）"))
    if images:
        model, base = os.environ.get("AI_VISION_MODEL", VISION_MODEL), os.environ.get("AI_VISION_BASE_URL", "https://api.deepseek.com")
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
    return check(out, (text or "") + "\n" + transcript, open_items, schools) | {"transcript": transcript}


def check(out, text, open_items, schools=()):
    """程序检查：原话必须在原文里；负责人、日期、事项 id 必须合法。不合格的丢掉并计数。"""
    src = _norm(text)
    ids, gone = {i["id"] for i in open_items if not i.get("cancelled")}, {i["id"] for i in open_items if i.get("cancelled")}
    new, found, dropped = [], [], 0
    for x in out.get("newItems") or []:
        q = str(x.get("quote") or "")
        if not q or _norm(q) not in src or x.get("owner") not in OWNERS or not str(x.get("what") or "").strip():
            dropped += 1
            continue
        due = x.get("due") if _date_ok(x.get("due")) else ""
        new.append({"what": str(x["what"]).strip()[:120], "owner": x["owner"], "due": due, "school": str(x.get("school") or "").strip()[:100], "quote": q[:300]})
    for x in out.get("found") or []:
        q, kind, item = str(x.get("quote") or ""), x.get("kind"), x.get("item")
        if isinstance(item, str) and item.isdigit():
            item = int(item)                                   # 有的模型把 id 写成字符串
        if kind not in FOUND_KINDS or not q or _norm(q) not in src:
            dropped += 1
            continue
        f = {"kind": kind, "item": None, "date": x.get("date") if _date_ok(x.get("date")) else "", "text": str(x.get("text") or q)[:300], "quote": q[:300]}
        if kind == "note":
            f["by"] = x.get("by") if x.get("by") in NOTE_BY else "家长"
        elif kind in ("dropschool", "sdl"):                    # 针对整所学校：学校必须是这个学生已经报名的
            if x.get("school") not in schools:
                dropped += 1
                continue
            f["school"] = x["school"]
            if kind == "sdl":
                f["due"] = x.get("due") if _date_ok(x.get("due")) else ""
        else:                                                  # 针对某一件事：id 必须对得上，状态也要对
            if item not in (gone if kind == "restore" else ids) or (kind == "owner" and x.get("owner") not in OWNERS):
                dropped += 1
                continue
            f["item"] = item
            if kind == "due":
                f["due"] = x.get("due") if _date_ok(x.get("due")) else ""
            if kind == "owner":
                f["owner"] = x["owner"]
        found.append(f)
    doc, d = None, out.get("doc")
    if isinstance(d, dict) and d.get("type") in DOC_TYPES and str(d.get("school") or "").strip():
        q = str(d.get("quote") or "")
        if q and _norm(q) in src:                              # 学校来信也要有原话依据
            conds = []
            for x in d.get("conditions") or []:
                cq = str((x or {}).get("quote") or "")
                if not cq or _norm(cq) not in src or not str(x.get("text") or "").strip():
                    dropped += 1
                    continue
                conds.append({"text": str(x["text"]).strip()[:200], "due": x.get("due") if _date_ok(x.get("due")) else "", "quote": cq[:300]})
            doc = {"type": d["type"], "school": str(d["school"]).strip()[:100], "program": str(d.get("program") or "").strip()[:120],
                   "result": d.get("result") if d.get("result") in DOC_RESULTS else "", "conditions": conds[:10], "quote": q[:300]}
        else:
            dropped += 1
    return {"newItems": new, "found": found, "doc": doc, "dropped": dropped}
