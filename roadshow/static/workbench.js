/* A handoff is a change of assignment, never a stored narrative.
   Both the landing card and student detail project the current server snapshot. */
const hbtn = (act,label,attrs="") => '<button class="btn" data-act="'+act+'" '+attrs+'>'+label+'</button>';
async function refreshLanding() {
  if(!S || document.hidden) return;
  const initial=D;
  try {
    const snapshot=await call("/api/state");
    if(S.role==="c" && S.tab.c==="today" && D===initial && !document.activeElement?.matches("input,textarea,select") && JSON.stringify(snapshot)!==JSON.stringify(D)){
      D=snapshot; TODAY=D.today; render();
    }
  } catch (_) { /* keep the last confirmed state on a transient failure */ }
}
window.addEventListener("focus",()=>{if(S?.role==="c" && S.tab.c==="today") refreshLanding();});
setInterval(()=>{if(S?.role==="c" && S.tab.c==="today") refreshLanding();},15000);
function summaryCard(s) {
  const open = D.items.filter(i=>i.student===s.name && !i.done).sort((a,b)=>
    [a.due,a.follow?.review_on || a.due].sort()[0].localeCompare([b.due,b.follow?.review_on || b.due].sort()[0]) || a.id-b.id);
  const i=open[0], f=i?.follow;
  const log=D.logs.find(l=>l.student===s.name && !l.undone && l.src!=="交接");
  const row=(k,v)=>'<div><small>'+k+'</small><strong>'+esc(v)+'</strong></div>';
  return '<section class="card briefing"><div class="head"><b>'+esc(s.name)+' · 接手摘要</b><span class="chip green">按当前记录生成</span></div>'+
    '<div class="briefgrid">'+row("最近一次业务记录",log?.act || "尚无记录")+
    row("首要未结事项",i ? (i.school || "其他事项")+" · "+i.what+"（等"+i.owner+"）" : "无未结事项")+
    row("负责顾问 / 下一步",s.consultant+" · "+(!i?"无需跟进":f?"核对是否收到材料；未收到则联系"+i.owner:"跟进"+i.owner+"，确认"+i.what))+
    row("时间依据",i ? (f?"承诺 "+md(f.promised_on)+" / 复查 "+md(f.review_on)+" / ":"")+"事项截止 "+md(i.due) : "—")+
    '</div><small>未结 '+open.length+' 件 · '+hbtn("freshbrief","从服务器刷新")+'</small></section>';
}
function reviewCard(i) {
  const f=i.follow;
  return '<article class="card yellow"><div class="head"><b>'+esc(i.student)+' · '+esc(i.what)+'</b><span class="chip yellow">待核实，未完成</span></div>'+
    '<p>'+esc(i.owner)+'曾说：“'+esc(f.promise)+'”</p><p>复查 '+md(f.review_on)+' · 硬截止 '+md(i.due)+' · 负责顾问 '+esc(stu(i.student).consultant)+'</p>'+
    '<label>仍未收到，下次复查 <input type="date" id="rv'+i.id+'" value="'+(TODAY<i.due?addDays(TODAY,1):"")+'"></label> '+
    hbtn("review","已跟进，安排复查",'data-id="'+i.id+'"')+' '+hbtn("openitem","查看事项",'data-id="'+i.id+'"')+'</article>';
}
function workflowStudent(name) {
  const s=stu(name), items=D.items.filter(i=>i.student===name && isFam(i) && !i.done);
  const others=D.users.filter(u=>u.active && u.role==="consultant" && u.id!==s.consultant_id);
  return summaryCard(s)+'<details class="card fold" '+(S.workflowOpen?'open':'')+'><summary>记录承诺 / 移交学生</summary>'+
    (items.length?'<label>对应事项<select id="pvItem">'+items.map(i=>'<option value="'+i.id+'">'+esc(i.what)+'</option>').join("")+'</select></label>'+
    '<label>学生或家长承诺的原话<input type="text" maxlength="180" id="pvQuote" value="'+esc(S.samplePromise || "")+'" placeholder="例如：我今晚发给您"></label>'+
    '<div class="row"><label>承诺日 <input type="date" id="pvDay" value="'+TODAY+'"></label><label>顾问复查日 <input type="date" id="pvReview" value="'+addDays(TODAY,1)+'"></label>'+
    hbtn("promise","确认承诺，不记完成")+'</div>':'')+
    (others.length?'<div class="row"><label>把该学生及未结事项移交给 <select id="toUser">'+others.map(u=>'<option value="'+u.id+'">'+esc(u.name)+'</option>').join("")+'</select></label>'+
    hbtn("handoff","确认移交",'data-s="'+esc(name)+'"')+'</div>':'')+'</details>';
}
function workHeader(tab) {
  if(S.role!=="c") return "";
  let out="";
  if(D.demo) {
    const s=D.students.find(s=>s.name==="林同学"), i=D.items.find(i=>i.student===s?.name && !i.done);
    let title,action="";
    if(TODAY===D.demo.day2){title="次日接手 · 核对承诺是否兑现";}
    else if(D.demo.transferred){title="王老师已移交，切换到接手人的工作日";action=hbtn("tomorrow","进入次日 · 以陈老师接手");}
    else if(i?.follow){title="承诺已记录，移交前无需再写总结";action=hbtn("openWorkflow","去移交给陈老师");}
    else if(i){title="学生回复：我今晚把英文成绩单发给您。";action=hbtn("openWorkflow","核对并记录学生承诺");}
    else {title="招生办发来一封补件邮件";action=hbtn("demoMail","打开学校邮件");}
    out+='<section class="guide"><div><small>20W / 补件路演　·　虚构数据　·　离线样例</small><h2>'+title+'</h2>'+action+'</div>'+
      '<button class="btn ghost" data-act="resetDemo">一键重置案例</button></section>';
  }
  if(tab==="today"){
    const incoming=myStudents().filter(s=>s.handed && s.consultant_id===D.me.id);
    out+='<h2>今日跟进 <span class="cnt">'+todayCount()+'</span></h2>';
    out+=incoming.map(summaryCard).join("");
  }
  return out;
}
async function workflowAction(name,ds) {
  if(name==="freshbrief"){D=await call("/api/state"); TODAY=D.today;render();return true;}
  if(name==="resetDemo" || name==="tomorrow"){await call("/api/demo/"+(name==="resetDemo"?"reset":"tomorrow"),{}); location.assign("/"); return true;}
  if(name==="demoMail"){S.tab.c="capture";pickStudent("林同学");S.cap.text=D.demo.mail;render();return true;}
  if(name==="openWorkflow"){S.tab.c="student";S.workflowOpen=true;S.samplePromise=D.demo.promise;pickStudent("林同学");document.getElementById("pvQuote")?.scrollIntoView({block:"center"});return true;}
  if(name==="promise"){await api("promise",{item:+val("pvItem"),quote:val("pvQuote"),promised:val("pvDay"),review:val("pvReview")});S.samplePromise="";toast("已记录承诺；截止日和完成状态未变");return true;}
  if(name==="handoff"){await api("handoff",{student:stu(ds.s).id,to:+val("toUser")});S.tab.c="today";S.pick=null;render();toast("负责人已变更，接手方将看到最新摘要");return true;}
  if(name==="review"){await api("review",{item:+ds.id,review:val("rv"+ds.id)});toast("已安排下次复查");return true;}
  return false;
}
