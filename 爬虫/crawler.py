#!/usr/bin/env python3
"""学校截止日期爬虫。

用法：
    python crawler.py            # 抓取 sources.yaml 里的全部来源，更新 data/ 下的文件
    python crawler.py --pdf x.pdf  # 不联网，直接解析本地的 Common App 总表（调试用）
    python crawler.py --reset      # 忽略上一次的结果，重建日期库

输出（都在 data/ 里）：
    deadlines.json / deadlines.csv   日期库：学校、轮次、截止日、申请费、来源、来源更新日、抓取时间
    deadlines_web.js                 给网页原型用的精简版（学校 -> 各轮次截止日；英港澳学校另带来源和备注）
    changes.md                       每次运行和上一次相比的变化（新增、删除、日期改动、网页变化）
    state.json                       上次抓取的状态（用来判断有没有变化）

原则：日期库里的日期只是"建议值"，顾问确认后才生效；每条都带来源和抓取时间。
"""
import argparse, csv, datetime as dt, hashlib, io, json, re, sys
from pathlib import Path

import pdfplumber, requests, yaml
from pdfplumber.utils import extract_text

ROOT = Path(__file__).parent
DATA = ROOT / "data"
UA = "deadline-checker/0.1"          # 通用的客户端名，不带任何个人信息
ROUNDS = ["ED", "EDII", "EA", "EAII", "REA", "RD"]
TYPES = {"Coed", "Women", "Men", "Coordinate"}
DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def fetch(url, state):
    """下载一个网址。服务器说没变（304）就返回 None，避免重复下载。"""
    headers = {"User-Agent": UA}
    old = state.get(url, {})
    if old.get("etag"):
        headers["If-None-Match"] = old["etag"]
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code == 304:
        return None
    r.raise_for_status()
    state.setdefault(url, {})["etag"] = r.headers.get("ETag", "")
    return r.content


# ---------------------------------------------------------------- Common App
def parse_commonapp(pdf_bytes, url):
    """解析 Common App 要求总表。

    PDF 里没有表格线，所以按"字的横坐标"判断每个日期属于哪一列：
    每页表头里有 ED / EDII / EA / EAII / REA / Rolling 这几个词，日期离哪个表头最近就算哪一轮。
    每行以"学校类型"（Coed / Women / Men / Coordinate）那个词定位。
    """
    out, updated = [], ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5)
            chars = page.chars
            if not updated:
                for i, w in enumerate(words):
                    if w["text"] == "Updated:" and i + 1 < len(words):
                        m = re.match(r"(\d{2})-(\d{2})-(\d{4})", words[i + 1]["text"])
                        if m:
                            updated = f"{m[3]}-{m[1]}-{m[2]}"
            cx = lambda w: (w["x0"] + w["x1"]) / 2
            # 表头列的位置（只在页面上部找）
            cols = {}
            for w in words:
                if w["top"] > 100:
                    break
                t = w["text"]
                if t in ("ED", "EDII", "EA", "EAII", "REA") and t not in cols:
                    cols[t] = cx(w)
                elif t in ("Rolling", "RD/") and "RD" not in cols:
                    cols["RD"] = cx(w)
                elif t == "US" and "fee_us" not in cols:
                    cols["fee_us"] = cx(w)
                elif t == "Int'l" and "fee_intl" not in cols:
                    cols["fee_intl"] = cx(w)
                elif t == "type" and "type" not in cols:
                    cols["type"] = cx(w)
            if not all(k in cols for k in ROUNDS + ["type"]):
                continue                                   # 这一页不是表格页（比如末尾的注释页）
            # 每一行的定位点：类型列里的词
            anchors = sorted((w for w in words if w["text"] in TYPES and abs(cx(w) - cols["type"]) < 15 and w["top"] > 95),
                             key=lambda w: w["top"])
            name_right = min(w["x0"] for w in anchors) - 2 if anchors else 0
            mids = [(a["top"] + a["bottom"]) / 2 for a in anchors]
            # 把表头以下的每个词分给纵向最近的那一行（学校名换行时，上下几行都属于同一所学校）
            rows_words = [[] for _ in anchors]
            for w in words:
                if w["top"] < 97 or not anchors:
                    continue
                c = (w["top"] + w["bottom"]) / 2
                j = min(range(len(anchors)), key=lambda k: abs(mids[k] - c))
                if abs(mids[j] - c) < 22:
                    rows_words[j].append(w)
            for i, a in enumerate(anchors):
                band = rows_words[i]
                # 学校名按"字符"重组：名字换行时 PDF 里两行的字是交错存放的，按词取会乱
                cs = [c for c in chars if c["x1"] <= name_right + 1 and c["top"] >= 97
                      and min(range(len(anchors)), key=lambda k: abs(mids[k] - (c["top"] + c["bottom"]) / 2)) == i
                      and abs(mids[i] - (c["top"] + c["bottom"]) / 2) < 22]
                name = " ".join(extract_text(cs, x_tolerance=1.5, y_tolerance=2).split()).replace("\u2019", "'") if cs else ""
                if not name:
                    continue
                rec = {"school": name, "type": a["text"], "rounds": {}, "fee_us": "", "fee_intl": ""}
                for w in band:
                    t, x = w["text"], cx(w)
                    if DATE.match(t) or t == "Rolling":
                        rnd = min(ROUNDS, key=lambda r: abs(cols[r] - x))
                        if abs(cols[rnd] - x) > 16:
                            continue
                        if t == "Rolling":
                            rec["rounds"][rnd] = "Rolling"
                        else:
                            m = DATE.match(t)
                            rec["rounds"][rnd] = f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}"
                    elif t.startswith("$") and "fee_us" in cols:
                        if abs(x - cols["fee_us"]) < 14:
                            rec["fee_us"] = t
                        elif abs(x - cols.get("fee_intl", -99)) < 14:
                            rec["fee_intl"] = t
                out.append(rec)
    rows, seen = [], {}
    for r in out:
        # 总表里个别学校有多行（比如不同校区或项目），第 2 行起在校名后标注，提醒人工核对
        seen[r["school"]] = seen.get(r["school"], 0) + 1
        if seen[r["school"]] > 1:
            r["school"] += f"（总表第 {seen[r['school']]} 行，请核对）"
        for rnd, d in r["rounds"].items():
            rows.append({"region": "美国", "school": r["school"], "school_type": r["type"], "round": rnd, "deadline": d, "note": "",
                         "fee_us": r["fee_us"], "fee_intl": r["fee_intl"],
                         "source": "Common App 要求总表", "source_url": url, "source_updated": updated})
    return rows


