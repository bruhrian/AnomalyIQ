// ==================== CLOCK ====================
function tick() {
  const t = new Date().toLocaleTimeString('en-GB');
  const el = document.getElementById('clk'); if(el) el.textContent = t;
  ['ts1','ts2','ts3','ts4'].forEach(id => { const e=document.getElementById(id); if(e) e.textContent=t; });
}
tick(); setInterval(tick, 1000);

// ==================== NAVIGATION FIX ====================
function switchToView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = document.getElementById(viewId);
  if (target) target.classList.add('active');
  
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
  const btnMap = { 'view-dashboard': 'nb-d', 'view-audit': 'nb-a', 'view-history': 'nb-h' };
  const activeBtn = document.getElementById(btnMap[viewId]);
  if (activeBtn) activeBtn.classList.add('active');
  
  const breadcrumb = document.getElementById('breadcrumb');
  const names = { 'view-dashboard': '/ Machine Monitor', 'view-audit': '/ Audit Log', 'view-history': '/ Chat History' };
  if (breadcrumb) breadcrumb.textContent = names[viewId] || '/ Dashboard';
}

document.getElementById('nb-d')?.addEventListener('click', () => switchToView('view-dashboard'));
document.getElementById('nb-a')?.addEventListener('click', () => switchToView('view-audit'));
document.getElementById('nb-h')?.addEventListener('click', () => switchToView('view-history'));

// ==================== AUDIT FUNCTIONS (unchanged) ====================
const AUDIT_API = 'http://localhost:8005';
let _allRows = [];
let _currentFilter = 'all';
const STAGE_CLASS = { DETECT:'detect', PROCESS:'process', SUMMARY:'summary', ANSWER:'answer', COMM:'process' };
const CORE_STAGES = ['DETECT', 'PROCESS', 'SUMMARY', 'ANSWER'];

function parseDetails(details) {
  if (!details) return {};
  if (typeof details === 'object') return details;
  try { return JSON.parse(details); } catch { return {}; }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function fmtPct(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '-';
  return `${Math.round(num * 100)}%`;
}

function shortId(value) {
  const text = String(value || '-');
  return text.length > 12 ? `${text.substring(0, 8)}...` : text;
}

function normalizeAuditLog(log) {
  const details = parseDetails(log.details);
  const stage = String(log.stage || log.event || 'DETECT').toUpperCase();
  return {
    event_id: log.event_id || String(log.id),
    job_id: details.job_id || log.job_id || String(log.id),
    machine_id: log.machine_id || details.machine_id || details.sensor_id || '-',
    machine_type: details.machine_type || log.machine_type || '-',
    stage,
    description: log.description || details.description || details.response || log.event || stage,
    created_at: log.timestamp || log.created_at,
    agent: log.agent || details.agent || 'SYSTEM',
    details,
  };
}

async function loadAudit() {
  const body = document.getElementById('auditBody');
  body.innerHTML = '<div style="padding:16px;text-align:center;font-family:var(--font-mono);font-size:11px;color:var(--muted);">Loading...</div>';
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`${AUDIT_API}/audit/logs?limit=50`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _allRows = (data.logs || data.events || []).map(normalizeAuditLog);
    document.getElementById('entryCount').textContent = `${_allRows.length} entries`;
    renderRows(_allRows, _currentFilter);
  } catch(e) {
    _allRows = [];
    document.getElementById('entryCount').textContent = 'backend unavailable';
    renderRows(_allRows, _currentFilter);
  }
}

function rowMatchesFilter(row, filter) {
  if (filter === 'all') return true;
  if (filter === 'COMM') return !CORE_STAGES.includes(row.stage);
  return row.stage === filter;
}

function getStageSummary(row) {
  const d = row.details || {};
  if (row.stage === 'DETECT') {
    const label = d.label || 'unknown';
    const confidence = d.confidence !== undefined ? fmtPct(d.confidence) : '-';
    const maintenance = d.cnn_targets?.maintenance_present ?? d.maintenance_present;
    const visualCount = Array.isArray(d.visual_url) ? d.visual_url.length : 0;
    return `
      <div class="audit-title">CNN detection result: ${escapeHtml(label)}</div>
      <div class="audit-meta">
        <span class="kv-chip">confidence ${escapeHtml(confidence)}</span>
        <span class="kv-chip">maintenance ${escapeHtml(maintenance ?? '-')}</span>
        <span class="kv-chip">${visualCount} visual${visualCount === 1 ? '' : 's'}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(row.description)}</div>`;
  }
  if (row.stage === 'PROCESS') {
    return `
      <div class="audit-title">Backend accepted alert and queued orchestration</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
        <span class="kv-chip">machine type ${escapeHtml(row.machine_type)}</span>
      </div>
      <div class="audit-detail">${escapeHtml(row.description)}</div>`;
  }
  if (row.stage === 'SUMMARY') {
    const summary = d.summary || row.description;
    return `
      <div class="audit-title">Analysis summary generated</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(summary)}</div>`;
  }
  if (row.stage === 'ANSWER') {
    const answer = d.response || row.description;
    return `
      <div class="audit-title">Operator-facing response recorded</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(answer)}</div>`;
  }
  return `
    <div class="audit-title">${escapeHtml(row.description)}</div>
    <div class="audit-meta">
      <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
      <span class="kv-chip">event ${escapeHtml(row.stage)}</span>
    </div>`;
}

