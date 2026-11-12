/* ======================= 数据层（Claude 网页版） =======================
   和服务器版的 server.py 做同样的事：每个操作检查输入、改数据、写一条留痕。
   数据存在这个网页自带的数据库里（claude.use("db")），用 Claude 账号识别是谁。
   集合：members（成员和角色）、students、items、logs、memory（本机构自填的学校）、app/settings。 */
let DB = null, USER = null, UID = null, IS_OWNER = false, SAMPLE = null, DICT = null, SAMPLE_IMG = false;
const RAW = {members:new Map(), students:new Map(), items:new Map(), logs:new Map(), memory:new Map(), settings:null};
let READY = {members:false, students:false, items:false, logs:false, memory:false};
const OWNERS = ["学生", "家长", "学校", "机构"];

function pad(n){ return String(n).padStart(2, "0"); }
function nowCN(){ return new Date(Date.now() + 8 * 3600e3); }                // 北京时间
function todayCN(){ const d = nowCN(); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`; }
function stampCN(){ const d = nowCN(); return `${todayCN()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; }
class Bad extends Error {}
const bad = m => { throw new Bad(m); };
function txt(v, name, max = 200, required = true){ v = String(v ?? "").trim(); if (required && !v) bad(`${name}不能为空`); if (v.length > max) bad(`${name}太长了（最多 ${max} 字）`); return v; }
function date(v, name = "日期"){ v = String(v ?? "").trim(); if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) bad(`${name}格式不对`);
  const d = new Date(v + "T00:00:00Z"); if (isNaN(d) || d.toISOString().slice(0, 10) !== v) bad(`${name}不存在`); return v; }
const mdd = s => s.slice(5);
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

/* ---------- 把原始数据拼成页面要的样子（和服务器版 state() 一样） ---------- */
function memberName(uid){ const m = RAW.members.get(uid); return m ? m.name : "成员"; }
function buildState(){
  const me = RAW.members.get(UID) || {name:"我", role: IS_OWNER ? "owner" : "consultant"};
  const studs = [...RAW.students.entries()].filter(([, s]) => !s.archived).sort((a, b) => (a[1].n || 0) - (b[1].n || 0));
  const sname = new Map(studs.map(([id, s]) => [id, s.name]));
  const consOf = new Map(studs.map(([id, s]) => [id, memberName(s.consultant)]));
  const undoAfter = Date.now() - 30 * 60e3;
  return {
    me: {id: UID, name: me.name, role: me.role}, agency: (RAW.settings && RAW.settings.agency) || "我的机构", today: todayCN(), ai: !!SAMPLE, aiImages: !!SAMPLE && SAMPLE_IMG,
    users: [...RAW.members.entries()].map(([id, m]) => ({id, name: m.name, role: m.role, active: m.active !== false})),
    students: studs.map(([id, s]) => ({id, name: s.name, parent: s.parent, consultant: consOf.get(id), consultant_id: s.consultant})),
    items: [...RAW.items.entries()].filter(([, i]) => !i.deleted && sname.has(i.student_id))
      .map(([id, i]) => ({id, student: sname.get(i.student_id), what: i.what, owner: i.owner, due: i.due, created: i.created, agreed: i.agreed || null,
        replied: i.replied || null, replyText: i.reply_text || null, done: i.done || null, school: i.school || null, round: i.round || "", sdl: i.sdl || "", region: i.region || "", rolling: !!i.rolling, chases: i.chases || []}))
      .sort((a, b) => a.due.localeCompare(b.due)),
    logs: [...RAW.logs.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 3000).map(([id, l]) => ({id, n: l.n, date: l.at.slice(0, 10), time: l.at.slice(11),
      who: l.who || memberName(l.uid), src: l.src, act: l.act, student: sname.get(l.student_id) || "", consultant: consOf.get(l.student_id) || "",
      undone: !!l.undone, canUndo: !!l.undo && !l.undone && l.uid === UID && l.n >= undoAfter})),
    memory: Object.fromEntries([...RAW.memory.values()].map(m => [m.school, {d: m.d, by: m.by, on: m.on, src: m.src || "", region: m.region || ""}])),
  };
}

