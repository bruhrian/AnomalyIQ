const BACKEND_URL = 'http://localhost:8005';

// Clock
function tick() {
  const t = new Date().toLocaleTimeString('en-GB');
  const el = document.getElementById('clk'); if(el) el.textContent = t;
}
tick(); setInterval(tick, 1000);

// Status helpers
const STATUS_COLORS = {
  ok:       { border:'rgba(0,232,122,.5)',  bg:'rgba(0,232,122,.08)',  text:'var(--ok)',     dot:'var(--ok)' },
  degraded: { border:'rgba(255,184,0,.5)',  bg:'rgba(255,184,0,.08)',  text:'var(--warn)',   dot:'var(--warn)' },
  error:    { border:'rgba(255,107,53,.5)', bg:'rgba(255,107,53,.08)', text:'var(--accent2)',dot:'var(--accent2)' },
};
const STATUS_LABELS = { ok:'Connected', degraded:'Degraded', error:'Disconnected' };

// Map backend component names to HTML element IDs
const COMPONENT_MAP = {
  UI:            { badge:'badge-ui',    check:'check-ui',    node:'node-ui',    latency:'lat-ui',    detail:'detail-ui'    },
  Streaming:     { badge:'badge-mcp',   check:'check-mcp',   node:'node-mcp',   latency:'lat-mcp',   detail:'detail-mcp'   },
  MCP:           { badge:'badge-mcp',   check:'check-mcp',   node:'node-mcp',   latency:'lat-mcp',   detail:'detail-mcp'   },
  PostgreSQL:    { badge:'badge-pg',    check:'check-pg',    node:'node-pg',    latency:'lat-pg',    detail:'detail-pg'    },
  Neo4j:         { badge:'badge-neo4j', check:'check-neo4j', node:'node-neo4j', latency:'lat-neo4j', detail:'detail-neo4j' },
  DataSimulator: { badge:'badge-ds',    check:'check-ds',    node:'node-ds',    latency:'lat-ds',    detail:'detail-ds'    },
  Backend:       { badge:'badge-be',    check:'check-be',    node:'node-be',    latency:'lat-be',    detail:'detail-be'    },
};

function applyStatus(name, status, detail, latencyMs = null) {
  const ids   = COMPONENT_MAP[name];
  if (!ids) return;
  const theme = STATUS_COLORS[status] || STATUS_COLORS.error;
  const cls   = status === 'ok' ? 'ok' : status === 'degraded' ? 'warn' : 'err';
  const now   = new Date().toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});

  // Update badge (class + style)
  const badge = document.getElementById(ids.badge);
  if (badge) {
    badge.className        = `conn-badge ${cls}`;
    badge.style.background = theme.bg;
    badge.style.border     = `1px solid ${theme.border}`;
    badge.style.color      = theme.text;
    badge.innerHTML = `<div class="conn-badge-dot" style="background:${theme.dot};box-shadow:0 0 5px ${theme.dot}"></div>${STATUS_LABELS[status]}`;
  }

  // Update last-check timestamp
  const check = document.getElementById(ids.check);
  if (check) check.textContent = now;

  // Update latency
  const latEl = document.getElementById(ids.latency);
  if (latEl) {
    const hasLatency = Number.isFinite(Number(latencyMs));
    const numericLatency = hasLatency ? Math.max(0, Math.round(Number(latencyMs))) : null;
    const latencyClass = hasLatency
      ? numericLatency < 100 ? 'ok' : numericLatency < 500 ? 'warn' : 'err'
      : cls;
    const latText = hasLatency ? `${numericLatency} ms` : status === 'error' ? 'timeout' : status === 'degraded' ? 'slow' : '-- ms';
    latEl.className   = `st-latency ${latencyClass}`;
    latEl.textContent = latText;
  }

  // Update description from real backend detail
  const detailEl = document.getElementById(ids.detail);
  if (detailEl && detail) {
    detailEl.textContent = detail;
    detailEl.className   = `st-detail${status !== 'ok' ? ' err' : ''}`;
  }

  // Update connection map node
  const node = document.getElementById(ids.node);
  if (node) {
    node.className = `node-box ${cls}`;
    const dot = node.querySelector('.node-status-dot');
    if (dot) dot.className = `node-status-dot ${cls}`;
  }

