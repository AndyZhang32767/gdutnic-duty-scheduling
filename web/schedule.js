const admin = typeof document !== 'undefined' && document.body.dataset.admin === 'true';
const $ = id => document.getElementById(id);
const dayInput = () => $('day') || {value: today()};
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let member = null;
let items = [], editing = null, editingSpecial = null, setup = true, generation = 0, rules = null;
async function api(url, method='GET', body) {
  const r = await fetch(url, {method, headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined});
  const data = await r.json();
  if (!r.ok) { const error=new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请检查填写内容'); error.status=r.status; throw error; }
  return data;
}
function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text !== undefined)n.textContent=text; return n; }
function button(text, cls, fn) { const n=el('button','btn '+(cls==='delete'?'danger':cls==='secondary'?'tonal':cls||'primary'),text); n.type='button'; n.onclick=fn; return n; }
async function load() {
  if (admin && typeof window.loadOverview === 'function') { await window.loadOverview(); return; }
  const token=++generation;
  $('status').textContent='正在加载排班…';
  window.updateShiftTimeline([]);
  try {
    const data=await api('/api/schedules?day='+encodeURIComponent(dayInput().value));
    if(token !== generation)return;
    // Defence in depth for members even if an admin cookie is also present in the browser.
    const visible = admin ? data.items : data.items.filter(s => s.members.some(m => m.name === member?.username));
    items=visible; rules=data.rules; window.updateShiftTimeline(items); render(); $('status').textContent='';
  } catch(e) { if(token===generation){ $('shifts').replaceChildren(); $('status').textContent=e.message; if(!admin && e.status===401)await bootMember(); } }
}
function render() {
  $('shifts').replaceChildren();
  if(!items.length){const box=el('div','empty');box.append(el('h2','', '当天暂无排班'),el('p','',admin?'点击「新增班次」开始安排值班。':'管理员发布排班后，会显示在这里。'));$('shifts').append(box);}
  for(const s of items){
    const card=el('article','card'),top=el('div','shift-top'),info=el('div');
    info.append(el('div','time',s.start+' — '+s.end));
    top.append(info,el('span','badge',`${s.members.filter(m=>m.checked_at).length} / ${s.members.length} 已签到`));card.append(top);
    if(s.note)card.append(el('p','',s.note));
    const members=el('div','members');
    for(const m of s.members){
      // Checked members always read "已签到"; only the colour reflects late/absent.
      const label = m.checked_at ? '已签到' : m.status==='absent' ? '旷班' : '待签到';
      const tone = m.status ? ' '+m.status : '';
      const n=el('span','member'+tone+(m.checked_at?' checked':''),m.name+' · '+label);
      if(m.checked_at)n.title=new Date(m.checked_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
      members.append(n);
    }card.append(members);
    if(admin){const actions=el('div','actions');actions.append(button('编辑班次','secondary',()=>openEditor(s)),button('删除','delete',async()=>{
      if(!confirm('确认删除此班次及其签到记录？'))return;
      try{await api('/api/admin/schedules/'+s.id,'DELETE');await load();}catch(e){$('status').textContent=e.message;}
    }));card.append(actions);}else{
      const own = s.members.find(m=>m.name === member?.username);
      if (!own) { card.append(el('p','','此班次未安排你值班。')); $('shifts').append(card); continue; }
      if (own.checked_at) { card.append(el('p','', '你已于 '+new Date(own.checked_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' 签到。')); $('shifts').append(card); continue; }
      const form=el('form','check-form');
      const submit=el('button','btn primary','确认到岗签到');submit.type='submit';
      // Mirror the server window: check-in opens early_minutes before start and closes at end.
      const range=window.ShiftTimeline.interval(s);
      const window_ms={early:(rules?.early_minutes ?? 10)*60000, late:(rules?.late_minutes ?? 15)*60000, absent:(rules?.absent_minutes ?? 30)*60000};
      window.syncCheckInButton(submit, range, window_ms);
      form.dataset.shiftId=String(s.id);
      form.append(submit);form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const result=await api(`/api/schedules/${s.id}/check-in`,'POST');await load();$('status').textContent=result.chained?.length?`签到成功，已自动签到后续相连的 ${result.chained.length} 个班次。`:'签到成功，已记录到岗时间。';}catch(err){$('status').textContent=err.message;submit.disabled=false;}};card.append(form);
    }
    $('shifts').append(card);
  }
}
function openEditor(s){editing=s?s.id:null;editingSpecial=null;const f=$('shiftForm');f.reset();$('formStatus').textContent='';$('editorTitle').textContent=s?'编辑班次':'新增班次';for(const key of ['day','start','end','note'])f.elements[key].value=s?s[key]:(key==='day'?dayInput().value:'');f.elements.members.value=s?s.members.map(m=>m.name).join('\n'):'';$('editor').showModal();}
if($('day')){$('day').value=today();$('day').onchange=load;}if(admin){
  $('add').onclick=()=>openEditor(null);$('closeEditor').onclick=()=>$('editor').close();
  $('shiftForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('[type=submit]');const body=Object.fromEntries(new FormData(f));body.members=body.members.split(/[\n,，、]+/).map(n=>n.trim()).filter(Boolean);b.disabled=true;try{
  if(editingSpecial!==null){const saved=editingSpecial;await api('/api/admin/special-schedules'+(editingSpecial?'/'+editingSpecial:''),editingSpecial?'PUT':'POST',body);$('editor').close();await loadSpecials();$('specialStatus').textContent=saved?'特殊排班已更新。':'特殊排班已添加。';}
  else{await api('/api/admin/schedules'+(editing?'/'+editing:''),editing?'PUT':'POST',body);if($('day'))$('day').value=body.day;$('editor').close();await load();}
}catch(err){$('formStatus').textContent=err.message;}finally{b.disabled=false;}};
  $('authForm').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;$('authStatus').textContent='';$('authSubmit').disabled=true;try{await api('/api/admin/'+(setup?'login':'register'),'POST',Object.fromEntries(new FormData(form)));form.reset();await boot();}catch(err){$('authStatus').textContent=err.message;}finally{$('authSubmit').disabled=false;}};
  $('logout').onclick=async()=>{try{await api('/api/admin/logout','POST');await boot();}catch(e){$('status').textContent=e.message;}};
  async function boot(){try{const state=await api('/api/admin/status');setup=state.setup;
    // Older backends do not send `permissions`; treat that as full access rather than hiding every menu.
    window.adminPermissions = state.logged_in && Array.isArray(state.permissions) ? state.permissions : null;
    window.canEditStatus = !Array.isArray(window.adminPermissions) || window.adminPermissions.includes('schedule');
    window.canEditField = !Array.isArray(window.adminPermissions) || window.adminPermissions.includes('field');
    if (typeof window.applyPermissions === 'function') window.applyPermissions(window.adminPermissions);$('authTitle').textContent='管理员登录';$('authSubmit').textContent=setup?'登录':'注册首个管理员（获得全部权限）';document.body.classList.toggle('auth-pending',!state.logged_in);$('authCard').hidden=state.logged_in;$('workspace').hidden=!state.logged_in;$('logout').hidden=!state.logged_in;if(state.logged_in)await load();}catch(e){$('authStatus').textContent=e.message;}}
  boot();
}else bootMember();
if(!admin) setInterval(()=>{
  for(const form of document.querySelectorAll('#shifts .check-form')) {
    const button=form.querySelector('button[type=submit]'), shift=items.find(s=>String(s.id)===form.dataset.shiftId);
    if(button && shift) syncCheckInButton(button, window.ShiftTimeline.interval(shift), {
      early:(rules?.early_minutes ?? 10)*60000, late:(rules?.late_minutes ?? 15)*60000, absent:(rules?.absent_minutes ?? 30)*60000});
  }
}, 20000);