/* ---------- 写操作 ---------- */
const W = {
  set: (col, id, data) => DB.collection(col).doc(id).set(data),
  upd: (col, id, data) => DB.collection(col).doc(id).update(data),
};
function student(id){ const s = RAW.students.get(String(id)); if (!s || s.archived) bad("找不到这个学生"); return {id: String(id), ...s}; }
function item(id){ const i = RAW.items.get(String(id)); if (!i || i.deleted) bad("找不到这个事项"); return {id: String(id), ...i}; }
async function log(student_id, src, act, who, undo){
  const id = newId();
  await W.set("logs", id, {student_id: student_id || null, at: stampCN(), n: Date.now(), uid: UID, who: who || null, src, act, undo: undo || null, undone: false});
  return id;
}
async function addItem(sid, what, owner, due, school, meta){
  what = txt(what, "事项", 120); due = date(due, "截止日");
  if (!OWNERS.includes(owner)) bad("负责人只能是学生、家长、学校或机构");
  const id = newId();
  await W.set("items", id, {student_id: sid, what, owner, due, created: todayCN(), agreed: null, replied: null, reply_text: null, done: null, school: school || null, ...(meta || {}), deleted: false, chases: [], n: Date.now()});
  return id;
}
const meName = () => memberName(UID);
const isOwnerRole = () => (RAW.members.get(UID) || {}).role === "owner";