function renderRows(rows, filter) {
  const body = document.getElementById('auditBody');
  const filtered = rows.filter(r => rowMatchesFilter(r, filter));
  if (filtered.length === 0) {
    const message = rows.length === 0
      ? 'No audit entries available. Trigger an anomaly to record Detect -> Process -> Summary -> Answer.'
      : 'No entries for this lifecycle stage yet.';
    body.innerHTML = `<div style="padding:16px;text-align:center;font-family:var(--font-mono);font-size:11px;color:var(--muted);">${message}</div>`;
    return;
  }
  body.innerHTML = filtered.map(r => {
    const ts = r.created_at ? new Date(r.created_at).toLocaleTimeString('en-GB') : '-';
    const cls = STAGE_CLASS[r.stage] || 'process';
    return `<div class="audit-row" style="cursor:pointer;" onclick="drillIn('${r.job_id}','${r.machine_id}')">
      <div class="atime">${ts}</div>
      <div class="stage ${cls}">${escapeHtml(r.stage)}</div>
      <div class="adesc">${getStageSummary(r)}</div>
      <div class="amach"><div>${escapeHtml(r.machine_id)}</div><span>${escapeHtml(r.machine_type)}</span></div>
    </div>`;
  }).join('');
}

function filterStage(stage, el) {
  _currentFilter = stage;
  el.closest('.tabs').querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderRows(_allRows, stage);
}

async function drillIn(jobId, machineId) {
  if (!jobId) return;
  const panel = document.getElementById('trailPanel');
  const rows = document.getElementById('trailRows');
  document.getElementById('trailEventId').textContent = `${jobId.substring(0,8)}... | ${machineId}`;
  rows.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">Loading trail...</div>';
  panel.style.display = 'block';
  try {
    const trail = _allRows
      .filter(r => r.job_id === jobId)
      .sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0))
      .map(item => ({
        created_at: item.created_at,
        stage: item.stage,
        agent: item.agent || 'SYSTEM',
        description: item.description,
      }));
    if (trail.length === 0) {
      rows.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No steps recorded for this event.</div>';
      return;
    }
    rows.innerHTML = trail.map(item => {
      const ts = item.created_at ? new Date(item.created_at).toLocaleTimeString('en-GB') : '-';
      const cls = STAGE_CLASS[item.stage] || 'process';
      return `<div style="padding:8px 0;border-bottom:1px solid var(--border);display:grid;grid-template-columns:70px 82px 1fr;gap:10px;">
        <div style="font-family:var(--font-mono);font-size:9px;color:var(--muted);">${ts}</div>
        <div class="stage ${cls}" style="font-size:9px;">${escapeHtml(item.stage)}</div>
        <div><div style="font-size:10px;">[${escapeHtml(item.agent)}] ${escapeHtml(item.description)}</div></div>
      </div>`;
    }).join('');
  } catch(e) {
    rows.innerHTML = `<div style="font-family:var(--font-mono);font-size:10px;color:var(--accent2);">Error: ${e.message}</div>`;
  }
}

function closeTrail() { document.getElementById('trailPanel').style.display = 'none'; }
function toggleThread(id) { document.getElementById(id)?.classList.toggle('open'); }

// Set init time
const auditInitEl = document.getElementById('auditInitTime');
if (auditInitEl) auditInitEl.textContent = new Date().toLocaleTimeString('en-GB');

