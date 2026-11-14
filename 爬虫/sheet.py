"""日期核对表：一个 Excel 文件，给机构顾问核对和补充，改完直接导回网站用的数据。

  python sheet.py export            生成 日期核对表.xlsx（内容来自 manual_deadlines.csv 和 app 的 config.js）
  python sheet.py import [文件]     把改好的表导回：写 manual_deadlines.csv，更新 config.js 里的内部时间和提醒规则

表里有三张要填的表：
  学校截止日    地区、学校、轮次、截止日（滚动录取就写"滚动录取"）、备注、来源链接、核对日期。库里没有的学校在最后加行。
  机构内部时间  加一所学校时自动生成的事项：事项、负责人、在学校截止日前几天。
  提醒规则      提醒家长的时间、临期的天数。
美国 Common App 的一千多所学校不在表里，由爬虫直接从官方 PDF 读；要改其中某一所，或加 Common App 没有的学校，在"学校截止日"里加一行。
把改好的文件放回 爬虫/日期核对表.xlsx 并推到 main，GitHub 会自动导入并重新生成日期库。
"""
import csv, re, sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).parent
CSV = ROOT / "manual_deadlines.csv"
XLSX = ROOT / "日期核对表.xlsx"
CONFIGS = [ROOT.parent / "app" / "static" / "config.js", ROOT.parent / "app" / "artifact" / "config.js"]
COLS = ["region", "school", "round", "deadline", "note", "source_url", "verified_on"]
HEAD = ["地区", "学校", "轮次", "截止日", "备注", "来源链接", "核对日期"]
OWNERS = ["学生", "家长", "学校", "机构"]
BACKPLAN_RE = re.compile(r"backplan: \[\n(.*?)\n  \],", re.S)
STEP_RE = re.compile(r'\{ what: "(.*?)",\s*owner: "(.*?)", days: (\d+) \}')


def read_config():
    s = CONFIGS[0].read_text(encoding="utf-8")
    steps = STEP_RE.findall(BACKPLAN_RE.search(s).group(1))
    chase = re.search(r"chaseDays: \[(.*?)\]", s).group(1)
    soon = re.search(r"soonDays: (\d+)", s).group(1)
    return steps, chase, soon


def export():
    wb = Workbook()
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F5D62")

    def sheet(ws, head, rows, widths):
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
        for r in rows:
            ws.append(list(r))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.number_format = "@"                      # 全部当文字，Excel 不会自动改日期格式
                c.alignment = Alignment(vertical="top", wrap_text=True)
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "填写说明"
    for line in ["日期核对表：请顾问核对截止日，补上表里没有的学校。改完把文件发回即可，数据会直接放进网站。", "",
                 "一、学校截止日", "1. 日期不对的，直接改「截止日」一列，格式 2026-11-30。滚动录取写：滚动录取。",
                 "2. 表里没有的学校，在最后加一行。地区、学校、轮次、截止日必填，其余可以空着。",
                 "3. 同一所学校有几个轮次或批次，每个轮次写一行。专业截止更早的，在备注里写明。",
                 "4. 这张表以英国、香港、澳洲为主。美国 Common App 的学校由系统自动读取，不在表里；发现错误或要加别的美国学校，同样在最后加一行。", "",
                 "二、机构内部时间", "加一所学校时，系统自动生成这些事项。「提前天数」是在学校截止日前几天完成。可以改天数、改负责人、增删行。",
                 "事项名称里的 {学校} 和 {轮次} 会自动换成学校名和轮次，请保留。负责人只能是：学生、家长、学校、机构。", "",
                 "三、提醒规则", "「提醒家长」是截止前第几天提醒，用逗号隔开，0 表示截止当天。「临期」是几天内到期算临期。"]:
        ws.append([line])
    ws.column_dimensions["A"].width = 110
    for c in ws["A"]:
        c.alignment = Alignment(wrap_text=True)
    for r in (1, 3, 9, 13):
        ws.cell(r, 1).font = Font(bold=True)

    with CSV.open(encoding="utf-8-sig") as f:
        rows = [[r[c] if c != "deadline" else (r[c] or "滚动录取") for c in COLS] for r in csv.DictReader(f)]
    sheet(wb.create_sheet("学校截止日"), HEAD, rows, [8, 34, 22, 14, 60, 50, 14])
    steps, chase, soon = read_config()
    sheet(wb.create_sheet("机构内部时间"), ["事项", "负责人", "提前天数"], steps, [36, 10, 12])
    sheet(wb.create_sheet("提醒规则"), ["项目", "数值"], [["提醒家长（截止前第几天）", chase], ["临期（几天内到期）", soon]], [30, 16])
    wb.move_sheet("填写说明", offset=3)                  # 数据放第一页，打开就能看到；说明放最后
    wb.active = 0
    for w in wb:
        w.sheet_view.tabSelected = w.title == "学校截止日"
    wb.save(XLSX)
    print(f"已生成 {XLSX.name}：{len(rows)} 条截止日，{len(steps)} 条内部时间")