// Update UI -> MCP connector line
  if (name === 'MCP' || name === 'Streaming') {
    const line = document.getElementById('line-ui-mcp');
    if (line) line.className = `conn-line ${cls}`;
  }
}

// Real-time health polling (3s, auto-reconnect)
let healthOnline = false;
let healthFailureCount = 0;
let lastHealthBanner = '';

async function loadHealth() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 7000);
    const t0 = performance.now();
    const res = await fetch(`${BACKEND_URL}/system/health`, { signal: controller.signal });
    const latencyMs = Math.round(performance.now() - t0);
    clearTimeout(timeout);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const components = data.components || {};

    if (!healthOnline) {
      healthOnline = true;
      lastHealthBanner = 'online';
    }

    if (components.Backend && !Number.isFinite(Number(components.Backend.latency_ms))) {
      components.Backend.latency_ms = latencyMs;
    }

    Object.entries(components).forEach(([name, info]) => {
      applyStatus(name, info.status, info.detail || '', info.latency_ms);
    });

    const pill     = document.getElementById('topPill');
    const pillText = document.getElementById('pillText');
    if (pill && pillText) {
      const overall  = data.overall || 'error';
      pill.className = `status-pill ${overall === 'ok' ? 'all-ok' : overall === 'degraded' ? 'has-warn' : 'has-err'}`;
      const errCount = Object.values(components).filter(c => c.status === 'error').length;
      const okCount  = Object.values(components).filter(c => c.status === 'ok').length;
      pillText.textContent = overall === 'ok' ? 'All systems nominal' : `${errCount} connection error${errCount !== 1 ? 's' : ''}`;
      const bErr = document.getElementById('badge-err-count');
      const bOk  = document.getElementById('badge-ok-count');
      if (bErr) bErr.textContent = `${errCount} error${errCount !== 1 ? 's' : ''}`;
      if (bOk)  bOk.textContent  = `${okCount} healthy`;
    }

  } catch(e) {
    if (healthOnline) {
      healthOnline = false;
      lastHealthBanner = 'offline';
    }
    ['MCP','PostgreSQL','Neo4j','DataSimulator','Backend'].forEach(n => {
      applyStatus(n, 'error', 'Backend unreachable');
    });
    const pill = document.getElementById('topPill');
    const pillText = document.getElementById('pillText');
    if (pill) pill.className = 'status-pill has-err';
    if (pillText) pillText.textContent = 'Backend offline';
    const bErr = document.getElementById('badge-err-count');
    const bOk  = document.getElementById('badge-ok-count');
      if (bErr) bErr.textContent = '-- errors';
      if (bOk)  bOk.textContent  = '-- healthy';
  } finally {
    setTimeout(loadHealth, 3000);
  }
}

// Retry a specific component
async function retryNeo4j() {
  appendSysMsg('Attempting to reconnect Neo4j on port 7687...');
  await loadHealth();
  const neo4jStatus = document.getElementById('badge-neo4j')?.textContent || '';
  if (neo4jStatus.includes('Connected')) {
    appendSysMsg('Neo4j reconnected successfully.');
  } else {
    appendSysMsg('Neo4j still unreachable. Check if service is running on port 7687.');
  }
}

// Refresh all
async function refreshAll() {
  await loadHealth();
  appendSysMsg('Status refreshed.');
}

function appendSysMsg(text) {
  const msgs = document.getElementById('chatMsgs');
  if (!msgs) return;
  const now = new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const m = document.createElement('div'); m.className='msg sys';
  m.innerHTML=`<div class="bubble">${text}</div><div class="msg-meta">SYSTEM | ${now}</div>`;
  msgs.appendChild(m); msgs.scrollTop=msgs.scrollHeight;
}

