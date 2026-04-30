// ==================== CLOCK ====================
document.getElementById('chatMsgs')?.replaceChildren();
function tick() {
  const t = new Date().toLocaleTimeString('en-GB');
  const el = document.getElementById('clk'); if(el) el.textContent = t;
}
tick(); setInterval(tick, 1000);

// ==================== NAVIGATION FIX ====================
function switchToView(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = document.getElementById(viewId);
  if (target) target.classList.add('active');
  
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
  const btnMap = { 'view-audit': 'nb-a' };
  const activeBtn = document.getElementById(btnMap[viewId]);
  if (activeBtn) activeBtn.classList.add('active');
  
  const breadcrumb = document.getElementById('breadcrumb');
  const names = { 'view-audit': '/ Audit Log' };
  if (breadcrumb) breadcrumb.textContent = names[viewId] || '/ Audit Log';
}

document.getElementById('nb-a')?.addEventListener('click', () => switchToView('view-audit'));

// ==================== AUDIT FUNCTIONS (unchanged) ====================
const AUDIT_API = 'http://localhost:8005';
let _allRows = [];
let _currentFilter = 'all';
const STAGE_CLASS = { DETECT:'detect', PROCESS:'process', SUMMARY:'summary', ANSWER:'answer', COMM:'process' };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function normalizeStage(log) {
  const event = String(log.event || log.stage || 'DETECT').toUpperCase();
  if (['DETECT','PROCESS','SUMMARY','ANSWER','COMM'].includes(event)) return event;
  if (event.includes('SUMMARY')) return 'SUMMARY';
  if (event.includes('ANSWER') || event.includes('RESPONSE')) return 'ANSWER';
  if (event.includes('COMM')) return 'COMM';
  if (event.includes('PROCESS') || event.includes('ORCHESTRATOR')) return 'PROCESS';
  return 'DETECT';
}

