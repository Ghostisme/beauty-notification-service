'use strict';

const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {csrf:'', page:'dashboard', templates:[], selectedTemplate:'new_order', enterprises:[], stores:[], config:{}, filter:{status:'',category:'',enterprise_id:'',keyword:'',page:1}, detail:null};
const titles = {dashboard:'运行概览',messages:'通知记录',stores:'企业与门店',templates:'通知模板',tasks:'自动任务',settings:'接入设置'};
const names = {new_order:'新订单通知',new_lead:'新留资通知',status_change:'状态变化通知'};
const statusNames = {pending:'待发送',sending:'发送中',waiting_receipt:'等待回执',sent:'已发送',failed:'发送失败',uncertain:'待人工核实',unrouted:'待分配门店',blocked:'已暂停',muted:'通知已关闭',skipped_old:'历史记录',canceled:'已取消',waiting_phone:'待补全手机号'};
const eventNames = {paid:'支付成功',verified:'核销成功',refunding:'退款申请',refunded:'退款成功',canceled:'订单取消'};
const fmt = n => n ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(n*1000)) : '—';
const number = n => new Intl.NumberFormat('zh-CN').format(n || 0);
const bytes = n => n > 1024**3 ? (n/1024**3).toFixed(1)+' GiB' : (n/1024**2).toFixed(1)+' MiB';
const checked = v => v ? ' checked' : '';
const selected = (a,b) => String(a)===String(b) ? ' selected' : '';
let toastTimer, refreshTimer, pageSequence = 0;

async function api(path, options = {}) {
  const headers = {...options.headers};
  if (options.body !== undefined) { headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body); }
  if (options.method && !['GET','HEAD'].includes(options.method)) headers['X-CSRF-Token']=state.csrf;
  const response = await fetch(path, {...options, headers, credentials:'same-origin'});
  const data = await response.json().catch(()=>({error:'服务响应格式不正确'}));
  if (!response.ok) {
    if (response.status===401 && path!=='/api/login') showLogin();
    throw new Error(data.error || '操作未完成，请重试');
  }
  return data;
}

