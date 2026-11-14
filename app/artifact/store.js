/* ======================= 数据层（Claude 网页版） =======================
   和服务器版的 server.py 做同样的事：每个操作检查输入、改数据、写一条留痕。
   数据存在这个网页自带的数据库里（claude.use("db")），用 Claude 账号识别是谁。
   集合：members（成员和角色）、students、items、logs、memory（本机构自填的学校）、app/settings。 */
let DB = null, USER = null, UID = null, IS_OWNER = false, SAMPLE = null, DICT = null, SAMPLE_IMG = false;
const RAW = {members:new Map(), students:new Map(), items:new Map(), logs:new Map(), memory:new Map(), outcomes:new Map(), settings:null};
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
const mdd = s => `${+s.slice(5, 7)}月${+s.slice(8, 10)}日`;
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
    outcomes: [...RAW.outcomes.entries()].filter(([, o]) => !o.deleted && sname.has(o.student_id)).sort((a, b) => (a[1].n || 0) - (b[1].n || 0))
      .map(([id, o]) => ({id, student: sname.get(o.student_id), school: o.school, kind: o.kind, result: o.result || "", program: o.program || "", conditions: o.conditions || [], date: o.on, by: o.by})),
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
    const ids = []; for (const x of items) ids.push(await addItem(s.id, x.what, x.owner, x.due, txt(x.school, "学校", 100, false) || null));
    const label = txt(b.from || "手动添加", "来源", 30), quotes = items.filter(x => x.quote).map(x => x.quote);
    return log(s.id, "录入", `${label}，确认 ${ids.length} 条事项：` + items.map(x => `${x.what}（${x.owner}，${mdd(x.due)}）`).join("；")
      + (quotes.length ? "。原话：" + quotes.map(q => `“${q.slice(0, 80)}”`).join(" / ") : ""), null, {t:"items", ids}); },
  async outcome(b){ const s = student(b.student), school = txt(b.school, "学校", 100), kind = b.kind;   // 学校来信：只存结果、条件和原话，不存原件
    if (!DOC_KINDS[kind]) bad("来信类型不对");
    const result = DOC_RESULTS.includes(b.result) ? b.result : "", program = txt(b.program, "专业", 120, false);
    const conds = (b.conditions || []).slice(0, 10).map(x => ({text: txt(x.text, "条件", 200), due: x.due ? date(x.due, "条件截止日") : ""}));
    const quote = txt(b.quote, "原话", 300, false), id = newId(), me = meName();
    await W.set("outcomes", id, {student_id: s.id, school, kind, result, program, conditions: conds, on: todayCN(), by: me, deleted: false, n: Date.now()});
    return log(s.id, "学校来信", `${school} ${DOC_KINDS[kind]}` + (result ? `：${result}` : "") + (program ? `，${program}` : "")
      + (conds.length ? "。条件：" + conds.map(x => x.text + (x.due ? `（${mdd(x.due)}前）` : "")).join("；") : "")
      + (quote ? `。原话：“${quote.slice(0, 120)}”` : "") + `（${me}核对后记录）`, school, {t:"outcome", id}); },
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
  async edititem(b){ const it = item(b.item), what = txt(b.what, "事项", 120), owner = b.owner, due = date(b.due, "截止日");
    if (!OWNERS.includes(owner)) bad("负责人只能是学生、家长、学校或机构");
    const ch = [], upd = {};
    if (what !== it.what){ ch.push(`名称改为「${what}」`); upd.what = what; }
    if (owner !== it.owner){ ch.push(`负责人从${it.owner}改为${owner}`); upd.owner = owner; }
    if (due !== it.due){ ch.push(`截止日从 ${it.due} 改为 ${due}`); upd.due = due; }
    if (!ch.length) bad("没有改动");
    const reason = txt(b.reason, "改动原因", 200, false);
    await W.upd("items", it.id, upd);
    return log(it.student_id, "修改事项", `「${it.what}」${ch.join("，")}` + (reason ? `（${reason}）` : ""), null, {t:"edit", id: it.id, old: {what: it.what, owner: it.owner, due: it.due}}); },
  async removeschool(b){ const s = student(b.student), school = txt(b.school, "学校", 100), reason = txt(b.reason, "移除原因", 200, false);
    const ids = [...RAW.items].filter(([, it]) => it.student_id === s.id && it.school === school && !it.deleted).map(([id]) => id);
    if (!ids.length) bad("这个学生没有这所学校的事项");
    for (const id of ids) await W.upd("items", id, {deleted: true});
    return log(s.id, "移除学校", `移除 ${school}，连同 ${ids.length} 条事项` + (reason ? `，原因：${reason}` : ""), null, {t:"restore", ids}); },
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
    else if (u.t === "edit") await W.upd("items", u.id, u.old);
    else if (u.t === "outcome") await W.upd("outcomes", u.id, {deleted: true});
    else if (u.t === "restore") for (const id of u.ids) await W.upd("items", id, {deleted: false});
    await W.upd("logs", String(b.log), {undone: true});        // 留痕不删，只标"已撤销"
    return null; },
  async addstudent(b){ const name = txt(b.name, "学生称呼", 30), parent = txt(b.parent, "家长称呼", 30);
    const cid = isOwnerRole() && b.consultant ? String(b.consultant) : UID;
    if (!RAW.members.has(cid)) bad("找不到这个顾问");
    if ([...RAW.students.values()].some(s => s.name === name)) bad("已经有同名学生了，可以加个区分，比如“张同学 A”");
    const id = newId();
    await W.set("students", id, {name, parent, consultant: cid, archived: false, created: todayCN(), n: Date.now()});
    for (let i = 0; i < 50 && !RAW.students.has(id); i++) await new Promise(r => setTimeout(r, 60));   // 等新学生同步回来，紧接着的加学校才找得到
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
    .replace("{schools}", () => [...new Set([...RAW.items.values()].filter(i => i.student_id === s.id && !i.deleted && i.school).map(i => i.school))].join("、") || "（还没有）")
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
const SYSTEM_PROMPT = "你是留学申请机构顾问的助理。顾问会给你一段材料，可能是见面笔记、微信聊天记录、家长的回复，也可能是学校发来的录取通知（offer）、补材料邮件、面试邀请、拒信、候补通知，或者这些内容的截图、照片、PDF 里的文字。材料可能是中文，也可能是英文。\n你的任务只有一个：把材料里和申请事项有关的信息整理成 JSON，供顾问核对后写入系统。你不直接面对家长和学生，不要寒暄，不要给建议。\n\n【要找的四类信息】\n一、新事项 newItems：材料里明确提到、但“已有事项”里没有的待办。写清做什么（what）、谁负责（owner）、最晚哪天（due）、属于哪所学校（school，不属于某所学校就写 \"\"）。\n二、已有事项的进展 found：\n  - 家长或学生对某个已有事项表示知道了、同意、会去办：kind 写 \"replied\"，item 写那个事项的 id。\n  - 某个已有事项已经办完：kind 写 \"done\"，item 写那个事项的 id。\n  - 家长的回复和任何已有事项都对不上，但值得留个记录（比如“收到，谢谢老师”）：kind 写 \"note\"，item 写 null。\n三、学校来信 doc：材料是学校发给学生的正式通知时才填，否则 doc 写 null。\n  - type 只能是：offer（录取通知）、补材料、面试、拒信、候补、其他。\n  - school：学校名。“已报名学校”里有同一所学校时，照抄那里的写法；没有就照抄材料里的写法。\n  - program：专业或项目名，照抄材料，没有写 \"\"。\n  - result 只能是：有条件录取、无条件录取、拒绝、候补、\"\"（不是录取结果时写 \"\"）。\n  - conditions：录取条件或学校提出的要求，一条写一项。text 用中文简要概括（成绩、分数、科目、证书名照抄原文，不要换算），due 是这一条要求的最晚日期，quote 是原话。接受录取的截止日、开学日期、学费金额不算条件，不要写进 conditions。只写学生要达到的标准（成绩、语言分数、毕业、学位等），“请登录系统确认”“请回复”这类办手续的提醒不算条件。\n  - quote：材料里说明这是什么通知的那句原话。\n四、图片转写 transcript：有图片时，先把图片里和申请事项有关的文字逐字抄下来。\n\n【学校来信要生成哪些新事项】\n材料里写了日期的，才生成事项；没写日期的不要自己编，系统会另外提示顾问。事项名称一律用简体中文，学校用顾问平时的叫法（港大、港科大、剑桥、曼大）。\n- offer：接受录取的截止日 → “接受 XX 录取”（学生）；押金、留位费、学费首付的截止日 → “付 XX 留位费”（家长）；每一条带日期的录取条件 → “达到 XX 录取条件并提交成绩”或“提交 XX 语言成绩”等（学生）；要求补交文件的截止日 → “提交 XX 最终成绩单”等（学校或学生）。开学或报到日期写成“XX 开学报到”（学生）。\n- 补材料：每一份要补的材料一条事项，按材料归谁办来定负责人（成绩单、推荐信是学校；护照、资金证明是家长；作品集、问卷是学生）。\n- 面试：有回复或预约截止日 → “预约 XX 面试时间”（学生）；有面试日期 → “参加 XX 面试”（学生）。\n- 候补：要求在某天前回复是否留在候补名单 → “回复 XX 是否留在候补名单”（学生）。\n- 拒信：不生成事项，只填 doc。\n\n【规则】\n1. owner 只能是这四个词之一：学生、家长、学校、机构。“机构”指顾问或机构自己要做的事；“学校”指学生所在中学要做的事，比如成绩单、推荐信。\n2. due 写成 YYYY-MM-DD。材料里是“22 号”“下周一”“月底”这类说法时，按“今天”的日期推算；英文日期（March 31, 2025）直接换成这个格式，年份照材料写，不要改。材料里只给了一段时间范围、还没定具体哪天的（比如“面试在 9 日到 13 日之间”），due 也写 \"\"，让顾问定下来后自己填；“某天之前”这种截止日照常写那一天。材料里明明有这件事、但日期被遮住或看不清的（比如“If we do not hear from you by [看不清]”），事项照常生成，due 写 \"\"，让顾问对照原件填。材料里没有提到时间就写空字符串 \"\"，不要猜。\n3. 每一条都必须带 quote：从材料原文或你的 transcript 里一字不差复制的一小段原话，作为依据。原文是英文就复制英文，不要翻译，不要改写，不要把两句拼成一句。找不到原话依据的内容不要输出。\n4. 不要把已有事项重复当成新事项。闲聊、没有明确动作的话，不要整理成事项。\n5. what 用简短的动宾短语，不超过 20 个字，比如“付托福送分费”“接受港大录取”。\n6. found 里的 text 写家长或学生的原话，date 写这句话是哪天说的，材料里看不出来就写今天。\n7. 红线：不写、不改、不翻译、不评价任何文书、活动描述、推荐信的内容。材料里出现这些正文时直接跳过，transcript 里也不要抄。\n8. 有图片时，transcript 照抄图片里的文字，保留是谁说的（比如“家长：”“顾问：”），看不清的地方写 [看不清]。没有图片时 transcript 写 \"\"。\n9. 只输出一个 JSON 对象。不要输出解释，不要用 ``` 包起来。没有内容的数组写 []。\n\n【输出格式】\n{\"transcript\":\"\",\"doc\":null 或 {\"type\":\"\",\"school\":\"\",\"program\":\"\",\"result\":\"\",\"conditions\":[{\"text\":\"\",\"due\":\"\",\"quote\":\"\"}],\"quote\":\"\"},\"newItems\":[{\"what\":\"\",\"owner\":\"\",\"due\":\"\",\"school\":\"\",\"quote\":\"\"}],\"found\":[{\"kind\":\"replied 或 done 或 note\",\"item\":\"已有事项的 id，note 时写 null\",\"date\":\"YYYY-MM-DD\",\"text\":\"\",\"quote\":\"\"}]}\n\n【例子一：聊天记录】\n输入：\n今天：2026-11-12。学生：张同学；家长称呼：张妈妈。\n已报名学校：UCLA\n已有事项（id｜事项｜负责人｜截止）：\n17｜付 UC 申请费｜家长｜2026-11-19\n材料：\n<<<\n顾问：张妈妈，UC 申请费记得 19 号前付\n张妈妈：好的，明天就付。对了托福送分是不是也要弄？\n顾问：对，送分要 30 美元，您 22 号前付一下\n张妈妈：行，辛苦老师\n>>>\n输出：\n{\"transcript\":\"\",\"doc\":null,\"newItems\":[{\"what\":\"付托福送分费\",\"owner\":\"家长\",\"due\":\"2026-11-22\",\"school\":\"\",\"quote\":\"送分要 30 美元，您 22 号前付一下\"}],\"found\":[{\"kind\":\"replied\",\"item\":\"17\",\"date\":\"2026-11-12\",\"text\":\"好的，明天就付\",\"quote\":\"好的，明天就付\"},{\"kind\":\"note\",\"item\":null,\"date\":\"2026-11-12\",\"text\":\"行，辛苦老师\",\"quote\":\"行，辛苦老师\"}]}\n\n【例子二：录取通知】\n输入：\n今天：2027-03-22。学生：陈同学；家长称呼：陈爸爸。\n已报名学校：香港大学 HKU、UCL\n已有事项（id｜事项｜负责人｜截止）：\n（没有）\n材料：\n<<<\nTHE UNIVERSITY OF HONG KONG\nOffer of admission\nIt is my great pleasure to offer you admission to the University of Hong Kong. This is a conditional offer with details as set out below:\nProgramme 6729 - Bachelor of Science\nStart of teaching September 1, 2027\nThis offer is conditional upon your obtaining the following on or before August 17, 2027:\nA*AA or better in three GCE Advanced Level subjects, including A or better in Mathematics\nIf we do not hear from you by March 31, 2027, our offer will no longer be valid.\n>>>\n输出：\n{\"transcript\":\"\",\"doc\":{\"type\":\"offer\",\"school\":\"香港大学 HKU\",\"program\":\"6729 - Bachelor of Science\",\"result\":\"有条件录取\",\"conditions\":[{\"text\":\"三门 GCE A-Level 达到 A*AA 或以上，其中数学 A 或以上\",\"due\":\"2027-08-17\",\"quote\":\"A*AA or better in three GCE Advanced Level subjects, including A or better in Mathematics\"}],\"quote\":\"This is a conditional offer with details as set out below\"},\"newItems\":[{\"what\":\"接受港大录取\",\"owner\":\"学生\",\"due\":\"2027-03-31\",\"school\":\"香港大学 HKU\",\"quote\":\"If we do not hear from you by March 31, 2027, our offer will no longer be valid.\"},{\"what\":\"达到港大录取条件并提交成绩\",\"owner\":\"学生\",\"due\":\"2027-08-17\",\"school\":\"香港大学 HKU\",\"quote\":\"This offer is conditional upon your obtaining the following on or before August 17, 2027\"},{\"what\":\"港大开学报到\",\"owner\":\"学生\",\"due\":\"2027-09-01\",\"school\":\"香港大学 HKU\",\"quote\":\"Start of teaching September 1, 2027\"}],\"found\":[]}";
const USER_PROMPT = "今天：{today}。学生：{student}；家长称呼：{parent}。\n已报名学校：{schools}\n已有事项（id｜事项｜负责人｜截止）：\n{items}\n材料{imgnote}：\n<<<\n{text}\n>>>";
const DOC_KINDS = {offer:"录取通知", "补材料":"补材料通知", "面试":"面试通知", "拒信":"拒信", "候补":"候补通知", "其他":"学校来信"};
const DOC_RESULTS = ["有条件录取", "无条件录取", "拒绝", "候补", ""];
function aiCheck(out, text, open){       // 原话必须在原文里；负责人、日期、事项 id 必须合法
  const norm = s => String(s || "").replace(/\s+/g, ""), src = norm(text), ids = new Set(open.map(i => i.id));
  const okDate = s => { try { return /^\d{4}-\d{2}-\d{2}$/.test(s) && new Date(s + "T00:00:00Z").toISOString().slice(0, 10) === s; } catch(e){ return false; } };
  const res = {newItems: [], found: [], dropped: 0};
  for (const x of out.newItems || []){ const q = String(x.quote || "");
    if (!q || !src.includes(norm(q)) || !OWNERS.includes(x.owner) || !String(x.what || "").trim()){ res.dropped++; continue; }
    res.newItems.push({what: String(x.what).trim().slice(0, 120), owner: x.owner, due: okDate(x.due) ? x.due : "", school: String(x.school || "").trim().slice(0, 100), quote: q.slice(0, 300)}); }
  const d = out.doc; res.doc = null;
  if (d && typeof d === "object" && DOC_KINDS[d.type] && String(d.school || "").trim()){ const q = String(d.quote || "");
    if (q && src.includes(norm(q))){ const conds = [];                       // 学校来信也要有原话依据
      for (const x of d.conditions || []){ const cq = String((x || {}).quote || "");
        if (!cq || !src.includes(norm(cq)) || !String(x.text || "").trim()){ res.dropped++; continue; }
        conds.push({text: String(x.text).trim().slice(0, 200), due: okDate(x.due) ? x.due : "", quote: cq.slice(0, 300)}); }
      res.doc = {type: d.type, school: String(d.school).trim().slice(0, 100), program: String(d.program || "").trim().slice(0, 120), result: DOC_RESULTS.includes(d.result) ? d.result : "", conditions: conds.slice(0, 10), quote: q.slice(0, 300)}; }
    else res.dropped++; }
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
  sub("members", "members"); sub("students", "students"); sub("items", "items"); sub("logs", "logs"); sub("memory", "memory"); sub("outcomes", "outcomes");
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