function describeAuditRow(log, stage, details) {
  if (details.description) return details.description;
  if (stage === 'DETECT') {
    return `CNN detection result: ${details.label || log.event || 'detected'}${details.confidence != null ? `, confidence ${Number(details.confidence).toFixed(3)}` : ''}`;
  }
  if (stage === 'PROCESS') return 'Backend accepted alert and queued orchestration';
  if (stage === 'SUMMARY') return details.summary || details.result || 'Analysis summary generated';
  if (stage === 'ANSWER') return details.response || details.answer || 'Orchestrator answer generated';
  return details.message || details.query || log.event || 'Agent communication';
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

function renderAuditVisuals(details) {
  const visuals = [];
  if (details?.visuals?.line_plot) visuals.push({ label: 'Line Chart', url: details.visuals.line_plot });
  if (details?.visuals?.heatmap) visuals.push({ label: 'Heatmap', url: details.visuals.heatmap });
  if (!visuals.length && Array.isArray(details?.visual_url)) {
    details.visual_url.forEach((url, i) => {
      visuals.push({ label: i === 0 ? 'Line Chart' : i === 1 ? 'Heatmap' : `Visual ${i + 1}`, url });
    });
  }
  if (!visuals.length) return '';
  return `
    <div style="margin-top:10px;">
      <div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;color:var(--muted);margin-bottom:6px;">VISUAL EVIDENCE</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">
        ${visuals.map(v => `
          <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px;">
            <div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:6px;">${escapeHtml(v.label)}</div>
            <a href="${v.url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" style="display:block;">
              <img src="${v.url}" alt="${escapeHtml(v.label)}" style="display:block;width:100%;max-height:220px;object-fit:cover;border-radius:6px;border:1px solid var(--border);background:var(--bg);cursor:zoom-in;" />
            </a>
          </div>
        `).join('')}
      </div>
    </div>`;
}

function renderAuditAnalysis(item) {
  const responseText = item.details?.response || item.details?.answer || item.description || '';
  if (!responseText) return '';
  return `
    <div style="margin-top:8px;background:rgba(0,212,255,.05);border:1px solid rgba(0,212,255,.18);border-radius:8px;padding:12px;">
      <div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;color:var(--accent);margin-bottom:8px;">ORCHESTRATOR ANALYSIS</div>
      ${renderRichText(responseText)}
    </div>`;
}

function extractSection(text, heading, nextHeadings) {
  const normalized = String(text || '').replace(/\r\n/g, '\n');
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const next = nextHeadings.map(h => h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const pattern = next
    ? new RegExp(`${escaped}:?\\s*([\\s\\S]*?)(?=\\n(?:${next}):?|$)`, 'i')
    : new RegExp(`${escaped}:?\\s*([\\s\\S]*)$`, 'i');
  const match = normalized.match(pattern);
  return match ? match[1].trim() : '';
}

function renderDiagnosticCard(item) {
  const d = item.details || {};
  const responseText = String(d.response || d.answer || '').trim();
  const isTimeoutAnswer = /timed out|timeout/i.test(responseText);
  if (!responseText && !d.label && !d.machine_id) return '';

  const whatAnomaly = [
    d.machine_id || item.machine_id || '-',
    d.machine_type || item.machine_type || '-',
    d.label || 'needs_maintenance',
    d.confidence != null ? `confidence ${fmtPct(d.confidence)}` : '',
  ].filter(Boolean).join(' | ');

  const summary = extractSection(responseText, 'Summary', ['Likely Cause', 'Risks', 'Recommended Actions', 'Visual Evidence']);
  const likelyCause = isTimeoutAnswer
    ? 'The orchestrator did not finish in time for this historical record, so no completed root-cause narrative was stored here.'
    : (extractSection(responseText, 'Likely Cause', ['Risks', 'Recommended Actions', 'Visual Evidence']) || summary);
  const recommended = isTimeoutAnswer
    ? 'Review the current visuals and refresh after a successful anomaly run, or trigger a fresh anomaly analysis if needed.'
    : (extractSection(responseText, 'Recommended Actions', ['Visual Evidence']) || extractSection(responseText, 'Recommended Action', ['Visual Evidence']));
  const risks = isTimeoutAnswer
    ? 'A finished operator-facing explanation is missing for this old record, so use the charts and the latest anomaly state as the immediate reference.'
    : extractSection(responseText, 'Risks', ['Recommended Actions', 'Visual Evidence']);

  const sectionCard = (title, body) => {
    if (!body) return '';
    return `
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px;">
        <div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;color:var(--muted);margin-bottom:7px;">${escapeHtml(title)}</div>
        ${renderRichText(body)}
      </div>`;
  };

  return `
    <div style="margin-top:8px;background:rgba(0,212,255,.05);border:1px solid rgba(0,212,255,.18);border-radius:10px;padding:12px;">
      <div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;color:var(--accent);margin-bottom:10px;">DIAGNOSTIC CARD</div>
      <div style="display:grid;gap:10px;">
        <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px;">
          <div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;color:var(--muted);margin-bottom:7px;">DETECTED ANOMALY</div>
          <div style="font-size:13px;line-height:1.55;color:var(--text);">${escapeHtml(whatAnomaly)}</div>
        </div>
        ${sectionCard('POSSIBLE ROOT CAUSE', likelyCause)}
        ${sectionCard('OPERATIONAL RISK', risks)}
        ${sectionCard('RECOMMENDED RESPONSE', recommended)}
      </div>
    </div>`;
}

function getStageSummary(row) {
  const d = row.details || {};
  if (row.stage === 'DETECT') {
    const visualCount = Array.isArray(d.visual_url) ? d.visual_url.length : 0;
    return `
      <div class="audit-title">CNN detection result: ${escapeHtml(d.label || 'unknown')}</div>
      <div class="audit-meta">
        <span class="kv-chip">confidence ${escapeHtml(fmtPct(d.confidence))}</span>
        <span class="kv-chip">${visualCount} visual${visualCount === 1 ? '' : 's'}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(row.description)}</div>`;
  }
  if (row.stage === 'PROCESS') {
    return `
      <div class="audit-title">Orchestrator accepted anomaly job</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(row.description)}</div>`;
  }
  if (row.stage === 'SUMMARY') {
    return `
      <div class="audit-title">Analysis summary generated</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
      </div>
      <div class="audit-detail">${escapeHtml(d.summary || row.description)}</div>`;
  }
  if (row.stage === 'ANSWER') {
    const visualCount = Array.isArray(d.visual_url) ? d.visual_url.length : 0;
    return `
      <div class="audit-title">Operator-facing response recorded</div>
      <div class="audit-meta">
        <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
        <span class="kv-chip">job ${escapeHtml(shortId(row.job_id))}</span>
        <span class="kv-chip">${visualCount} visual${visualCount === 1 ? '' : 's'}</span>
      </div>
      <div class="audit-detail">${escapeHtml((d.response || row.description || '').substring(0, 260))}</div>`;
  }
  return `
    <div class="audit-title">${escapeHtml(row.description)}</div>
    <div class="audit-meta">
      <span class="kv-chip">agent ${escapeHtml(row.agent)}</span>
      <span class="kv-chip">event ${escapeHtml(row.stage)}</span>
    </div>`;
}

async function loadAudit() {
  const body = document.getElementById('auditBody');
  body.innerHTML = '<div style="padding:16px;text-align:center;font-family:var(--font-mono);font-size:11px;color:var(--muted);">Loading...</div>';
  try {
    const res = await fetch(`${AUDIT_API}/audit/logs?limit=200`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _allRows = (data.logs || data.events || []).map(log => ({
      event_id: log.event_id || String(log.id),
      machine_id: log.machine_id || log.details?.machine_id || '-',
      stage: (log.stage || log.event || 'DETECT').toUpperCase(),
      description: log.description || (log.details ? JSON.stringify(log.details).substring(0,100) : log.event),
      created_at: log.timestamp || log.created_at,
    }));
    _allRows = (data.logs || data.events || []).map(log => {
      const details = log.details || {};
      const stage = normalizeStage(log);
      return {
        event_id: String(log.id ?? log.event_id ?? details.job_id ?? ''),
        job_id: details.job_id || String(log.id ?? ''),
        agent: log.agent || details.agent || 'SYSTEM',
        machine_id: log.machine_id || details.machine_id || details.sensor_id || '-',
        machine_type: details.machine_type || log.machine_type || '-',
        stage,
        description: describeAuditRow(log, stage, details),
        created_at: log.timestamp || log.created_at,
        details,
      };
    });
    document.getElementById('entryCount').textContent = `${_allRows.length} entries`;
    renderRows(_allRows, _currentFilter);
  } catch(e) {
    body.innerHTML = `<div style="padding:20px;text-align:center;font-family:var(--font-mono);font-size:11px;color:var(--accent2);">Cannot reach backend at ${AUDIT_API}<br><span style="color:var(--muted);font-size:10px;">Make sure main.py is running (port 8005)</span></div>`;
    document.getElementById('entryCount').textContent = 'offline';
  }
}

function renderRows(rows, filter) {
  const body = document.getElementById('auditBody');
  const filtered = filter === 'all' ? rows : rows.filter(r => r.stage === filter);
  if (filtered.length === 0) {
    body.innerHTML = '<div style="padding:16px;text-align:center;font-family:var(--font-mono);font-size:11px;color:var(--muted);">No entries for this filter.</div>';
    return;
  }
  body.innerHTML = filtered.map(r => {
    const ts = r.created_at ? new Date(r.created_at).toLocaleTimeString('en-GB') : '-';
    const cls = STAGE_CLASS[r.stage] || 'process';
    return `<div class="audit-row" style="cursor:pointer;" onclick="drillIn('${escapeHtml(r.event_id)}','${escapeHtml(r.job_id)}')">
      <div class="atime">${ts}</div><div class="stage ${cls}">${r.stage}</div><div class="adesc">${getStageSummary(r)}</div><div class="amach"><div>${escapeHtml(r.machine_id)}</div><span>${escapeHtml(r.machine_type)}</span></div>
    </div>`;
  }).join('');
}

function filterStage(stage, el) {
  _currentFilter = stage;
  el.closest('.tabs').querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderRows(_allRows, stage);
}

async function drillIn(eventId, machineId) {
  if (!eventId) return;
  const panel = document.getElementById('trailPanel');
  const rows = document.getElementById('trailRows');
  document.getElementById('trailEventId').textContent = `${eventId.substring(0,8)}... · ${machineId}`;
  rows.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">Loading trail...</div>';
  panel.style.display = 'block';
  try {
    const res = await fetch(`${AUDIT_API}/audit/trail/${eventId}`);
    const trail = res.ok ? (await res.json()).steps : [];
    if (trail.length === 0) {
      rows.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No steps recorded for this event.</div>';
      return;
    }
    rows.innerHTML = trail.map(item => {
      const ts = item.created_at ? new Date(item.created_at).toLocaleTimeString('en-GB') : '-';
      const cls = STAGE_CLASS[item.stage] || 'process';
      return `<div style="padding:8px 0;border-bottom:1px solid var(--border);display:grid;grid-template-columns:70px 82px 1fr;gap:10px;">
        <div style="font-family:var(--font-mono);font-size:9px;color:var(--muted);">${ts}</div>
        <div class="stage ${cls}" style="font-size:9px;">${item.stage}</div>
        <div><div style="font-size:10px;">[${item.agent}] ${item.description}</div></div>
      </div>`;
    }).join('');
  } catch(e) {
    rows.innerHTML = `<div style="font-family:var(--font-mono);font-size:10px;color:var(--accent2);">Error: ${e.message}</div>`;
  }
}

function closeTrail() { document.getElementById('trailPanel').style.display = 'none'; }

function drillIn(eventId, jobId) {
  if (!eventId) return;
  const panel = document.getElementById('trailPanel');
  const rows = document.getElementById('trailRows');
  document.getElementById('trailEventId').textContent = `${String(jobId || eventId).substring(0,8)}...`;
  panel.style.display = 'block';

  const trail = _allRows
    .filter(item => item.job_id === jobId || item.event_id === eventId)
    .sort((a,b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));

  const selected = trail.find(item => String(item.event_id) === String(eventId)) || trail[trail.length - 1];
  const orderedTrail = selected && selected.stage === 'ANSWER'
    ? [selected, ...trail.filter(item => item !== selected)]
    : trail;

  if (orderedTrail.length === 0) {
    rows.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No related audit rows found.</div>';
    return;
  }

  rows.innerHTML = orderedTrail.map(item => {
    const ts = item.created_at ? new Date(item.created_at).toLocaleTimeString('en-GB') : '--';
    const cls = STAGE_CLASS[item.stage] || 'process';
    const visualsHtml = renderAuditVisuals(item.details || {});
    const responseHtml = item.stage === 'ANSWER'
      ? renderDiagnosticCard(item)
      : item.stage === 'SUMMARY'
        ? `<div style="margin-top:8px;">${renderRichText(item.details?.summary || item.description)}</div>`
        : '';
    const detailJson = escapeHtml(JSON.stringify(item.details || {}, null, 2));
    const headerHtml = item.stage === 'ANSWER'
      ? `<div style="font-size:10px;margin-bottom:8px;"><strong>[${escapeHtml(item.agent)}]</strong> Operator-facing anomaly response</div>`
      : `<div style="font-size:10px;"><strong>[${escapeHtml(item.agent)}]</strong> ${escapeHtml(item.description)}</div>`;
    return `<div style="padding:10px 0;border-bottom:1px solid var(--border);display:grid;grid-template-columns:70px 82px 1fr;gap:10px;">
      <div style="font-family:var(--font-mono);font-size:9px;color:var(--muted);">${ts}</div>
      <div class="stage ${cls}" style="font-size:9px;">${item.stage}</div>
      <div>
        ${headerHtml}
        ${responseHtml}
        ${item.stage === 'ANSWER' ? visualsHtml : visualsHtml}
        <details style="margin-top:8px;">
          <summary style="cursor:pointer;font-family:var(--font-mono);font-size:10px;color:var(--muted);">Raw details</summary>
          <pre style="white-space:pre-wrap;margin-top:6px;color:var(--muted);font-size:9px;line-height:1.35;">${detailJson}</pre>
        </details>
      </div>
    </div>`;
  }).join('');
}

function toggleThread(id) { document.getElementById(id)?.classList.toggle('open'); }

let auditStream = null;
let auditFallbackTimer = null;

function startAuditStream() {
  if (auditStream) {
    auditStream.close();
    auditStream = null;
  }
  try {
    auditStream = new EventSource(`${AUDIT_API}/audit/stream?limit=200`);
    auditStream.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data || '{}');
        if (data.error) return;
        _allRows = (data.logs || []).map(log => {
          const details = log.details || {};
          const stage = normalizeStage(log);
          return {
            event_id: String(log.id ?? log.event_id ?? details.job_id ?? ''),
            job_id: details.job_id || String(log.id ?? ''),
            agent: log.agent || details.agent || 'SYSTEM',
            machine_id: log.machine_id || details.machine_id || details.sensor_id || '-',
            machine_type: details.machine_type || log.machine_type || '-',
            stage,
            description: describeAuditRow(log, stage, details),
            created_at: log.timestamp || log.created_at,
            details,
          };
        });
        document.getElementById('entryCount').textContent = `${_allRows.length} entries`;
        renderRows(_allRows, _currentFilter);
      } catch (e) {
        console.log('Audit stream parse failed:', e.message);
      }
    };
    auditStream.onerror = () => {
      if (!auditFallbackTimer) {
        auditFallbackTimer = setInterval(loadAudit, 1500);
      }
    };
  } catch (e) {
    console.log('Audit stream unavailable:', e.message);
    if (!auditFallbackTimer) {
      auditFallbackTimer = setInterval(loadAudit, 1500);
    }
  }
}