// Load real chat sessions into history panel
async function loadHistorySessions() {
  try {
    const res = await fetch(`${AUDIT_API}/chat/sessions`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    const sessions = data.sessions || [];
    const scroll = document.getElementById('historyScroll');
    const label  = document.getElementById('historyLabel');
    if (!scroll) return;
    if (label) label.textContent = `Conversation Records - ${sessions.length} sessions`;

    // Remove old cards (keep label)
    scroll.querySelectorAll('.hcard').forEach(c => c.remove());

    if (sessions.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'color:var(--muted);font-family:var(--font-mono);font-size:10px;padding:8px 0;';
      empty.textContent = 'No sessions recorded yet.';
      scroll.appendChild(empty);
      return;
    }

    for (const sessionId of sessions) {
      const threadId = 'ht-' + sessionId.replace(/[^a-z0-9]/gi,'_');
      const card = document.createElement('div');
      card.className = 'hcard';
      card.innerHTML = `
        <div class="hcard-top"><div class="htag">${sessionId}</div><div class="htime">tap to load</div></div>
        <div class="hpreview" id="prev-${threadId}">Loading...</div>
        <div class="hfooter"><div class="hturns" id="turns-${threadId}">- turns</div><div style="flex:1"></div></div>
        <div class="hthread" id="${threadId}"></div>`;
      card.onclick = () => loadHistoryThread(sessionId, threadId);
      scroll.appendChild(card);
    }
  } catch(e) {
    console.log('Sessions load failed:', e.message);
  }
}

async function loadHistoryThread(sessionId, threadId) {
  const thread = document.getElementById(threadId);
  if (!thread) return;
  if (thread.classList.contains('open')) { thread.classList.remove('open'); return; }
  thread.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">Loading...</div>';
  thread.classList.add('open');
  try {
    const res  = await fetch(`${AUDIT_API}/chat/history/${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    const msgs = data.messages || [];
    const prev  = document.getElementById(`prev-${threadId}`);
    const turns = document.getElementById(`turns-${threadId}`);
    if (prev && msgs.length)  prev.textContent  = msgs[0].content.substring(0,100) + '...';
    if (turns) turns.textContent = `${msgs.length} turns`;
    thread.innerHTML = msgs.map(m => {
      const cls = m.role === 'human' ? 'user' : 'sys';
      return `<div class="hmsg ${cls}"><div class="hbubble">${m.content}</div><div class="hmeta">${m.role.toUpperCase()}</div></div>`;
    }).join('') || '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);">No messages.</div>';
  } catch(e) {
    thread.innerHTML = `<div style="color:var(--accent2);font-size:10px;">Error: ${e.message}</div>`;
  }
}

loadHistorySessions();

async function pollAudit() {
  await loadAudit();
  setTimeout(pollAudit, 5000);
}
pollAudit();

// ==================== CHAT FUNCTIONS (ORIGINAL - UNCHANGED) ====================
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 180000;
let currentMachineId = 'M001';
let currentSessionId = (window.crypto && crypto.randomUUID)
  ? crypto.randomUUID()
  : `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function nowStr(){return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function appendMsg(cls,html,meta){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className=`msg ${cls}`;el.innerHTML=`<div class="bubble">${html}</div><div class="msg-meta">${meta}</div>`;msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function appendTyping(){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className='msg sys';el.innerHTML='<div class="typing-wrap"><span></span><span></span><span></span></div>';msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function formatResult(r){if(typeof r==='string')return r;let h='';if(r.Impact_analysis)h+=`<strong>Impact Analysis</strong><br>${r.Impact_analysis}<br><br>`;if(r.cascade_effects&&r.cascade_effects.length){h+='<strong>Cascade Effects</strong><br>';r.cascade_effects.forEach((e,i)=>{const l=['Immediate','Short-term','Long-term'];h+=`- ${l[i]||i+1}: ${e}<br>`;});h+='<br>';}if(r.solutions)h+=`<strong>Recommended Action</strong><br>${r.solutions}`;if(r.sources&&r.sources.length)h+=`<br><br><span style="font-size:10px;color:var(--muted);">Sources: ${r.sources.join(', ')}</span>`;return h||JSON.stringify(r,null,2);}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result?.result??data.result),`SYSTEM | ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${data.detail||'Error'}</span>`,`SYSTEM | ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${err.message}</span>`,`SYSTEM | ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">TIMEOUT Request timed out.</span>',`SYSTEM | ${nowStr()}`);}
async function sendMsg(){const input=document.getElementById('chatInput');if(!input)return;const text=input.value.trim();if(!text)return;input.disabled=true;document.querySelector('.send-btn').disabled=true;appendMsg('user',text,`OPERATOR | ${nowStr()}`);input.value='';const typingEl=appendTyping();try{const res=await fetch(`${CA_URL}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({machine_id:currentMachineId,question:text,session_id:currentSessionId})});if(!res.ok){const err=await res.json().catch(()=>({}));typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${res.status}: ${err.detail||res.statusText}</span>`,`SYSTEM | ${nowStr()}`);return;}const data=await res.json();if(data.session_id)currentSessionId=data.session_id;if(!data.job_id){typingEl.remove();appendMsg('sys','<span style="color:var(--accent2)">WARN No job_id returned.</span>',`SYSTEM | ${nowStr()}`);return;}await pollJob(data.job_id,typingEl);}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN Cannot reach backend: ${err.message}</span>`,`SYSTEM | ${nowStr()}`);}finally{input.disabled=false;document.querySelector('.send-btn').disabled=false;input.focus();}}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}
document.getElementById('chatInput')?.addEventListener('keydown', handleKey);