function on(id, helper) {
  const node = $(id);
  if (node) node[helper[0]] = helper[1];
  return !!node;
}

async function bootMember() {
  try {
    const state = await api('/api/member/status');
    member = state.logged_in ? state : null;
    document.body.classList.toggle('auth-pending', !member);
    if ($('memberAuth')) $('memberAuth').hidden = !!member;
    $('workspace').hidden = !member;
    if (member) { if ($('memberGreeting')) $('memberGreeting').textContent = member.username+'，欢迎回来'; await load(); }
    else { ++generation; items=[]; window.updateShiftTimeline([]); $('shifts').replaceChildren(); }
  } catch (err) { $('memberLoginStatus').textContent=err.message; }
}
if (!admin) {
  on('memberLoginForm', ['onsubmit', async e => {
    e.preventDefault(); const form=e.currentTarget, submit=form.querySelector('[type=submit]');
    submit.disabled=true; if ($('memberLoginStatus')) $('memberLoginStatus').textContent='';
    try { await api('/api/member/login','POST',Object.fromEntries(new FormData(form))); form.reset(); await bootMember(); }
    catch(err) { if ($('memberLoginStatus')) $('memberLoginStatus').textContent=err.message; }
    finally { submit.disabled=false; }
  }]);
  on('memberLogout', ['onclick', async () => {
    try { await api('/api/member/logout','POST'); await bootMember(); }
    catch(err) { if ($('status')) $('status').textContent=err.message; }
  }]);
  on('changePassword', ['onclick', () => {
    if (!$('passwordForm')) return;
    $('passwordForm').reset(); $('passwordStatus').textContent=''; $('passwordEditor').showModal();
  }]);
  on('closePassword', ['onclick', () => $('passwordEditor').close()]);
  $('passwordForm') && ($('passwordForm').onsubmit = async e => {
    e.preventDefault(); const form=e.currentTarget, submit=form.querySelector('[type=submit]'); submit.disabled=true;
    try { await api('/api/member/password','POST',Object.fromEntries(new FormData(form))); form.reset(); $('passwordEditor').close(); $('status').textContent='密码已更新。'; }
    catch(err) { $('passwordStatus').textContent=err.message; }
    finally { submit.disabled=false; }
  });
}