# ---------------------------------------------------------------- 网页监控
def page_text(html_bytes):
    if html_bytes[:5] == b"%PDF-":                      # 有些学校把日期放在 PDF 传单里
        with pdfplumber.open(io.BytesIO(html_bytes)) as pdf:
            return " ".join((p.extract_text() or "") for p in pdf.pages)
    s = html_bytes.decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


DATEISH = re.compile(r"(?i)\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
                     r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
                     r"|\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}/\d{4})")


# ---------------------------------------------------------------- 主流程
def diff(old, new):
    key = lambda r: (r["school"], r["round"])
    o, n = {key(r): r for r in old}, {key(r): r for r in new}
    lines = []
    for k in sorted(n.keys() - o.keys()):
        lines.append(f"- 新增：{k[0]}｜{k[1]}｜{n[k]['deadline']}")
    for k in sorted(o.keys() - n.keys()):
        lines.append(f"- 删除：{k[0]}｜{k[1]}｜原为 {o[k]['deadline']}")
    for k in sorted(n.keys() & o.keys()):
        if n[k]["deadline"] != o[k]["deadline"]:
            lines.append(f"- **日期改动**：{k[0]}｜{k[1]}｜{o[k]['deadline']} → {n[k]['deadline']}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="解析本地的 Common App 总表 PDF，不联网")
    ap.add_argument("--reset", action="store_true", help="忽略上一次的结果，重建日期库（变化记录会从头开始）")
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    state_f, dl_f = DATA / "state.json", DATA / "deadlines.json"
    state = json.loads(state_f.read_text("utf-8")) if state_f.exists() else {}
    first_run = args.reset or not dl_f.exists()
    if args.reset:
        state = {}
    old = [] if first_run else json.loads(dl_f.read_text("utf-8"))["deadlines"]
    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text("utf-8"))
    new, notes, stamp = list(old), [], now()

    for src in cfg["sources"]:
        name, url, typ = src["name"], src["url"], src["type"]
        try:
            if typ == "commonapp_grid":
                raw = Path(args.pdf).read_bytes() if args.pdf else fetch(url, state)
                if raw is None:
                    notes.append(f"- {name}：文件没有变化，跳过。")
                    continue
                rows = parse_commonapp(raw, url)
                if len(rows) < 200:                       # 解析结果明显不对时，不覆盖旧数据
                    notes.append(f"- **{name}：只解析出 {len(rows)} 条，可能是 PDF 版式变了，旧数据未改动，需要人工检查。**")
                    continue
                for r in rows:
                    r["fetched_at"] = stamp
                keep = [r for r in new if r.get("source") != "Common App 要求总表"]
                mine = [r for r in new if r.get("source") == "Common App 要求总表"]
                changes = diff(mine, rows)
                new = keep + rows
                if first_run:
                    notes.append(f"- {name}：首次导入 {len(rows)} 条（{len({r['school'] for r in rows})} 所学校）。")
                elif changes:
                    notes.append(f"- {name}：{len(changes)} 处变化。")
                    notes += ["  " + c for c in changes]
                else:
                    notes.append(f"- {name}：内容没有变化。")
            elif typ == "watch":
                if args.pdf:
                    continue
                raw = fetch(url, state)
                if raw is None:
                    notes.append(f"- {name}：网页没有变化。")
                    continue
                text = page_text(raw)
                dates = sorted({" ".join(d.split()) for d in DATEISH.findall(text)})[:300]
                st = state.setdefault(url, {})
                # 只比较页面上出现的日期。整页内容每次都会有小变动（广告、时间戳），比较整页会天天误报。
                if "dates" in st and st["dates"] != dates:
                    gone = sorted(set(st["dates"]) - set(dates))
                    came = sorted(set(dates) - set(st["dates"]))
                    notes.append(f"- **{name}：官网页面上的日期有变化，请人工核实并更新 manual_deadlines.csv。** {url}")
                    if came: notes.append(f"  - 新出现的日期：{'、'.join(came)}")
                    if gone: notes.append(f"  - 消失的日期：{'、'.join(gone)}")
                elif "dates" not in st:
                    notes.append(f"- {name}：首次记录，页面上有 {len(dates)} 个日期。"
                                 + ("页面上读不到日期，这个网页的变化提醒不起作用，需要人工定期查看。" if not dates else ""))
                else:
                    notes.append(f"- {name}：日期没有变化。" + ("（页面上读不到日期，需要人工定期查看）" if not dates else ""))
                st.update(dates=dates, checked_at=stamp)
        except requests.RequestException as e:            # 网站打不开或拒绝访问：记一笔，不算需要人工核实
            code = getattr(getattr(e, "response", None), "status_code", "")
            notes.append(f"- {name}：这次没抓到（{type(e).__name__} {code}）。旧数据未改动，这个网站拒绝程序访问的话需要人工定期查看。")
        except Exception as e:                            # 一个来源出错不影响其他来源
            notes.append(f"- **{name}：抓取失败（{type(e).__name__}: {e}）。旧数据未改动。**")

    # 人工核实过的日期表（英国、香港、澳洲）：每次运行都整表重新读入
    mf = ROOT / "manual_deadlines.csv"
    if mf.exists():
        with mf.open(encoding="utf-8-sig") as f:
            manual = [{"region": r["region"], "school": r["school"], "school_type": "", "round": r["round"], "deadline": r["deadline"],
                       "note": r["note"], "fee_us": "", "fee_intl": "", "source": "学校官网（人工核实）", "source_url": r["source_url"],
                       "source_updated": r["verified_on"], "fetched_at": stamp} for r in csv.DictReader(f)]
        mine = [r for r in new if r.get("source") == "学校官网（人工核实）"]
        changes = diff(mine, manual)
        new = [r for r in new if r.get("source") != "学校官网（人工核实）"] + manual
        if changes and mine:
            notes.append(f"- 人工日期表：{len(changes)} 处变化。"); notes += ["  " + c.replace("**", "") for c in changes]
        elif not mine:
            notes.append(f"- 人工日期表：首次导入 {len(manual)} 条（{len({r['school'] for r in manual})} 所学校）。")
    for r in new:                                       # 旧版本生成的记录没有这两列，补上
        r.setdefault("region", "美国"); r.setdefault("note", "")

    new.sort(key=lambda r: (r["region"], r["school"], ROUNDS.index(r["round"]) if r["round"] in ROUNDS else 9))
    payload = {"generated_at": stamp, "count": len(new), "deadlines": new}
    dl_f.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    # 给网页原型用的精简版：学校 -> 各轮次截止日
    web = {}
    ca = [r for r in new if r.get("source") == "Common App 要求总表"]
    for r in ca:
        web.setdefault(r["school"], {})[r["round"]] = r["deadline"]
    # 英国、香港、澳洲（人工核实表）也放进去；info 里记每所学校的地区、来源和备注。截止日为空的记成 Rolling（滚动录取）。
    info = {}
    for r in new:
        if r.get("source") != "学校官网（人工核实）":
            continue
        web.setdefault(r["school"], {})[r["round"]] = r["deadline"] or "Rolling"
        i = info.setdefault(r["school"], {"region": r["region"], "source": r["source"], "source_url": r["source_url"],
                                          "verified_on": r["source_updated"], "notes": {}})
        if r["note"]:
            i["notes"][r["round"]] = r["note"]
    meta = {"generated_at": stamp, "source": "Common App 要求总表", "source_url": next((r["source_url"] for r in ca), ""),
            "source_updated": next((r["source_updated"] for r in ca), ""), "schools": web, "info": info}
    (DATA / "deadlines_web.js").write_text("// 由 crawler.py 生成，不要手改。\nwindow.DEADLINES = " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + ";\n", "utf-8")
    with (DATA / "deadlines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        cols = ["region", "school", "school_type", "round", "deadline", "note", "fee_us", "fee_intl", "source", "source_url", "source_updated", "fetched_at"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(new)
    state_f.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    ch = DATA / "changes.md"
    prev = ch.read_text("utf-8") if ch.exists() and not args.reset else "# 变化记录\n"
    head, _, rest = prev.partition("\n")
    ch.write_text(f"{head}\n\n## {stamp}\n\n" + "\n".join(notes) + "\n" + rest, "utf-8")
    print("\n".join(notes)); print(f"共 {len(new)} 条，已写入 {DATA}")
    if any("**" in n for n in notes):
        sys.exit(2)                                       # 有需要人看的变化时返回 2，方便定时任务发通知


if __name__ == "__main__":
    main()