const ACT = {
  async chased(b){ const it = item(b.item), chases = [...(it.chases || []), todayCN()];
    await W.upd("items", it.id, {chases}); const school = it.owner === "学校";
    return log(it.student_id, school ? "跟进" : "提醒", `${school ? "跟进学校" : "已发提醒"}（第 ${chases.length} 次）：${it.what}`, null, {t:"chase", id: it.id}); },
  async done(b){ const it = item(b.item); if (it.done) bad("这件事已经是完成状态");
    await W.upd("items", it.id, {done: todayCN()});
    return log(it.student_id, "完成", `完成「${it.what}」（${meName()}记录）`, it.owner === "机构" ? null : it.owner, {t:"done", id: it.id}); },
  async agreed(b){ const s = student(b.student);
    const rows = [...RAW.items.entries()].filter(([, i]) => i.student_id === s.id && !i.deleted && !i.done && !i.agreed && (i.owner === "学生" || i.owner === "家长"));
    if (!rows.length) bad("没有需要发约定的事项");
    for (const [id] of rows) await W.upd("items", id, {agreed: todayCN()});
    return log(s.id, "约定", "已发约定给家长：" + rows.map(([, i]) => `「${i.what}」`).join("、"), null, {t:"agreed", ids: rows.map(([id]) => id)}); },
  async replied(b){ const it = item(b.item), d = date(b.date || todayCN()), t = txt(b.text, "家长原话", 300, false);
    await W.upd("items", it.id, {replied: d, reply_text: t || null});
    return log(it.student_id, "微信回复", `家长 ${mdd(d)} 回复${t ? "：“" + t + "”" : ""}（${meName()}记录）`, student(it.student_id).parent, {t:"replied", id: it.id, old: [it.replied || null, it.reply_text || null]}); },
  async parentnote(b){ const s = student(b.student), t = txt(b.text, "家长原话", 300);
    return log(s.id, "微信回复", `家长回复：“${t}”（${meName()}记录，不对应具体事项）`, s.parent, {t:"none"}); },
  async sent(b){ const s = student(b.student); return log(s.id, "反馈家长", `已发${txt(b.what, "内容", 20)}给家长`, null, {t:"none"}); },
  async additems(b){ const s = student(b.student), items = (b.items || []).slice(0, 50); if (!items.length) bad("没有要写入的事项");
    items.forEach(x => { txt(x.what, "事项", 120); date(x.due, "截止日"); if (!OWNERS.includes(x.owner)) bad("负责人不对"); });
    const ids = []; for (const x of items) ids.push(await addItem(s.id, x.what, x.owner, x.due));
    const label = txt(b.from || "手动添加", "来源", 30), quotes = items.filter(x => x.quote).map(x => x.quote);
    return log(s.id, "录入", `${label}，确认 ${ids.length} 条事项：` + items.map(x => `${x.what}（${x.owner}，${mdd(x.due)}）`).join("；")
      + (quotes.length ? "。原话：" + quotes.map(q => `“${q.slice(0, 80)}”`).join(" / ") : ""), null, {t:"items", ids}); },
  async found(b){ const s = student(b.student); let last = null;
    for (const f of (b.found || []).slice(0, 20)){
      if (f.kind === "note"){ last = await log(s.id, "微信回复", `家长回复：“${txt(f.text || f.quote, "家长原话", 300)}”（从粘贴的内容识别，${meName()}确认，不对应具体事项）`, s.parent, {t:"none"}); continue; }
      const it = item(f.item); if (it.student_id !== s.id) bad("事项不属于这个学生");
      const q = txt(f.quote, "原话", 300, false);
      if (f.kind === "replied"){ const d = date(f.date || todayCN());
        await W.upd("items", it.id, {replied: d, reply_text: txt(f.text, "原话", 300, false) || null});
        last = await log(s.id, "微信回复", `家长 ${mdd(d)} 回复：“${q}”（从粘贴的聊天识别，${meName()}确认）`, s.parent, {t:"replied", id: it.id, old: [it.replied || null, it.reply_text || null]}); }
      else if (f.kind === "done" && !it.done){ await W.upd("items", it.id, {done: todayCN()});
        last = await log(s.id, "完成", `完成「${it.what}」：“${q}”（从粘贴的聊天识别，${meName()}确认）`, it.owner, {t:"done", id: it.id}); } }
    return last; },
  async addschool(b){ const s = student(b.student), school = txt(b.school, "学校", 100), rnd = txt(b.round, "轮次", 40), deadline = date(b.deadline, "学校截止日");
    const dbd = b.db_deadline || null, source = txt(b.source, "来源", 200, false), reason = txt(b.reason, "改动原因", 200, false);
    const steps = (b.steps || []).slice(0, 20); if (!steps.length) bad("没有要写入的事项");
    steps.forEach(x => { txt(x.what, "事项", 120); date(x.due, "截止日"); });
    const region = txt(b.region, "地区", 20, false) || "其他", rolling = rnd === "滚动录取" || !!b.rolling;
    const ids = []; for (const x of steps) ids.push(await addItem(s.id, x.what, x.owner, x.due, school, {round: rnd, sdl: deadline, region, rolling}));
    const me = meName();
    const dl = dbd && dbd !== deadline ? `日期库是 ${dbd}，${me}改为 ${deadline}` + (reason ? `（${reason}）` : "")
      : dbd ? `截止日 ${deadline}（日期库，${me}已核对）` : rnd === "滚动录取" || b.rolling ? `滚动录取，计划递交日 ${deadline} 由${me}和学生商定` : `截止日 ${deadline}，${me}自填`;
    const edited = steps.filter(x => x.edited).length;
    const lid = await log(s.id, "加学校", `加入 ${school}（${region}，${rnd}），${dl}${source ? "，来源：" + source : ""}；写入 ${ids.length} 条事项：` + steps.map(x => `${x.what} ${mdd(x.due)}`).join("；")
      + (edited ? `。其中 ${edited} 条的截止日由顾问改过` : ""), null, {t:"items", ids});
    if (b.remember && !dbd && rnd !== "滚动录取" && !b.rolling){
      const key = encodeURIComponent(school).replace(/[^A-Za-z0-9_\-.~:@+]/g, "_").slice(0, 180) || "school";
      const old = [...RAW.memory.entries()].find(([, m]) => m.school === school);
      const id = old ? old[0] : key;
      await W.set("memory", id, {school, d: {...(old ? old[1].d : {}), [rnd]: deadline}, by: me, on: todayCN(), src: source, region}); }
    return lid; },
  async editdue(b){ const it = item(b.item), nd = date(b.due, "新截止日"); if (nd === it.due) bad("日期没有变化");
    const reason = txt(b.reason, "改动原因", 200, false);
    await W.upd("items", it.id, {due: nd});
    return log(it.student_id, "改截止日", `「${it.what}」截止日从 ${it.due} 改为 ${nd}` + (reason ? `（${reason}）` : ""), null, {t:"due", id: it.id, old: it.due}); },
  async deleteitem(b){ const it = item(b.item), reason = txt(b.reason, "删除原因", 200, false);
    await W.upd("items", it.id, {deleted: true});
    return log(it.student_id, "删除事项", `删除「${it.what}」（原截止 ${it.due}）` + (reason ? `，原因：${reason}` : ""), null, {t:"undelete", id: it.id}); },
  async undo(b){ const l = RAW.logs.get(String(b.log));
    if (!l || !l.undo || l.undone || l.uid !== UID) bad("这条记录不能撤销");
    if (l.n < Date.now() - 30 * 60e3) bad("超过 30 分钟的操作不能撤销，请直接修改");
    const u = l.undo;
    if (u.t === "chase"){ const it = RAW.items.get(u.id); if (it){ const c = [...(it.chases || [])]; c.pop(); await W.upd("items", u.id, {chases: c}); } }
    else if (u.t === "done") await W.upd("items", u.id, {done: null});
    else if (u.t === "agreed") for (const id of u.ids) await W.upd("items", id, {agreed: null});
    else if (u.t === "replied") await W.upd("items", u.id, {replied: u.old[0], reply_text: u.old[1]});
    else if (u.t === "items") for (const id of u.ids) await W.upd("items", id, {deleted: true});
    else if (u.t === "due") await W.upd("items", u.id, {due: u.old});
    else if (u.t === "undelete") await W.upd("items", u.id, {deleted: false});
    await W.upd("logs", String(b.log), {undone: true});        // 留痕不删，只标"已撤销"
    return null; },
  async addstudent(b){ const name = txt(b.name, "学生称呼", 30), parent = txt(b.parent, "家长称呼", 30);
    const cid = isOwnerRole() && b.consultant ? String(b.consultant) : UID;
    if (!RAW.members.has(cid)) bad("找不到这个顾问");
    if ([...RAW.students.values()].some(s => s.name === name)) bad("已经有同名学生了，可以加个区分，比如“张同学 A”");
    const id = newId();
    await W.set("students", id, {name, parent, consultant: cid, archived: false, created: todayCN(), n: Date.now()});
    return log(id, "学生", `新建学生 ${name}，家长称呼 ${parent}，负责顾问 ${memberName(cid)}`); },
  async archivestudent(b){ const s = student(b.student); await W.upd("students", s.id, {archived: true});
    return log(s.id, "学生", `${s.name} 已结案（不再显示，记录保留）`); },
  async forget(b){ const school = txt(b.school, "学校", 100);
    for (const [id, m] of RAW.memory) if (m.school === school) await DB.collection("memory").doc(id).delete();
    return log(null, "学校记忆", `删除自填学校 ${school} 的日期`); },
  async myname(b){ const name = txt(b.name, "称呼", 20); const m = RAW.members.get(UID);
    await W.set("members", UID, {...(m || {}), name, role: m ? m.role : (IS_OWNER ? "owner" : "consultant"), active: true});
    return null; },
  async setrole(b){ if (!isOwnerRole()) bad("只有老板能改角色"); const id = String(b.user); if (id === UID) bad("不能改自己的角色");
    const m = RAW.members.get(id) || bad("找不到这个成员"); await W.upd("members", id, {role: b.role === "owner" ? "owner" : "consultant"});
    return log(null, "成员", `把 ${m.name} 设为${b.role === "owner" ? "老板" : "顾问"}`); },
  async agency(b){ if (!isOwnerRole()) bad("只有老板能改机构名称"); await DB.doc("app/settings").set({agency: txt(b.name, "机构名称", 40)}); return null; },
};