def norm_date(v):
    """认 2026-11-30、2026/11/30、2026年11月30日、Excel 日期；滚动录取返回空字符串；看不懂返回 None。"""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    v = str(v or "").strip()
    if not v or "滚动" in v or v.lower() == "rolling":
        return ""
    m = re.match(r"^(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?$", v)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def cells(ws):
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        vals = [("" if v is None else v) for v in row]
        if any(str(v).strip() for v in vals):
            yield n, [v.strip() if isinstance(v, str) else v for v in vals]


def import_(path):
    wb = load_workbook(path, data_only=True)
    errs, today = [], date.today().isoformat()
    with CSV.open(encoding="utf-8-sig") as f:
        old = {(r["school"], r["round"]): r for r in csv.DictReader(f)}

    out, seen = [], set()
    for n, v in cells(wb["学校截止日"]):
        v = (v + [""] * 7)[:7]
        region, school, rnd, raw, note, url, ver = [str(x).strip() if not isinstance(x, (datetime, date)) else x for x in v]
        d = norm_date(raw)
        if not (region and school and rnd):
            errs.append(f"学校截止日 第 {n} 行：地区、学校、轮次都要填")
        elif d is None:
            errs.append(f"学校截止日 第 {n} 行：截止日「{raw}」看不懂，请写成 2026-11-30 或 滚动录取")
        elif (school, rnd) in seen:
            errs.append(f"学校截止日 第 {n} 行：{school} 的「{rnd}」重复了")
        else:
            seen.add((school, rnd))
            o = old.get((school, rnd))
            same = o and (o["region"], o["deadline"], o["note"], o["source_url"]) == (region, d, note, url)
            out.append({"region": region, "school": school, "round": rnd, "deadline": d, "note": note, "source_url": url,
                        "verified_on": o["verified_on"] if same else (norm_date(ver) if isinstance(ver, (datetime, date)) else today)})

    steps = []
    for n, v in cells(wb["机构内部时间"]):
        what, owner, days = (v + ["", "", ""])[:3]
        try:
            days = int(float(days))
        except (TypeError, ValueError):
            days = -1
        if not str(what).strip() or owner not in OWNERS or not 0 <= days <= 365 or '"' in str(what):
            errs.append(f"机构内部时间 第 {n} 行：事项不能空，负责人只能是 学生/家长/学校/机构，提前天数是 0 到 365 的整数")
        else:
            steps.append((str(what).strip(), owner, days))

    rules = {str(v[0]).strip(): str(v[1]).strip() for _, v in cells(wb["提醒规则"]) if len(v) >= 2}
    chase = soon = None
    for k, val in rules.items():
        if k.startswith("提醒家长"):
            try:
                chase = sorted({int(float(x)) for x in re.split(r"[,，、\s]+", val) if x}, reverse=True)
            except ValueError:
                pass
        elif k.startswith("临期"):
            soon = int(float(val)) if re.match(r"^\d+(\.0)?$", val) else None
    if not chase or any(not 0 <= x <= 60 for x in chase):
        errs.append("提醒规则：「提醒家长」请写成用逗号隔开的天数，比如 7, 3, 0")
    if soon is None or not 1 <= soon <= 60:
        errs.append("提醒规则：「临期」请写 1 到 60 之间的整数")
    if not out:
        errs.append("学校截止日是空的")
    if not steps:
        errs.append("机构内部时间是空的")
    if errs:
        print("核对表有问题，没有导入：\n" + "\n".join("- " + e for e in errs))
        sys.exit(1)

    changed = [f"{r['school']} {r['round']}：{(old[(r['school'], r['round'])]['deadline'] or '滚动录取') if (r['school'], r['round']) in old else '新增'} → {r['deadline'] or '滚动录取'}"
               for r in out if (r["school"], r["round"]) not in old or old[(r["school"], r["round"])]["deadline"] != r["deadline"]]
    removed = [f"{s} {r}" for (s, r) in old if (s, r) not in seen]
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    block = "backplan: [\n" + ",\n".join(f'    {{ what: "{w_}", owner: "{o}", days: {d} }}' for w_, o, d in steps) + "\n  ],"
    for p in CONFIGS:
        s = p.read_text(encoding="utf-8")
        s = BACKPLAN_RE.sub(lambda m: block, s, count=1)
        s = re.sub(r"chaseDays: \[.*?\]", f"chaseDays: [{', '.join(map(str, chase))}]", s, count=1)
        s = re.sub(r"soonDays: \d+", f"soonDays: {soon}", s, count=1)
        s = re.sub(r"临期：\d+ 天内到期", f"临期：{soon} 天内到期", s, count=1)
        p.write_text(s, encoding="utf-8")
    print(f"已导入：{len(out)} 条截止日（{len(changed)} 条新增或改动，{len(removed)} 条被删掉），{len(steps)} 条内部时间，提醒 {chase}，临期 {soon} 天")
    for c in changed + ["删掉：" + r for r in removed]:
        print("  " + c)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "export":
        export()
    elif len(sys.argv) >= 2 and sys.argv[1] == "import":
        import_(sys.argv[2] if len(sys.argv) > 2 else XLSX)
    else:
        print(__doc__)