// Auto-refresh every 30s
loadHealth();

// Chat
// Shared with dashboard real /chat endpoint
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 180000;
let currentMachineId = 'M001';
let currentSessionId = (window.crypto && crypto.randomUUID)
  ? crypto.randomUUID()
  : `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function nowStr(){return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function appendMsg(cls,html,meta){const msgs=document.getElementById('chatMsgs');const el=document.createElement('div');el.className=`msg ${cls}`;el.innerHTML=`<div class="bubble">${html}</div><div class="msg-meta">${meta}</div>`;msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function appendTyping(){const msgs=document.getElementById('chatMsgs');const el=document.createElement('div');el.className='msg sys';el.innerHTML='<div class="typing-wrap"><span></span><span></span><span></span></div>';msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function escapeHtml(text){return String(text??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function formatInlineMarkdown(text){return escapeHtml(text).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-family:var(--font-mono);font-size:.95em;">$1</code>');}
function renderTableBlock(lines){const rows=lines.map(line=>line.trim()).filter(Boolean).map(line=>line.split('|').map(cell=>cell.trim()).filter((cell,idx,arr)=>!(idx===0&&cell==='')&&!(idx===arr.length-1&&cell==='')));if(rows.length<2)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;const [header,...body]=rows.filter(row=>!row.every(cell=>/^:?-{3,}:?$/.test(cell)));if(!header||!body.length)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;return `<div style="overflow:auto;margin:0 0 14px 0;"><table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text);"><thead><tr>${header.map(cell=>`<th style="text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--muted);font-family:var(--font-mono);font-size:10px;letter-spacing:.04em;text-transform:uppercase;">${formatInlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${body.map(row=>`<tr>${header.map((_,idx)=>`<td style="padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:top;">${formatInlineMarkdown(row[idx]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function renderRichText(text){const normalized=String(text??'').replace(/\r\n/g,'\n').trim();if(!normalized)return '';const blocks=normalized.split(/\n\s*\n/);return blocks.map(block=>{const lines=block.split('\n').map(line=>line.trim()).filter(Boolean);if(!lines.length)return '';if(lines.some(line=>/\|/.test(line))&&lines.length>=2){return renderTableBlock(lines);}if(lines.every(line=>/^[-*•]\s+/.test(line))){return `<ul style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^[-*•]\s+/,''))}</li>`).join('')}</ul>`;}if(lines.every(line=>/^\d+[.)]\s+/.test(line))){return `<ol style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^\d+[.)]\s+/,''))}</li>`).join('')}</ol>`;}if(lines.length===1&&/^#{1,4}\s+/.test(lines[0])){const level=Math.min(4,(lines[0].match(/^#+/)||['#'])[0].length);const size={1:22,2:19,3:16,4:14}[level];return `<div style="margin:2px 0 10px 0;font-size:${size}px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/^#{1,4}\s+/,''))}</div>`;}if(lines.length===1&&/^[A-Za-z][A-Za-z /&-]{2,}:\s*$/.test(lines[0])){return `<div style="margin:2px 0 8px 0;font-size:15px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/:\s*$/,''))}</div>`;}return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;}).join('');}
function renderSection(title,body){if(!body)return '';return `<div style="margin:0 0 16px 0;"><div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">${escapeHtml(title)}</div>${renderRichText(body)}</div>`;}
function formatVisuals(result){const urls=[];if(result?.visuals?.line_plot)urls.push({label:'Line Chart',url:result.visuals.line_plot});if(result?.visuals?.heatmap)urls.push({label:'Heatmap',url:result.visuals.heatmap});if(!urls.length&&Array.isArray(result?.visual_url)){result.visual_url.forEach((url,i)=>urls.push({label:i===0?'Line Chart':i===1?'Heatmap':`Visual ${i+1}`,url}));}if(!urls.length)return '';return `<div style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">${urls.map(v=>`<a href="${v.url}" target="_blank" style="display:block;text-decoration:none;color:var(--text);"><div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:4px;">${v.label}</div><img src="${v.url}" alt="${v.label}" style="width:100%;max-height:180px;object-fit:cover;border:1px solid var(--border);border-radius:6px;background:var(--surface2);" /></a>`).join('')}</div>`;}
function formatResult(result){if(typeof result==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(result)}</div>`;const payload=result?.result??result;if(typeof payload==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(payload)}${formatVisuals(result)}</div>`;let html='';html+=renderSection('Impact Analysis',payload.Impact_analysis);if(payload.cascade_effects&&payload.cascade_effects.length){const labels=['Immediate','Short-term','Long-term'];const cascadeText=payload.cascade_effects.map((e,i)=>`- ${labels[i]||i+1}: ${e}`).join('\n');html+=renderSection('Cascade Effects',cascadeText);}html+=renderSection('Recommended Action',payload.solutions);if(payload.sources&&payload.sources.length){html+=`<div style="margin-top:8px;font-size:11px;color:var(--muted);">Sources: ${payload.sources.map(escapeHtml).join(', ')}</div>`;}if(!html)html=renderRichText(JSON.stringify(payload,null,2));return `<div style="display:flex;flex-direction:column;gap:2px;">${html}${formatVisuals(result)}</div>`;}
function isHealthQuestion(text) {
  return /\b(backend|connected|connection|connect|down|health|status|neo4j|postgres|postgresql|mcp|simulator|service)\b/i.test(text);
}
async function answerHealthQuestion(text, typingEl) {
  const res = await fetch(`${CA_URL}/system/health`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  const comps = data.components || {};
  const parts = Object.entries(comps).map(([name, info]) => `${name}: ${info.status}${info.detail ? ` (${info.detail})` : ''}`);
  typingEl.remove();
  appendMsg('sys', `Backend health: <strong>${data.overall || 'unknown'}</strong><br>${parts.join('<br>')}`, `SYSTEM | ${nowStr()}`);
}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result),`SYSTEM | ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${data.detail||'Error'}</span>`,`SYSTEM | ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${err.message}</span>`,`SYSTEM | ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">TIMEOUT Request timed out.</span>',`SYSTEM | ${nowStr()}`);}
async function sendMsg() {
  const input = document.getElementById('chatInput');
  const btn   = document.getElementById('chatSendBtn');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  input.disabled = true;
  if (btn) btn.disabled = true;
  appendMsg('user', text, `OPERATOR | ${nowStr()}`);
  input.value = '';
  const typingEl = appendTyping();
  try {
    if (isHealthQuestion(text)) {
      await answerHealthQuestion(text, typingEl);
      return;
    }
    const res = await fetch(`${CA_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ machine_id: currentMachineId, question: text, session_id: currentSessionId })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      typingEl.remove();
      appendMsg('sys', `<span style="color:var(--accent2)">WARN ${res.status}: ${err.detail || res.statusText}</span>`, `SYSTEM | ${nowStr()}`);
      return;
    }
    const data = await res.json();
    if (data.session_id) currentSessionId = data.session_id;
    if (!data.job_id) {
      typingEl.remove();
      appendMsg('sys', '<span style="color:var(--accent2)">WARN No job_id returned.</span>', `SYSTEM | ${nowStr()}`);
      return;
    }
    await pollJob(data.job_id, typingEl);
    input.disabled = false;
    if (btn) btn.disabled = false;
    input.focus();
    return;
  } catch(err) {
    typingEl.remove();
    appendMsg('sys', `<span style="color:var(--accent2)">WARN Cannot reach backend: ${err.message}</span>`, `SYSTEM | ${nowStr()}`);
  } finally {
    input.disabled = false;
    if (btn) btn.disabled = false;
    input.focus();
  }
}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}