let renderTimer = null, pendingRender = false;
function scheduleRender(){
  if (!S) return;
  const a = document.activeElement;
  if (a && a.closest && a.closest("main") && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)){ pendingRender = true; return; }   // 别人改了数据时，不打断正在输入的人
  clearTimeout(renderTimer); renderTimer = setTimeout(() => { D = buildState(); TODAY = D.today; render(); }, 60);
}
document.addEventListener("focusout", () => setTimeout(() => { if (pendingRender){ pendingRender = false; scheduleRender(); } }, 0));

/* 页面主逻辑调用的两个函数 */
async function api(name, payload = {}, label){
  let lid = null;
  try { lid = await ACT[name](payload); }
  catch (e){ toast(e instanceof Bad ? e.message : (e && e.code === "quota_exceeded" ? "数据库已满，请联系管理员" : "保存失败，请重试")); throw e; }
  D = buildState(); TODAY = D.today;
  S.undo = label && lid ? {log: lid, label} : null;
  render();
}
async function extract(sid, text, images = []){
  const s = student(sid);
  const open = [...RAW.items.entries()].filter(([, i]) => i.student_id === s.id && !i.deleted && !i.done).map(([id, i]) => ({id, what: i.what, owner: i.owner, due: i.due}));
  const user = USER_PROMPT.replace("{today}", todayCN()).replace("{student}", s.name).replace("{parent}", s.parent)
    .replace("{items}", () => open.map(i => `${i.id}｜${i.what}｜${i.owner}｜${i.due}`).join("\n") || "（没有）")
    .replace("{imgnote}", images.length ? `（另附 ${images.length} 张图片）` : "").replace("{text}", () => text.trim() || "（没有文字，只有图片）");
  let out;
  try { out = await SAMPLE.json(SYSTEM_PROMPT + "\n\n下面是这一次的输入，请按上面的规则输出 JSON。\n" + user, images.length ? {images} : undefined); }
  catch (e){ toast(e && e.code === "rate_limited" ? "AI 有点忙，请稍后再试" : e && e.code === "not_granted" ? "没有允许使用 AI，可以用手动添加" : "AI 整理失败，请再试一次或手动添加"); throw e; }
  out = out || {};
  const transcript = images.length ? String(out.transcript || "").slice(0, 4000) : "";
  return {...aiCheck(out, text + "\n" + transcript, open), transcript};      // 图片里的原话要在转写文字里，转写给顾问对照图片核对
}
// 提示词和服务器版 ai.py 一样（说明见 提示词/信息整理提示词.md）。改一处要同步另一处。
const SYSTEM_PROMPT = "你是留学申请机构顾问的助理。顾问会给你一段材料，可能是见面笔记、微信聊天记录、家长的回复、学校或考试机构的邮件，也可能是这些内容的截图或照片。\n你的任务只有一个：把材料里和申请事项有关的信息整理成 JSON，供顾问核对后写入系统。你不直接面对家长和学生，不要寒暄，不要给建议。\n\n【要找的三类信息】\n一、新事项 newItems：材料里明确提到、但“已有事项”里没有的待办。写清做什么（what）、谁负责（owner）、最晚哪天（due）。\n二、已有事项的进展 found：\n  - 家长或学生对某个已有事项表示知道了、同意、会去办：kind 写 \"replied\"，item 写那个事项的 id。\n  - 某个已有事项已经办完：kind 写 \"done\"，item 写那个事项的 id。\n  - 家长的回复和任何已有事项都对不上，但值得留个记录（比如“收到，谢谢老师”）：kind 写 \"note\"，item 写 null。\n三、图片转写 transcript：有图片时，先把图片里和申请事项有关的文字逐字抄下来。\n\n【规则】\n1. owner 只能是这四个词之一：学生、家长、学校、机构。“机构”指顾问或机构自己要做的事；“学校”指学生所在中学要做的事，比如成绩单、推荐信。\n2. due 写成 YYYY-MM-DD。材料里是“22 号”“下周一”“月底”这类说法时，按“今天”的日期推算。材料里没有提到时间就写空字符串 \"\"，不要猜。\n3. 每一条都必须带 quote：从材料原文或你的 transcript 里一字不差复制的一小段原话，作为依据。不要改写，不要翻译，不要把两句拼成一句。找不到原话依据的内容不要输出。\n4. 不要把已有事项重复当成新事项。闲聊、没有明确动作的话，不要整理成事项。\n5. what 用简短的动宾短语，不超过 20 个字，比如“付托福送分费”“交 UCL 文书终稿”。\n6. found 里的 text 写家长或学生的原话，date 写这句话是哪天说的，材料里看不出来就写今天。\n7. 红线：不写、不改、不翻译、不评价任何文书、活动描述、推荐信的内容。材料里出现这些正文时直接跳过，transcript 里也不要抄。\n8. 有图片时，transcript 照抄图片里的文字，保留是谁说的（比如“家长：”“顾问：”），看不清的地方写 [看不清]。没有图片时 transcript 写 \"\"。\n9. 只输出一个 JSON 对象。不要输出解释，不要用 ``` 包起来。没有内容的数组写 []。\n\n【输出格式】\n{\"transcript\":\"\",\"newItems\":[{\"what\":\"\",\"owner\":\"\",\"due\":\"\",\"quote\":\"\"}],\"found\":[{\"kind\":\"replied 或 done 或 note\",\"item\":\"已有事项的 id，note 时写 null\",\"date\":\"YYYY-MM-DD\",\"text\":\"\",\"quote\":\"\"}]}\n\n【例子】\n输入：\n今天：2026-11-12。学生：张同学；家长称呼：张妈妈。\n已有事项（id｜事项｜负责人｜截止）：\n17｜付 UC 申请费｜家长｜2026-11-19\n材料：\n<<<\n顾问：张妈妈，UC 申请费记得 19 号前付\n张妈妈：好的，明天就付。对了托福送分是不是也要弄？\n顾问：对，送分要 30 美元，您 22 号前付一下\n张妈妈：行，辛苦老师\n>>>\n输出：\n{\"transcript\":\"\",\"newItems\":[{\"what\":\"付托福送分费\",\"owner\":\"家长\",\"due\":\"2026-11-22\",\"quote\":\"送分要 30 美元，您 22 号前付一下\"}],\"found\":[{\"kind\":\"replied\",\"item\":\"17\",\"date\":\"2026-11-12\",\"text\":\"好的，明天就付\",\"quote\":\"好的，明天就付\"},{\"kind\":\"note\",\"item\":null,\"date\":\"2026-11-12\",\"text\":\"行，辛苦老师\",\"quote\":\"行，辛苦老师\"}]}";
const USER_PROMPT = "今天：{today}。学生：{student}；家长称呼：{parent}。\n已有事项（id｜事项｜负责人｜截止）：\n{items}\n材料{imgnote}：\n<<<\n{text}\n>>>";
function aiCheck(out, text, open){       // 原话必须在原文里；负责人、日期、事项 id 必须合法
  const norm = s => String(s || "").replace(/\s+/g, ""), src = norm(text), ids = new Set(open.map(i => i.id));
  const okDate = s => { try { return /^\d{4}-\d{2}-\d{2}$/.test(s) && new Date(s + "T00:00:00Z").toISOString().slice(0, 10) === s; } catch(e){ return false; } };
  const res = {newItems: [], found: [], dropped: 0};
  for (const x of out.newItems || []){ const q = String(x.quote || "");
    if (!q || !src.includes(norm(q)) || !OWNERS.includes(x.owner) || !String(x.what || "").trim()){ res.dropped++; continue; }
    res.newItems.push({what: String(x.what).trim().slice(0, 120), owner: x.owner, due: okDate(x.due) ? x.due : "", quote: q.slice(0, 300)}); }
  for (const x of out.found || []){ const q = String(x.quote || ""), note = x.kind === "note";
    if (!["replied", "done", "note"].includes(x.kind) || (!note && !ids.has(String(x.item))) || !q || !src.includes(norm(q))){ res.dropped++; continue; }
    res.found.push({kind: x.kind, item: note ? null : String(x.item), date: okDate(x.date) ? x.date : "", text: String(x.text || q).slice(0, 300), quote: q.slice(0, 300)}); }
  return res;
}