loadAudit();
startAuditStream();

// ==================== CHAT FUNCTIONS (ORIGINAL - UNCHANGED) ====================
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 130000;
let currentMachineId = '';

function nowStr(){return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function appendMsg(cls,html,meta){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className=`msg ${cls}`;el.innerHTML=`<div class="bubble">${html}</div><div class="msg-meta">${meta}</div>`;msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function appendTyping(){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className='msg sys';el.innerHTML='<div class="typing-wrap"><span></span><span></span><span></span></div>';msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function formatResult(r){if(typeof r==='string')return r;let h='';if(r.Impact_analysis)h+=`<strong>Impact Analysis</strong><br>${r.Impact_analysis}<br><br>`;if(r.cascade_effects&&r.cascade_effects.length){h+='<strong>Cascade Effects</strong><br>';r.cascade_effects.forEach((e,i)=>{const l=['Immediate','Short-term','Long-term'];h+=`- ${l[i]||i+1}: ${e}<br>`;});h+='<br>';}if(r.solutions)h+=`<strong>Recommended Action</strong><br>${r.solutions}`;if(r.sources&&r.sources.length)h+=`<br><br><span style="font-size:10px;color:var(--muted);">Sources: ${r.sources.join(', ')}</span>`;return h||JSON.stringify(r,null,2);}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result?.result??data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">Request timed out.</span>',`SYSTEM · ${nowStr()}`);}
async function sendMsg(){const input=document.getElementById('chatInput');if(!input)return;const text=input.value.trim();if(!text)return;input.disabled=true;document.querySelector('.send-btn').disabled=true;appendMsg('user',text,`OPERATOR · ${nowStr()}`);input.value='';const typingEl=appendTyping();try{const res=await fetch(`${CA_URL}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({machine_id:currentMachineId||'',question:text})});if(!res.ok){const err=await res.json().catch(()=>({}));typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${res.status}: ${err.detail||res.statusText}</span>`,`SYSTEM · ${nowStr()}`);return;}const data=await res.json();if(!data.job_id){typingEl.remove();appendMsg('sys','<span style="color:var(--accent2)">No job_id returned.</span>',`SYSTEM · ${nowStr()}`);return;}await pollJob(data.job_id,typingEl);}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">Cannot reach backend: ${err.message}</span>`,`SYSTEM · ${nowStr()}`);}finally{input.disabled=false;document.querySelector('.send-btn').disabled=false;input.focus();}}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}
document.getElementById('chatInput')?.addEventListener('keydown', handleKey);

// Unified rich answer renderer
function escapeHtml(text){return String(text??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function formatInlineMarkdown(text){return escapeHtml(text).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-family:var(--font-mono);font-size:.95em;">$1</code>');}
function renderTableBlock(lines){const rows=lines.map(line=>line.trim()).filter(Boolean).map(line=>line.split('|').map(cell=>cell.trim()).filter((cell,idx,arr)=>!(idx===0&&cell==='')&&!(idx===arr.length-1&&cell==='')));if(rows.length<2)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;const [header,...body]=rows.filter(row=>!row.every(cell=>/^:?-{3,}:?$/.test(cell)));if(!header||!body.length)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;return `<div style="overflow:auto;margin:0 0 14px 0;"><table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text);"><thead><tr>${header.map(cell=>`<th style="text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--muted);font-family:var(--font-mono);font-size:10px;letter-spacing:.04em;text-transform:uppercase;">${formatInlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${body.map(row=>`<tr>${header.map((_,idx)=>`<td style="padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:top;">${formatInlineMarkdown(row[idx]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function renderRichText(text){const normalized=String(text??'').replace(/\r\n/g,'\n').trim();if(!normalized)return '';const blocks=normalized.split(/\n\s*\n/);return blocks.map(block=>{const lines=block.split('\n').map(line=>line.trim()).filter(Boolean);if(!lines.length)return '';if(lines.some(line=>/\|/.test(line))&&lines.length>=2){return renderTableBlock(lines);}if(lines.every(line=>/^[-*•]\s+/.test(line))){return `<ul style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^[-*•]\s+/,''))}</li>`).join('')}</ul>`;}if(lines.every(line=>/^\d+[.)]\s+/.test(line))){return `<ol style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^\d+[.)]\s+/,''))}</li>`).join('')}</ol>`;}if(lines.length===1&&/^#{1,4}\s+/.test(lines[0])){const level=Math.min(4,(lines[0].match(/^#+/)||['#'])[0].length);const size={1:22,2:19,3:16,4:14}[level];return `<div style="margin:2px 0 10px 0;font-size:${size}px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/^#{1,4}\s+/,''))}</div>`;}if(lines.length===1&&/^[A-Za-z][A-Za-z /&-]{2,}:\s*$/.test(lines[0])){return `<div style="margin:2px 0 8px 0;font-size:15px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/:\s*$/,''))}</div>`;}return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;}).join('');}
function renderSection(title,body){if(!body)return '';return `<div style="margin:0 0 16px 0;"><div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">${escapeHtml(title)}</div>${renderRichText(body)}</div>`;}
function formatVisuals(result){const urls=[];if(result?.visuals?.line_plot)urls.push({label:'Line Chart',url:result.visuals.line_plot});if(result?.visuals?.heatmap)urls.push({label:'Heatmap',url:result.visuals.heatmap});if(!urls.length&&Array.isArray(result?.visual_url)){result.visual_url.forEach((url,i)=>urls.push({label:i===0?'Line Chart':i===1?'Heatmap':`Visual ${i+1}`,url}));}if(!urls.length)return '';return `<div style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">${urls.map(v=>`<a href="${v.url}" target="_blank" style="display:block;text-decoration:none;color:var(--text);"><div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:4px;">${v.label}</div><img src="${v.url}" alt="${v.label}" style="width:100%;max-height:180px;object-fit:cover;border:1px solid var(--border);border-radius:6px;background:var(--surface2);" /></a>`).join('')}</div>`;}
function formatResult(result){if(typeof result==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(result)}</div>`;const payload=result?.result??result;if(typeof payload==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(payload)}${formatVisuals(result)}</div>`;let html='';html+=renderSection('Impact Analysis',payload.Impact_analysis);if(payload.cascade_effects&&payload.cascade_effects.length){const labels=['Immediate','Short-term','Long-term'];const cascadeText=payload.cascade_effects.map((e,i)=>`- ${labels[i]||i+1}: ${e}`).join('\n');html+=renderSection('Cascade Effects',cascadeText);}html+=renderSection('Recommended Action',payload.solutions);if(payload.sources&&payload.sources.length){html+=`<div style="margin-top:8px;font-size:11px;color:var(--muted);">Sources: ${payload.sources.map(escapeHtml).join(', ')}</div>`;}if(!html)html=renderRichText(JSON.stringify(payload,null,2));return `<div style="display:flex;flex-direction:column;gap:2px;">${html}${formatVisuals(result)}</div>`;}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">Request timed out.</span>',`SYSTEM · ${nowStr()}`);}