function toast(message, error=false) {
  clearTimeout(toastTimer); const element=$('#toast'); element.textContent=message;
  element.className='toast'+(error?' error':''); element.hidden=false;
  toastTimer=setTimeout(()=>{element.hidden=true;},5000);
}
function badge(status) {
  const color = ['sent'].includes(status)?'green':['failed','uncertain'].includes(status)?'red':['unrouted','blocked','pending','waiting_phone'].includes(status)?'amber':['sending','waiting_receipt'].includes(status)?'blue':'gray';
  return `<span class="badge ${color}">${esc(statusNames[status]||status)}</span>`;
}
function switchInput(name, value, label) {
  return `<label class="switch"><input name="${esc(name)}" type="checkbox" aria-label="${esc(label)}"${checked(value)}><span class="switch-track"></span></label>`;
}
function heading(title, subtitle, actions='', kicker='STORE NOTIFICATIONS') {
  return (state.demo?'<div class="tip amber">当前为离线演示环境，使用示例数据，不连接抖音，也不执行企微发送。</div>':'')+`<div class="page-heading"><div><div class="page-kicker">${esc(kicker)}</div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function empty(title, subtitle='') {
  return `<div class="empty"><div class="empty-icon">▤</div><strong>${esc(title)}</strong><p>${esc(subtitle)}</p></div>`;
}
function showLogin() {
  clearInterval(refreshTimer); state.csrf=''; $('#app-view').hidden=true; $('#login-view').hidden=false;
  if ($('#modal').open) $('#modal').close();
}
function openModal(title, content) {
  $('#modal-title').textContent=title; $('#modal-content').innerHTML=content;
  if (!$('#modal').open) $('#modal').showModal();
}
function closeModal() { $('#modal').close(); state.detail=null; }
function formData(form) { return Object.fromEntries(new FormData(form)); }
async function loadEntities() {
  const results=await Promise.allSettled([api('/api/enterprises'),api('/api/stores')]);
  const failures=results.filter(r=>r.status==='rejected'); if(failures.length) throw failures[0].reason;
  state.enterprises=results[0].value.items; state.stores=results[1].value.items;
}
function enterpriseOptions(value='', emptyLabel='选择企业') {
  return `<option value="">${esc(emptyLabel)}</option>`+state.enterprises.filter(e=>!e.is_test).map(e=>`<option value="${e.id}"${selected(e.id,value)}>${esc(e.name)}</option>`).join('');
}
function storeOptions(value='', enterpriseId='', boundOnly=false, includeTest=false) {
  return '<option value="">选择门店</option>'+state.stores.filter(s=>(!s.is_test||includeTest)&&(!enterpriseId||String(s.enterprise_id)===String(enterpriseId))&&(!boundOnly||(s.enabled&&s.group_id&&s.group_name))).map(s=>`<option value="${s.id}"${selected(s.id,value)}>${esc(s.name)}${!s.group_id?'（未绑定群）':''}</option>`).join('');
}

async function navigate(page, quiet=false) {
  if (!titles[page]) page='dashboard';
  const sequence=++pageSequence; state.page=page;
  document.title=titles[page]+' · 来客门店通知'; $('#breadcrumb').textContent=titles[page];
  document.querySelectorAll('[data-page]').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  $('.sidebar').classList.remove('open');
  if (!quiet) $('#main-content').innerHTML='<div class="loading"><div class="spinner"></div><p>正在读取工作台…</p></div>';
  try {
    let html;
    if(page==='dashboard') html=await dashboardPage();
    if(page==='messages') html=await messagesPage();
    if(page==='stores') html=await storesPage();
    if(page==='templates') html=await templatesPage();
    if(page==='tasks') html=await tasksPage();
    if(page==='settings') html=await settingsPage();
    if(sequence!==pageSequence) return;
    $('#main-content').innerHTML=html;
    if(page==='templates') await previewTemplate(false);
  } catch(error) {
    if(sequence===pageSequence) {
      if(!quiet) $('#main-content').innerHTML=empty('暂时无法读取数据',error.message);
      toast(error.message,true);
    }
  }
}

function messageTable(items) {
  if(!items.length) return empty('还没有通知记录','添加企业和门店后，可先创建一条测试消息检查发送链路。');
  return `<div class="table-wrap"><table><thead><tr><th>通知 / 业务编号</th><th>企业与门店</th><th>接收群</th><th>发送状态</th><th>创建时间</th><th class="column-small">操作</th></tr></thead><tbody>${items.map(m=>`<tr><td><div class="cell-title">${esc(m.event_name||names[m.category])}${m.is_test?' <span class="badge gray">测试消息</span>':''}</div><div class="cell-sub mono">${esc(m.record_id)}</div></td><td><div class="cell-title">${esc(m.store_name||'待分配门店')}</div><div class="cell-sub">${esc(m.enterprise_name)}</div></td><td><div class="cell-title ellipsis" title="${esc(m.group_name)}">${esc(m.group_name||'尚未绑定')}</div></td><td>${badge(m.status)}${m.result_source==='manual'?'<div class="cell-sub">人工确认</div>':''}${m.status==='pending'&&m.next_attempt?'<div class="cell-sub">'+fmt(m.next_attempt)+' 后重试</div>':''}</td><td class="nowrap muted">${fmt(m.created_at)}</td><td><button class="text-button" data-detail="${m.id}">查看</button></td></tr>`).join('')}</tbody></table></div>`;
}
function runTable(runs) {
  if(!runs.length) return empty('还没有任务运行记录','填写抖音应用凭证后，点击“立即同步”或开启自动同步。');
  return `<div class="table-wrap"><table><thead><tr><th>开始时间</th><th>触发方式</th><th>结果</th><th>读取 / 入队</th><th>详情</th></tr></thead><tbody>${runs.map(r=>`<tr><td class="nowrap">${fmt(r.started_at)}</td><td>${r.trigger==='scheduled'?'自动任务':'手动触发'}</td><td><span class="badge ${r.status==='success'?'green':['failed','partial','interrupted'].includes(r.status)?'red':'blue'}">${esc({success:'已完成',failed:'失败',partial:'部分失败',running:'运行中',interrupted:'已中断'}[r.status]||r.status)}</span></td><td class="nowrap">${r.orders} / ${r.queued}</td><td><div class="run-details">${r.details.length?r.details.map(v=>`${esc(v.enterprise)}：${v.orders} 单，${v.queued} 条通知${v.error?'<br><span class="error-text">'+esc(v.error)+'</span>':v.warning?'<br>'+esc(v.warning):''}`).join('<br>'):'尚无已完成企业'}</div></td></tr>`).join('')}</tbody></table></div>`;
}

async function dashboardPage() {
  const results=await Promise.allSettled([api('/api/dashboard'),api('/api/messages?page_size=6')]);
  for(const r of results) if(r.status==='rejected') throw r.reason;
  const d=results[0].value, messages=results[1].value; const counts=d.counts;
  const attention=(counts.failed||0)+(counts.uncertain||0)+(counts.unrouted||0)+(counts.waiting_phone||0);
  const online=d.workers.find(w=>w.online&&w.ready);
  const worker=d.workers[0];
  $('#nav-count').textContent=number(attention); $('#nav-count').hidden=!attention;
  return heading('门店通知工作台','把每一条订单与留资，及时送达对应门店。',`<button data-action="test-message">＋ 测试消息</button><button class="primary" data-action="run-task"${d.sync_running?' disabled':''}>↻ ${d.sync_running?'正在同步':'立即同步'}</button>`,'工作概览 / OVERVIEW')+
  `<div class="stats-grid"><div class="stat-card"><div class="stat-top">待发送通知<span class="stat-icon">↗</span></div><div class="stat-value">${number(counts.pending)}</div><p class="stat-foot">${d.notifications.delivery_enabled?'发送已开启，按队列依次处理':'发送已暂停，消息保留在队列'}</p></div><div class="stat-card"><div class="stat-top">近 24 小时已发送<span class="stat-icon">✓</span></div><div class="stat-value">${number(d.sent_today)}</div><p class="stat-foot">含 ${number(d.manual_today)} 条人工核实记录</p></div><div class="stat-card"><div class="stat-top">需要人工介入<span class="stat-icon">!</span></div><div class="stat-value ${attention?'warning':''}">${number(attention)}</div><p class="stat-foot">失败 ${counts.failed||0} · 待核实 ${counts.uncertain||0} · 待分配 ${counts.unrouted||0} · 待补手机号 ${counts.waiting_phone||0}</p></div><div class="stat-card"><div class="stat-top">已接入门店<span class="stat-icon">▦</span></div><div class="stat-value">${number(d.stores)}</div><p class="stat-foot">分属 ${number(d.enterprises)} 家合作企业</p></div></div>
  <div class="overview-grid"><section class="panel"><div class="panel-head"><h2>自动任务</h2><span class="badge ${d.scheduler.enabled?'green':'gray'}">${d.scheduler.enabled?'运行中':'已暂停'}</span></div><div class="panel-body"><div class="operation-state"><div class="state-disc ${d.scheduler.enabled?'':'amber'}">◷</div><div><h3>${d.scheduler.enabled?'按计划同步抖音数据':'等待开启自动同步'}</h3><p>${d.scheduler.enabled?'每家企业独立同步，失败会保留游标。':'先配置企业授权，也可以手动执行一轮同步。'}</p></div></div><dl class="info-grid"><div><dt>同步频率</dt><dd>每 ${d.scheduler.interval_seconds/60} 分钟</dd></div><div><dt>上轮运行</dt><dd>${d.runs[0]?fmt(d.runs[0].started_at):'尚未运行'}</dd></div><div><dt>下轮计划</dt><dd>${d.scheduler.enabled?fmt(d.next_sync):'已暂停'}</dd></div></dl></div><div class="panel-note"><span>任务进度与错误会自动记录</span><button class="text-button small-button" data-page="tasks">管理任务 →</button></div></section>
  <section class="panel"><div class="panel-head"><h2>企微发送端</h2><span class="badge ${d.channel_mode==='http'?'blue':online?'green':'amber'}">${d.channel_mode==='http'?'HTTP 工具':online?'已连接':'待连接'}</span></div><div class="panel-body"><div class="operation-state"><div class="state-disc ${online?'':'amber'}">⇄</div><div><h3>${d.channel_mode==='http'?'通过已配置的发送工具投递':online?esc(online.label):'连接 Windows / Mac 企微发送端'}</h3><p>${d.channel_mode==='http'?'以发送工具的明确回执更新状态。':worker?esc(worker.detail||'等待发送端准备就绪。'):'在已登录企业微信的电脑启动发送端。'}</p></div></div><dl class="info-grid"><div><dt>消息发送</dt><dd>${d.notifications.delivery_enabled?'已开启':'已暂停'}</dd></div><div><dt>最近心跳</dt><dd>${worker?fmt(worker.last_seen):'尚未连接'}</dd></div><div><dt>等待回执</dt><dd>${number((counts.sending||0)+(counts.waiting_receipt||0))} 条</dd></div></dl></div><div class="panel-note"><span>发送结果不明的消息进入人工核实</span><button class="text-button small-button" data-page="settings">接入设置 →</button></div></section></div>
  <section class="panel"><div class="panel-head"><h2>最近通知</h2><button class="text-button small-button" data-page="messages">查看全部 →</button></div>${messageTable(messages.items)}<div class="panel-note"><span>只将发送端确认成功或人工核实的消息标记为已发送</span><span>每 10 秒刷新</span></div></section>
  <section class="panel section-gap"><div class="panel-head"><h2>最近同步任务</h2><span class="muted">数据占用 ${bytes(d.db_bytes)} · 已运行 ${Math.floor(d.uptime_seconds/60)} 分钟</span></div>${runTable(d.runs.slice(0,4))}</section>`;
}

async function messagesPage() {
  if(!state.enterprises.length) await loadEntities();
  const query=new URLSearchParams({...state.filter,page_size:20}); const result=await api('/api/messages?'+query);
  return heading('通知记录','查看发送结果，处理失败、未分配或需要核实的通知。',`<button data-action="manual-lead">＋ 录入留资</button><button data-action="refresh">↻ 刷新</button>`,'通知管理 / MESSAGES')+
  `<section class="panel"><form id="filter-form" class="filters"><input name="keyword" placeholder="搜索订单号、群名或消息内容" aria-label="搜索通知" value="${esc(state.filter.keyword)}"><select name="status" aria-label="发送状态"><option value="">全部状态</option>${Object.entries(statusNames).map(([k,v])=>`<option value="${k}"${selected(k,state.filter.status)}>${v}</option>`).join('')}</select><select name="category" aria-label="通知类型"><option value="">全部通知类型</option>${Object.entries(names).map(([k,v])=>`<option value="${k}"${selected(k,state.filter.category)}>${v}</option>`).join('')}</select><select name="enterprise_id" aria-label="企业">${enterpriseOptions(state.filter.enterprise_id,'全部企业')}</select><button class="soft" type="submit">筛选</button></form>${messageTable(result.items)}<div class="table-footer"><span>共 ${number(result.total)} 条通知</span><div class="pagination"><button data-pagination="${result.page-1}"${result.page<=1?' disabled':''}>上一页</button><span>${result.page} / ${Math.max(1,Math.ceil(result.total/result.page_size))}</span><button data-pagination="${result.page+1}"${result.page*result.page_size>=result.total?' disabled':''}>下一页</button></div></div></section>`;
}

async function storesPage() {
  await loadEntities();
  return heading('企业与门店','一家企业可以管理多家门店，每家门店绑定独立接收群。',`<button data-action="add-enterprise">＋ 添加企业</button><button class="primary" data-action="add-store">＋ 添加门店</button>`,'业务连接 / STORES')+
  `<div class="tip">按“商户账号 ID ＋ 门店 ID”分配通知。没有明确门店的数据保留为待分配，由你选择所属门店。</div>
  <section class="panel"><div class="panel-head"><h2>合作企业</h2><span class="muted">${state.enterprises.length} 家企业</span></div>${state.enterprises.length?`<div class="table-wrap"><table><thead><tr><th>企业名称</th><th>抖音商户账号 ID</th><th>门店数量</th><th>状态</th><th>最近同步</th><th>操作</th></tr></thead><tbody>${state.enterprises.map(e=>`<tr><td><div class="cell-title">${esc(e.name)}${e.is_test?' <span class="badge gray">测试专用</span>':''}</div>${e.last_error?`<div class="cell-sub" title="${esc(e.last_error)}">${esc(e.last_error)}</div>`:''}</td><td class="mono">${esc(e.is_test?'测试用途 · 不连接抖音':e.account_id)}</td><td>${e.stores_count}</td><td><span class="badge ${e.enabled?'green':'gray'}">${e.enabled?'已启用':'已暂停'}</span></td><td class="muted nowrap">${fmt(e.last_sync)}</td><td>${e.is_test?'<span class="muted">测试配置</span>':`<button class="text-button" data-edit-enterprise="${e.id}">编辑</button>`}</td></tr>`).join('')}</tbody></table></div>`:empty('先添加一家合作企业','商家需要在抖音来客授权你的服务商应用。')}</section>
  <section class="panel section-gap"><div class="panel-head"><h2>门店与接收群</h2><span class="muted">${state.stores.length} 家门店</span></div>${state.stores.length?`<div class="table-wrap"><table><thead><tr><th>门店</th><th>所属企业</th><th>抖音门店 ID</th><th>企微外部群</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.stores.map(s=>`<tr><td class="cell-title">${esc(s.name)}${s.is_test?' <span class="badge gray">测试专用</span>':''}</td><td>${esc(s.enterprise_name)}</td><td class="mono">${esc(s.is_test?'测试用途':s.poi_id)}</td><td><div class="cell-title">${esc(s.group_name||'尚未绑定')}</div><div class="cell-sub mono">${esc(s.group_id||'请完善群绑定')}</div></td><td><span class="badge ${s.enabled&&s.group_id?'green':s.enabled?'amber':'gray'}">${s.enabled?s.group_id?'已启用':'待绑定':'已暂停'}</span></td><td>${s.is_test?'<span class="muted">专用测试群</span>':`<button class="text-button" data-edit-store="${s.id}">编辑</button>`}</td></tr>`).join('')}</tbody></table></div>`:empty('还没有门店','添加门店并绑定企微外部群，系统才能准确分发通知。')}</section>`;
}

async function templatesPage() {
  const result=await api('/api/templates'); state.templates=result.items;
  const template=state.templates.find(t=>t.kind===state.selectedTemplate)||state.templates[0]; state.selectedTemplate=template.kind;
  return heading('通知模板','统一消息格式，按通知类型分别启停和调整内容。','','内容设置 / TEMPLATES')+
  `<div class="template-tabs">${Object.entries(names).map(([k,v])=>`<button data-template="${k}" class="${k===template.kind?'active':''}">${v}</button>`).join('')}</div><div class="split-layout"><section class="panel form-panel"><form id="template-form"><div class="switch-row"><div><h3>${esc(template.name)}</h3><p>关闭后保留业务记录，不自动投递。</p></div>${switchInput('enabled',template.enabled,'启用当前通知')}</div><label>消息模板<textarea id="template-body" name="body" class="template-editor" spellcheck="false" required>${esc(template.body)}</textarea></label><div class="subtitle">点击变量插入到光标位置</div><div class="variable-list">${result.variables.map(v=>`<button type="button" data-variable="${esc(v)}">${esc(v)}</button>`).join('')}</div><label>字段缺失时<select name="missing"><option value="omit"${selected(template.missing,'omit')}>隐藏缺失字段所在行</option><option value="placeholder"${selected(template.missing,'placeholder')}>显示“未提供”</option></select></label><div class="form-actions"><button class="primary" type="submit">保存模板</button><button type="button" data-action="preview-template">刷新预览</button></div></form></section><section class="panel form-panel"><h2>消息预览</h2><p>以下使用示例数据，预览不会发送到门店群。</p><div class="phone-preview"><div class="preview-top">玥笙-辽宁-大连中山店</div><div class="preview-time">示例消息</div><div class="preview-chat"><div class="preview-avatar">来</div><div id="template-preview" class="preview-bubble">正在生成预览…</div></div></div>${template.kind==='status_change'?'<p class="subtitle">需要通知的状态事件在“自动任务”中单独勾选。</p>':''}</section></div>`;
}
async function previewTemplate(showToast=true) {
  const form=$('#template-form'); if(!form) return;
  try {
    const data=formData(form); const result=await api('/api/templates/preview',{method:'POST',body:{body:data.body,missing:data.missing}});
    $('#template-preview').textContent=result.text; if(showToast) toast('预览已更新，未发送消息');
  } catch(e) { toast(e.message,true); }
}

async function tasksPage() {
  const result=await api('/api/config'); state.config=result; const tasks=await api('/api/tasks'); const c=result.scheduler,n=result.notifications;
  return heading('自动任务','分别控制数据同步与消息发送，随时暂停或手动运行。',`<button class="primary" data-action="run-task"${tasks.running?' disabled':''}>↻ ${tasks.running?'正在同步':'立即同步一轮'}</button>`,'运行设置 / AUTOMATION')+
  `<div class="task-split"><section class="panel form-panel"><h2>数据同步计划</h2><p>按企业依次拉取新增或变化的订单，成功后推进各自的同步游标。</p><form id="scheduler-form"><div class="switch-row"><div><h3>自动同步</h3><p>关闭时仍可手动执行同步。</p></div>${switchInput('enabled',c.enabled,'开启自动同步')}</div><div class="form-grid"><label>同步间隔（分钟）<input name="interval_minutes" type="number" min="0.5" max="1440" step="0.5" value="${c.interval_seconds/60}" required></label><label>首次回看（分钟）<input name="lookback_minutes" type="number" min="5" max="10080" value="${c.lookback_minutes}" required></label><label>新消息有效期（分钟）<input name="max_age_minutes" type="number" min="1" max="10080" value="${c.max_age_minutes}" required><small>超过有效期的历史数据只保存记录。</small></label><label>每企业最多查询页数<input name="max_pages" type="number" min="1" max="1000" value="${c.max_pages}" required></label><label>通知记录保留（天）<input name="history_days" type="number" min="7" max="3650" value="${c.history_days}" required></label></div><button class="primary" type="submit">保存同步计划</button></form></section>
  <section class="panel form-panel"><h2>通知发送规则</h2><p>三类通知的模板开关在“通知模板”中配置。</p><form id="notifications-form"><div class="switch-row"><div><h3>自动发送消息</h3><p>暂停时通知继续入队，等待重新开启发送。</p></div>${switchInput('delivery_enabled',n.delivery_enabled,'开启自动发送')}</div><label class="check-label"><input name="require_full_phone" type="checkbox"${checked(n.require_full_phone)}>必须取得完整手机号后才能发送</label><p class="subtitle">缺少完整号码的通知进入“待补全手机号”，线索到达后自动补全，也可在通知详情手动补录。</p><label>新订单通知触发条件<select name="order_trigger"><option value="paid"${selected(n.order_trigger,'paid')}>支付成功后通知</option><option value="created"${selected(n.order_trigger,'created')}>订单创建后通知</option></select><small>选择支付成功后通知时，同一次支付不会再重复触发支付状态通知。</small></label><div class="subtitle">需要启用的状态变化通知</div><div class="check-grid">${Object.entries(eventNames).map(([key,name])=>`<label class="check-label"><input type="checkbox" name="status_events" value="${key}"${checked(n.status_events.includes(key))}>${name}</label>`).join('')}</div><details class="details"><summary>券状态码映射（按实际接口校准）</summary><div class="form-grid"><label>已核销状态码<input name="verified_statuses" value="${esc(n.verified_statuses.join(','))}"></label><label>已退款状态码<input name="refunded_statuses" value="${esc(n.refunded_statuses.join(','))}"></label><label>退款中状态码<input name="refunding_statuses" value="${esc(n.refunding_statuses.join(','))}"></label></div></details><div class="form-actions"><button class="primary" type="submit">保存通知规则</button></div></form></section></div>
  <section class="panel section-gap"><div class="panel-head"><h2>任务运行记录</h2><span class="muted">显示最近 50 轮</span></div>${runTable(tasks.items)}</section>`;
}

function connectionPanel(report) {
  const labels={ready:'已就绪',failed:'检查失败',unverified:'待验证',unconfigured:'待接入',partial:'部分就绪',paused:'已暂停',blocked:'不可用'};
  return `<section class="panel connection-panel"><div class="panel-head"><h2>真实接入检查</h2><button class="text-button small-button" data-action="refresh">刷新检查状态</button></div><div class="connection-note">应用凭证、商家授权和发送结果分别验证。填写配置只代表已保存；测试记录和人工确认不会计入实际业务自动发送证明。</div><div class="table-wrap"><table><thead><tr><th>环节</th><th>状态</th><th>实际检查结果</th><th>操作</th></tr></thead><tbody>${report.items.map(item=>`<tr><td class="nowrap">${esc(item.name)}</td><td><span class="badge ${item.state==='ready'?'green':item.state==='failed'?'red':'amber'}">${labels[item.state]||esc(item.state)}</span></td><td><div class="connection-detail">${esc(item.detail)}</div>${item.checked_at?`<div class="cell-sub">最近验证：${fmt(item.checked_at)}</div>`:''}</td><td>${item.check_enterprise_id!==undefined?`<button class="text-button" data-check-douyin="${item.check_enterprise_id}"${report.demo?' disabled':''}>${item.check_enterprise_id?'验证订单权限':'验证应用凭证'}</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
}

async function settingsPage() {
  const results=await Promise.allSettled([api('/api/config'),api('/api/connections')]);
  for(const result of results) if(result.status==='rejected') throw result.reason;
  const c=results[0].value; state.config=c;
  return heading('接入设置','连接抖音服务商应用，将通知发送到门店企微外部客户群。','','连接管理 / CONNECTIONS')+
  connectionPanel(results[1].value)+`<div class="split-layout"><div class="settings-stack"><section class="panel form-panel"><h2>抖音来客服务商应用</h2><p>每家合作企业需要单独授权该应用。</p><form id="douyin-form"><label>Client Key<input name="client_key" value="${esc(c.douyin.client_key)}" autocomplete="off"></label><label>Client Secret <span class="token-status">${c.douyin.secret_configured?'已保存':'尚未配置'}</span><input name="client_secret" type="password" placeholder="${c.douyin.secret_configured?'留空保留原凭证':'填写应用密钥'}" autocomplete="new-password"></label><label>金额单位<select name="amount_unit"><option value="fen"${selected(c.douyin.amount_unit,'fen')}>分（收到 9900，显示 ¥99.00）</option><option value="yuan"${selected(c.douyin.amount_unit,'yuan')}>元（收到 99，显示 ¥99.00）</option></select></label><label class="check-label"><input name="decrypt_enabled" type="checkbox"${checked(c.douyin.decrypt_enabled)}>启用平台手机号批量解密能力</label><label class="check-label"><input name="clue_enabled" type="checkbox"${checked(c.douyin.clue_enabled)}>同步抖音客资中心线索并补全订单手机号</label><label>首次线索回看（天）<input name="clue_lookback_days" type="number" min="1" max="730" value="${c.douyin.clue_lookback_days}" required><small>线索约延迟十分钟落入；完整解密使用平台额度，打码结果不算完整号码。</small></label><details class="details"><summary>接口地址设置</summary><label>开放平台地址<input name="base_url" value="${esc(c.douyin.base_url)}"></label><label>订单查询路径<input name="order_path" value="${esc(c.douyin.order_path)}"></label><label>线索查询路径<input name="clue_path" value="${esc(c.douyin.clue_path)}"></label><label>批量解密路径<input name="decrypt_path" value="${esc(c.douyin.decrypt_path)}"></label></details><div class="form-actions"><button class="primary" type="submit">保存抖音设置</button></div></form></section>
  <section class="panel form-panel"><h2>独立留资数据接入</h2><p>开启客资中心线索同步后，系统自动生成新留资通知。也支持接入其他上游或手工录入；以独立线索编号去重。</p><div class="subtitle">接收地址：<span class="inline-code">POST /api/ingest</span></div><div class="form-actions"><button data-token="ingest">查看留资接入令牌</button><button data-action="manual-lead" class="soft">手工录入留资</button></div><div id="token-ingest"></div><p class="details">上游需提供商户账号、留资编号、门店 ID 和留资内容。完整格式见随程序交付的接入说明。</p></section></div>
  <div class="settings-stack"><section class="panel form-panel"><h2>企微外部客户群发送</h2><p>接收群为包含外部联系人的企微客户群。按单自动发送由已入群的企微账号通过 Windows / Mac 客户端完成；使用其他发送工具时，需先验证它能向目标外部客户群发送。</p><form id="channel-form"><label>发送方式<select name="mode"><option value="relay"${selected(c.channel.mode,'relay')}>Windows / Mac 企微客户端（外部客户群）</option><option value="http"${selected(c.channel.mode,'http')}>已有外部群发送工具的 HTTP 接口</option></select></label><p id="relay-help" class="subtitle"${c.channel.mode==='http'?' hidden':''}>桌面发送端无需填写 HTTP 接口；使用下方的服务器地址和发送端接入令牌连接。</p><div id="http-fields"${c.channel.mode==='relay'?' hidden':''}><label>HTTP 发送地址<input name="http_url" value="${esc(c.channel.http_url)}" placeholder="https://发送工具地址/send"><small>使用 Windows / Mac 发送端时可留空。</small></label><label>HTTP 接入令牌 <span class="token-status">${c.channel.token_configured?'已保存':'尚未配置'}</span><input name="http_token" type="password" autocomplete="new-password" placeholder="留空保留原令牌"></label></div><div class="form-grid"><label>消息间隔（秒）<input name="interval_seconds" type="number" min="1" max="300" value="${c.channel.interval_seconds}"></label><label>失败最多尝试<input name="max_attempts" type="number" min="1" max="10" value="${c.channel.max_attempts}"></label><label>请求超时（秒）<input name="timeout_seconds" type="number" min="5" max="60" value="${c.channel.timeout_seconds}"></label><label>回执等待（秒）<input name="lease_seconds" type="number" min="60" max="900" value="${c.channel.lease_seconds}"></label></div><button class="primary" type="submit">保存发送设置</button></form></section>
  <section class="panel form-panel"><h2>Windows / Mac 发送端连接</h2><label>发送端服务器地址<input readonly aria-label="发送端服务器地址" value="${esc(location.origin)}"><small>发送端和后台在当前这台电脑时，可使用此本机地址。</small></label><p class="subtitle">下方令牌由本工具提供，复制到发送电脑的连接配置中。</p><div class="step"><span class="step-number">1</span><div><h3>在常开电脑登录企业微信</h3><p>发送账号需要加入相应门店的外部客户群，桌面保持可交互。</p></div></div><div class="step"><span class="step-number">2</span><div><h3>配置连接并校准界面</h3><p>Windows 双击 start-test-sender.bat；Mac 双击 start-test-sender.command。Mac 需允许屏幕录制和辅助功能，再校准搜索区、群标题及输入框。</p></div></div><div class="step"><span class="step-number">3</span><div><h3>先验证测试群，再开启自动发送</h3><p>发送端精确核对群名，发送后回报群内消息的确认结果。</p></div></div><button data-token="relay">查看发送端接入令牌</button><div id="token-relay"></div></section></div></div>`;
}

function enterpriseModal(id) {
  const e=state.enterprises.find(v=>v.id===id)||{enabled:true};
  openModal(id?'编辑合作企业':'添加合作企业',`<form id="enterprise-form" data-id="${id||''}"><label>企业名称<input name="name" value="${esc(e.name||'')}" maxlength="150" required></label><label>抖音商户账号 ID<input name="account_id" value="${esc(e.account_id||'')}"${id?' readonly':''} required><small>使用抖音来客商户根账户 ID，完整保留数字。</small></label><label class="check-label"><input name="enabled" type="checkbox"${checked(e.enabled)}>启用该企业</label><div class="form-actions"><button class="primary" type="submit">保存企业</button><button type="button" data-action="close-modal">取消</button></div></form>`);
}
function storeModal(id) {
  if(!state.enterprises.length) {toast('请先添加一家合作企业',true);return;}
  const s=state.stores.find(v=>v.id===id)||{enabled:true,group_id:'wecom-'+crypto.randomUUID()};
  openModal(id?'编辑门店与接收群':'添加门店',`<form id="store-form" data-id="${id||''}"><label>所属企业<select name="enterprise_id"${id?' disabled':''} required>${enterpriseOptions(s.enterprise_id)}</select>${id?`<input type="hidden" name="enterprise_id" value="${s.enterprise_id}">`:''}</label><div class="form-grid"><label>门店名称<input name="name" value="${esc(s.name||'')}" required></label><label>抖音门店 ID<input name="poi_id" value="${esc(s.poi_id||'')}"${id?' readonly':''} required></label></div><label>企微外部客户群名称<input name="group_name" value="${esc(s.group_name||'')}" placeholder="例如：玥笙-辽宁-大连中山店"><small>填写目标外部客户群的完整且唯一群名，发送账号需已加入该群。</small></label><label>接收群 ID<input name="group_id" value="${esc(s.group_id||'')}"><small>桌面模式保留本工具生成的群标识，按完整群名定位；连接现有工具时填写该工具提供的外部群标识。</small></label><label class="check-label"><input name="enabled" type="checkbox"${checked(s.enabled)}>启用该门店</label><div class="form-actions"><button class="primary" type="submit">保存门店</button><button type="button" data-action="close-modal">取消</button></div></form>`);
}
async function detailModal(id) {
  await loadEntities(); const d=await api('/api/messages/'+id); state.detail=d;
  const editable=!['sent','canceled','sending','waiting_receipt'].includes(d.status);
  const attention=d.status==='uncertain'?'<div class="warning-box">发送结果尚未确认。请先检查对应群内是否已有这条消息，再选择“人工确认已发送”或重试。</div>':'';
  openModal('通知详情 · #'+d.id,`<div class="actions">${badge(d.status)}<span class="subtitle">${esc(d.event_name)}${d.is_test?' · 测试消息':''}</span></div>${attention}<dl class="detail-grid"><div><dt>所属企业</dt><dd>${esc(d.enterprise_name)}</dd></div><div><dt>业务编号</dt><dd class="mono">${esc(d.record_id)}</dd></div>${d.payload.order_id?`<div><dt>关联订单</dt><dd class="mono">${esc(d.payload.order_id)}</dd></div>`:""}<div><dt>接收群</dt><dd>${esc(d.group_name||'待分配')}</dd></div><div><dt>创建时间</dt><dd>${fmt(d.created_at)}</dd></div><div><dt>尝试次数</dt><dd>${d.attempts} 次</dd></div><div><dt>发送确认</dt><dd>${d.status==='sent'?`${fmt(d.sent_at)} · ${d.result_source==='manual'?'人工核实':'发送端回执'}`:'尚未确认成功'}</dd></div></dl>${d.last_error?`<div class="warning-box">${esc(d.last_error)}</div>`:''}<h3>消息内容</h3>${editable?`<textarea id="message-body" spellcheck="false">${esc(d.body)}</textarea><button class="text-button small-button" data-message-action="edit">保存内容修改</button>`:`<div class="message-preview">${esc(d.body)}</div>`}${editable?`<label class="section-gap">重新分配到本企业门店<select id="route-store">${storeOptions(d.store_id,d.enterprise_id,true,!!d.is_test)}</select></label><button data-message-action="route" class="small-button">分配并加入待发队列</button>`:''}<div class="section-gap"><h3>发送尝试</h3>${d.attempt_history.length?d.attempt_history.map(a=>`<div class="attempt-item"><strong>第 ${a.number} 次 · ${esc({sent:'已确认发送',failed:'确认发送失败',uncertain:'结果待核实',sending:'发送中',waiting_receipt:'等待回执'}[a.outcome]||a.outcome)}</strong><p>${fmt(a.started_at)}${a.detail?' · '+esc(a.detail):''}</p></div>`).join(''):'<p class="subtitle">还没有发送尝试。</p>'}</div>${editable?`<details class="details"><summary>补全客户手机号（${({full:'完整号码',masked:'打码号码',missing:'未取得',ambiguous:'号码冲突'})[d.payload.phone_state]||'未取得'}）</summary><label>完整手机号<input id="contact-phone" inputmode="tel" autocomplete="off" placeholder="填写可联系客户的完整手机号"></label><label>号码来源说明<input id="contact-note" placeholder="例如：门店已核对的预约登记"></label><button data-message-action="contact">保存手机号并更新通知</button></details>`:''}<div class="modal-actions">${editable?'<button class="primary" data-message-action="retry">重新加入发送队列</button>':''}${!['sent','sending','waiting_receipt'].includes(d.status)?'<button data-action="mark-sent-form">人工确认已发送</button>':''}${!['sent','sending','waiting_receipt','canceled'].includes(d.status)?'<button class="danger" data-message-action="cancel">取消通知</button>':''}<button data-action="close-modal">关闭</button></div>`);
}
async function leadModal() {
  await loadEntities(); if(!state.enterprises.length){toast('请先添加企业和门店',true);return;}
  openModal('手工录入留资',`<form id="lead-form"><div class="form-grid"><label>所属企业<select name="enterprise_id" id="lead-enterprise" required>${enterpriseOptions()}</select></label><label>所属门店<select name="store_id" id="lead-store" required>${storeOptions()}</select></label><label>客户称呼<input name="customer" required></label><label>联系电话<input name="phone" inputmode="tel" maxlength="35"></label><label>意向项目<input name="intent"></label><label>留资编号<input name="record_id" value="MANUAL-${Date.now()}" required></label></div><label>客户备注<textarea name="remark" rows="3"></textarea></label><div class="form-actions"><button class="primary" type="submit">保存并生成通知</button><button type="button" data-action="close-modal">取消</button></div></form>`);
}
async function testModal() {
  const profile=await api('/api/test-group');
  if(profile.real_store_binding) {
    openModal('测试群已绑定真实门店',`<p>接收群：<strong>${esc(profile.group_name)}</strong></p><p>该群已经绑定 ${esc(profile.real_store_binding.enterprise_name)} 的 ${esc(profile.real_store_binding.name)}。</p><p class="subtitle">当前使用真实商户和门店 ID。请先在接入设置验证订单权限，再同步真实订单；无需创建模拟企业或替换现有绑定。</p><div class="form-actions"><button class="primary" data-action="open-live-connections">查看真实接入状态</button><button data-action="close-modal">关闭</button></div>`);
    return;
  }
  if(!profile.configured) {
    openModal('配置专用测试群',`<p>测试接收群：<strong>${esc(profile.group_name)}</strong></p><p class="subtitle">配置后可以测试新订单、新留资和状态变化通知，使用模拟数据，无需填写真实抖音商户或门店 ID。</p><div class="form-actions"><button class="primary" data-action="prepare-test-group">配置此测试群</button><button data-action="close-modal">取消</button></div>`);
    return;
  }
  openModal('创建发送链路测试',`<form id="test-form"><input type="hidden" name="store_id" value="${profile.store.id}"><div class="tip">专用测试群：<strong>${esc(profile.group_name)}</strong></div><p class="subtitle">正文会标记“发送链路测试｜模拟数据”，不使用真实客户资料。自动发送暂停时，消息保留在待发队列。</p><label>测试通知类型<select name="category"><option value="new_order">新订单通知</option><option value="new_lead">新留资通知</option><option value="status_change">状态变化通知（模拟核销）</option></select></label><div class="form-actions"><button class="primary" type="submit">创建测试消息</button><button type="button" data-action="close-modal">取消</button></div></form>`);
}
function passwordModal() {
  openModal('修改管理员密码',`<form id="password-form"><label>当前密码<input name="current_password" type="password" autocomplete="current-password" required></label><label>新密码<input name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="200" required><small>至少 12 个字符。</small></label><div class="form-actions"><button class="primary" type="submit">保存并重新登录</button><button type="button" data-action="close-modal">取消</button></div></form>`);
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('button'); if(!button||button.disabled)return;
  try {
    if(button.dataset.page) {location.hash=button.dataset.page;return;}
    if(button.dataset.detail) {await detailModal(Number(button.dataset.detail));return;}
    if(button.dataset.pagination) {state.filter.page=Number(button.dataset.pagination);await navigate('messages',true);return;}
    if(button.dataset.editEnterprise) {enterpriseModal(Number(button.dataset.editEnterprise));return;}
    if(button.dataset.editStore) {storeModal(Number(button.dataset.editStore));return;}
    if(button.dataset.template) {state.selectedTemplate=button.dataset.template;await navigate('templates',true);return;}
    if(button.dataset.variable) {const editor=$('#template-body');const value='{'+button.dataset.variable+'}';editor.setRangeText(value,editor.selectionStart,editor.selectionEnd,'end');editor.focus();return;}
    if(button.dataset.checkDouyin!==undefined) {
      button.disabled=true;button.textContent='正在检查…';
      try {
        const enterprise=Number(button.dataset.checkDouyin);
        const result=await api('/api/connections/douyin/check',{method:'POST',body:enterprise?{enterprise_id:enterprise}:{}});
        if(state.page==='settings')await navigate('settings',true);
        toast(result.detail,result.state==='failed');
      } finally {button.disabled=false;}
      return;
    }
    if(button.dataset.token) {
      const name=button.dataset.token; const result=await api('/api/connection-token/'+name,{method:'POST',body:{}});
      $('#token-'+name).innerHTML=`<textarea class="connection-token" readonly aria-label="接入令牌">${esc(result.token)}</textarea><button class="text-button small-button" data-copy-token="${name}">复制令牌</button>`;return;
    }
    if(button.dataset.copyToken) {await navigator.clipboard.writeText($('#token-'+button.dataset.copyToken+' textarea').value);toast('已复制接入令牌');return;}
    if(button.dataset.messageAction) {
      const action=button.dataset.messageAction,d=state.detail;
      if(action==='cancel'&&!confirm('取消这条尚未发送的通知？'))return;
      const data={version:d.version};
      if(action==='edit')data.body=$('#message-body').value;
      if(action==='contact'){data.phone=$('#contact-phone').value;data.note=$('#contact-note').value;}
      if(action==='route')data.store_id=Number($('#route-store').value);
      if(action==='mark_sent')data.note=$('#manual-sent-note').value;
      if(['retry','route'].includes(action)&&d.status==='uncertain') {
        if(!$('#not-sent-note')) {
          $('.modal-actions').insertAdjacentHTML('beforebegin','<label class="section-gap">核实未发送的说明<input id="not-sent-note" placeholder="先确认群内没有收到，再填写核实情况"></label>');
          $('#not-sent-note').focus();toast('请先检查群内消息并填写核实说明，再点击补发',true);return;
        }
        data.note=$('#not-sent-note').value.trim();if(!data.note){toast('请填写未发送的核实说明',true);return;}
      }
      await api(`/api/messages/${d.id}/${action}`,{method:'POST',body:data});
      toast(action==='route'?'已分配门店并加入队列':action==='edit'?'消息内容已保存':'通知处理已保存');
      await detailModal(d.id);return;
    }
    const action=button.dataset.action;
    if(action==='refresh')await navigate(state.page,true);
    if(action==='close-modal')closeModal();
    if(action==='open-live-connections') {closeModal();location.hash='settings';}
    if(action==='add-enterprise')enterpriseModal();
    if(action==='add-store')storeModal();
    if(action==='manual-lead')await leadModal();
    if(action==='test-message')await testModal();
    if(action==='prepare-test-group') {await api('/api/test-group',{method:'POST',body:{}});await testModal();toast('专用测试群已配置');}
    if(action==='preview-template')await previewTemplate();
    if(action==='run-task') {button.disabled=true;await api('/api/tasks/run',{method:'POST',body:{}});toast('同步任务已启动，运行结果会显示在任务记录中');setTimeout(()=>navigate(state.page,true),700);}
    if(action==='mark-sent-form') {
      if(!$('#manual-sent-note'))$('.modal-actions').insertAdjacentHTML('beforebegin','<label class="section-gap">人工核实说明<input id="manual-sent-note" placeholder="例如：已在对应门店群确认收到该消息" required></label><button class="soft" data-message-action="mark_sent">保存人工确认</button>');
      $('#manual-sent-note').focus();
    }
  } catch(error) {toast(error.message,true);}
});

document.addEventListener('change',event=>{
  if(event.target.id==='lead-enterprise')$('#lead-store').innerHTML=storeOptions('',event.target.value);
  if(event.target.matches('#channel-form select[name=mode]')) {
    const http=event.target.value==='http';$('#http-fields').hidden=!http;$('#relay-help').hidden=http;
  }
});

document.addEventListener('submit',async event=>{
  const form=event.target;event.preventDefault();
  const submit=form.querySelector('button[type="submit"]');if(submit)submit.disabled=true;
  try {
    const data=formData(form);
    if(form.id==='login-form') {
      $('#login-error').textContent='';const result=await api('/api/login',{method:'POST',body:data});state.csrf=result.csrf;await startApp();return;
    }
    if(form.id==='filter-form') {state.filter={...data,page:1};await navigate('messages',true);return;}
    if(form.id==='enterprise-form') {data.enabled=form.elements.enabled.checked;const id=form.dataset.id;await api('/api/enterprises'+(id?'/'+id:''),{method:id?'PUT':'POST',body:data});closeModal();toast('企业已保存');await navigate('stores',true);}
    if(form.id==='store-form') {data.enabled=form.elements.enabled.checked;data.enterprise_id=Number(data.enterprise_id);const id=form.dataset.id;await api('/api/stores'+(id?'/'+id:''),{method:id?'PUT':'POST',body:data});closeModal();toast('门店与群绑定已保存');await navigate('stores',true);}
    if(form.id==='template-form') {data.enabled=form.elements.enabled.checked;await api('/api/templates/'+state.selectedTemplate,{method:'PUT',body:data});toast('通知模板已保存');await previewTemplate(false);}
    if(form.id==='scheduler-form') {const payload={...data,enabled:form.elements.enabled.checked,interval_seconds:Number(data.interval_minutes)*60};delete payload.interval_minutes;for(const key of ['lookback_minutes','max_age_minutes','max_pages','history_days'])payload[key]=Number(payload[key]);await api('/api/config/scheduler',{method:'PUT',body:payload});toast('自动同步计划已保存');}
    if(form.id==='notifications-form') {const payload={delivery_enabled:form.elements.delivery_enabled.checked,require_full_phone:form.elements.require_full_phone.checked,order_trigger:data.order_trigger,status_events:new FormData(form).getAll('status_events')};for(const k of ['verified_statuses','refunded_statuses','refunding_statuses'])payload[k]=data[k].split(',').map(v=>Number(v.trim()));await api('/api/config/notifications',{method:'PUT',body:payload});toast('通知发送规则已保存');}
    if(form.id==='douyin-form') {data.decrypt_enabled=form.elements.decrypt_enabled.checked;data.clue_enabled=form.elements.clue_enabled.checked;data.clue_lookback_days=Number(data.clue_lookback_days);await api('/api/config/douyin',{method:'PUT',body:data});toast('抖音应用设置已保存');await navigate('settings',true);}
    if(form.id==='channel-form') {for(const k of ['interval_seconds','max_attempts','timeout_seconds','lease_seconds'])data[k]=Number(data[k]);await api('/api/config/channel',{method:'PUT',body:data});toast('企微发送设置已保存');await navigate('settings',true);}
    if(form.id==='lead-form') {const enterprise=state.enterprises.find(e=>String(e.id)===data.enterprise_id),store=state.stores.find(s=>String(s.id)===data.store_id);if(!store||store.enterprise_id!==enterprise.id)throw new Error('请选择本企业内的门店');await api('/api/manual/lead',{method:'POST',body:{account_id:enterprise.account_id,poi_id:store.poi_id,record_id:data.record_id,event_time:Date.now()/1000,data:{customer:data.customer,phone:data.phone,intent:data.intent,remark:data.remark,source:'手工录入',poi_name:store.name}}});closeModal();toast('留资已保存，通知已生成');location.hash='messages';if(state.page==='messages')await navigate('messages',true);}
    if(form.id==='test-form') {const result=await api('/api/test-message',{method:'POST',body:{store_id:Number(data.store_id),category:data.category}});closeModal();toast(result.queued?'测试消息已生成，请查看发送状态':'测试消息已保存，当前模板未启用');await detailModal(result.message_id);}
    if(form.id==='password-form') {await api('/api/password',{method:'POST',body:data});closeModal();showLogin();toast('密码已修改，请重新登录');}
  } catch(error) {
    if(form.id==='login-form')$('#login-error').textContent=error.message;
    else toast(error.message,true);
  } finally {if(submit)submit.disabled=false;}
});

$('#modal-close').addEventListener('click',closeModal);
$('#modal').addEventListener('click',event=>{if(event.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeModal();}});
$('#menu-button').addEventListener('click',()=>$('.sidebar').classList.toggle('open'));
$('#password-button').addEventListener('click',passwordModal);
$('#logout-button').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST',body:{}});}finally{showLogin();}});
window.addEventListener('hashchange',()=>{if(state.csrf)navigate(location.hash.slice(1)||'dashboard');});

async function startApp() {
  const info=await api('/api/session');state.csrf=info.csrf;state.demo=info.demo;$('#demo-badge').hidden=false;$('#demo-badge').textContent=info.demo?'离线演示环境':'正式环境';$('#demo-badge').className='badge '+(info.demo?'amber':'green');$('#version').textContent='v'+info.version;
  $('#login-view').hidden=true;$('#app-view').hidden=false;
  await navigate(location.hash.slice(1)||'dashboard');
  clearInterval(refreshTimer);refreshTimer=setInterval(()=>{if(!document.hidden&&!$('#modal').open&&['dashboard','messages'].includes(state.page))navigate(state.page,true);},10000);
}
function clock() {$('#clock').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'short'}).format(new Date());}
clock();setInterval(clock,60000);
startApp().catch(()=>showLogin());