/* ---------- 启动：订阅数据，第一次来的人登记成成员 ---------- */
async function boot(){
  const main = document.getElementById("main");
  DB = await claude.use("db"); USER = await claude.use("user");
  if (!DB || !USER){ main.innerHTML = `<div class="card"><div class="empty">请在 Claude 里登录后打开这个页面。</div></div>`; return; }
  UID = await USER.id(); IS_OWNER = !!(USER.isOwner && USER.isOwner());
  if (!UID){ main.innerHTML = `<div class="card"><div class="empty">请在 Claude 里登录后打开这个页面。</div></div>`; return; }
  claude.use("sample").then(async s => { SAMPLE = s;
    try { SAMPLE_IMG = !!(s && s.limits && (await s.limits()).images); } catch (e){ SAMPLE_IMG = false; }
    if (D){ D.ai = !!s; D.aiImages = !!s && SAMPLE_IMG; scheduleRender(); } });
  claude.use("dictation").then(d => { DICT = d; if (D) scheduleRender(); });
  const slow = setTimeout(() => { if (!S) main.innerHTML = `<div class="card"><div class="empty">数据还没连上，请稍等或刷新。</div></div>`; }, 10000);
  const sub = (name, col) => DB.collection(col).onSnapshot(snap => {
    RAW[name] = new Map(snap.docs.map(d => [d.id, d.data()])); READY[name] = true; maybeStart(); scheduleRender();
  }, e => { toast("数据连接中断，请刷新页面"); });
  sub("members", "members"); sub("students", "students"); sub("items", "items"); sub("logs", "logs"); sub("memory", "memory");
  DB.doc("app/settings").onSnapshot(d => { RAW.settings = d.exists ? d.data() : null; scheduleRender(); }, () => {});
  async function maybeStart(){
    if (S || !Object.values(READY).every(Boolean)) return;
    clearTimeout(slow);
    if (!RAW.members.has(UID)){                       // 第一次来：登记称呼
      main.innerHTML = `<div class="card" style="max-width:420px"><div class="head"><b>第一次使用，请填你的称呼</b></div>
        <div class="muted small">会显示在留痕里，比如"王老师"。${IS_OWNER ? "你是这个页面的所有者，会被设为老板。" : "默认是顾问，老板可以在设置里改。"}</div>
        <input type="text" id="first_name" style="margin-top:8px" placeholder="你的称呼"><div class="row"><button class="btn" id="first_go">开始使用</button></div></div>`;
      document.getElementById("first_go").onclick = async () => {
        const name = document.getElementById("first_name").value.trim(); if (!name) return toast("请填称呼");
        try { await W.set("members", UID, {name, role: IS_OWNER ? "owner" : "consultant", active: true, n: Date.now()}); }
        catch(e){ return toast("保存失败：你可能只有查看权限，请让老板把你设为可编辑"); }
        RAW.members.set(UID, {name, role: IS_OWNER ? "owner" : "consultant", active: true}); start(); };
      return;
    }
    start();
  }
  function start(){ D = buildState(); TODAY = D.today; SEEN = Math.max(0, ...D.logs.map(l => l.n)); S = fresh(); render(); }
}
