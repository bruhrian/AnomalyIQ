const BACKEND_URL = 'http://localhost:8005';

function fetchJsonWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { signal: controller.signal })
    .finally(() => clearTimeout(timer))
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    });
}

// ── Clock ──
function tick() {
  const t = new Date().toLocaleTimeString('en-GB');
  const el = document.getElementById('clk'); if(el) el.textContent = t;
}
tick(); setInterval(tick, 1000);

// ── Status helpers ──
const STATUS_COLORS = {
  ok:       { border:'rgba(0,232,122,.5)',  bg:'rgba(0,232,122,.08)',  text:'var(--ok)',     dot:'var(--ok)' },
  degraded: { border:'rgba(255,184,0,.5)',  bg:'rgba(255,184,0,.08)',  text:'var(--warn)',   dot:'var(--warn)' },
  error:    { border:'rgba(255,107,53,.5)', bg:'rgba(255,107,53,.08)', text:'var(--accent2)',dot:'var(--accent2)' },
};
const STATUS_LABELS = { ok:'Connected', degraded:'Degraded', error:'Disconnected' };

// Map backend component names to HTML element IDs
const COMPONENT_MAP = {
  UI:            { badge:'badge-ui',         check:'check-ui',         node:'node-ui',         latency:'lat-ui',        detail:'detail-ui'    },
  Streaming:     { badge:'badge-streaming',  check:'check-streaming',  node:'node-streaming',  latency:'lat-streaming'},
  MCP:           { badge:'badge-mcp',        check:'check-mcp',        node:'node-mcp',        latency:'lat-mcp',       detail:'detail-mcp'   },
  PostgreSQL:    { badge:'badge-pg',         check:'check-pg',         node:'node-pg',         latency:'lat-pg',        detail:'detail-pg'    },
  Neo4j:         { badge:'badge-neo4j',      check:'check-neo4j',      node:'node-neo4j',      latency:'lat-neo4j',     detail:'detail-neo4j' },
  DataSimulator: { badge:'badge-ds',         check:'check-ds',         node:'node-ds',         latency:'lat-ds',        detail:'detail-ds'    },
  Backend:       { badge:'badge-be',         check:'check-be',         node:null,              latency:null           },
};

function applyStatus(name, status, detail, latencyMs) {
  const ids   = COMPONENT_MAP[name];
  const theme = STATUS_COLORS[status] || STATUS_COLORS.error;
  const now   = new Date().toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});

  // Update badge
  const badge = document.getElementById(ids?.badge);
  if (badge) {
    badge.style.background   = theme.bg;
    badge.style.border       = `1px solid ${theme.border}`;
    badge.style.color        = theme.text;
    badge.innerHTML = `<div class="conn-badge-dot" style="background:${theme.dot};box-shadow:0 0 5px ${theme.dot}"></div>${STATUS_LABELS[status]}`;
  }

  // Update last-check timestamp
  const check = document.getElementById(ids?.check);
  if (check) check.textContent = now;

  const detailEl = document.getElementById(ids?.detail);
  if (detailEl) {
    detailEl.textContent = detail || (status === 'ok' ? 'Connected' : status === 'degraded' ? 'Degraded' : 'Unavailable');
    detailEl.className = `st-detail ${status === 'error' ? 'err' : ''}`;
  }

  const latencyEl = document.getElementById(ids?.latency);
  if (latencyEl) {
    const ms = Number.isFinite(latencyMs) ? `${latencyMs} ms` : (detail && /timeout/i.test(detail) ? 'timeout' : '-- ms');
    latencyEl.textContent = ms;
    latencyEl.className = `st-latency ${status === 'ok' ? 'ok' : status === 'degraded' ? 'warn' : 'err'}`;
  }

  // Update connection map node
  const node = document.getElementById(ids?.node);
  if (node) {
    node.className = `node-box ${status === 'ok' ? 'ok' : status === 'degraded' ? 'warn' : 'err'}`;
    const dot = node.querySelector('.node-status-dot');
    if (dot) dot.className = `node-status-dot ${status === 'ok' ? 'ok' : status === 'degraded' ? 'warn' : 'err'}`;
  }
}

// ── Fetch real health from backend ──
async function loadHealth() {
  try {
    await fetchJsonWithTimeout(`${BACKEND_URL}/health`, 2500);
    applyStatus('Backend', 'ok', 'Running', 0);

    const data = await fetchJsonWithTimeout(`${BACKEND_URL}/system/health`, 9000);
    const components = data.components || {};

    Object.entries(components).forEach(([name, info]) => {
      applyStatus(name, info.status, info.detail || '', info.latency_ms);
    });

    const statuses = Object.values(components).map(c => c.status);
    const errCount = statuses.filter(s => s === 'error').length;
    const okCount = statuses.filter(s => s === 'ok').length;
    const warnCount = statuses.filter(s => s === 'degraded').length;
    const errBadge = document.getElementById('statusErrorCount');
    const okBadge = document.getElementById('statusHealthyCount');
    if (errBadge) errBadge.textContent = warnCount ? `${errCount} error, ${warnCount} degraded` : `${errCount} error${errCount !== 1 ? 's' : ''}`;
    if (okBadge) okBadge.textContent = `${okCount} healthy`;

    // Update top pill
    const pill = document.getElementById('topPill');
    const pillText = document.getElementById('pillText');
    if (pill && pillText) {
      const overall = data.overall || 'error';
      const theme   = STATUS_COLORS[overall];
      pill.className = `status-pill ${overall === 'ok' ? 'all-ok' : overall === 'degraded' ? 'has-warn' : 'has-err'}`;
      pillText.textContent = overall === 'ok'
        ? 'All systems nominal'
        : `${errCount} connection error${errCount !== 1 ? 's' : ''}`;
    }

  } catch(e) {
    try {
      await fetchJsonWithTimeout(`${BACKEND_URL}/health`, 2500);
      applyStatus('Backend', 'ok', 'Running', 0);
      ['MCP','PostgreSQL','Neo4j','DataSimulator'].forEach(n => {
        applyStatus(n, 'degraded', `Component health unavailable - ${e.name === 'AbortError' ? 'timed out' : e.message}`);
      });
      const errBadge = document.getElementById('statusErrorCount');
      const okBadge = document.getElementById('statusHealthyCount');
      if (errBadge) errBadge.textContent = 'component health unavailable';
      if (okBadge) okBadge.textContent = 'Backend healthy';
      const pill = document.getElementById('topPill');
      const pillText = document.getElementById('pillText');
      if (pill && pillText) {
        pill.className = 'status-pill has-warn';
        pillText.textContent = 'Backend connected';
      }
    } catch {
      ['UI','MCP','PostgreSQL','Neo4j','DataSimulator','Backend'].forEach(n => {
        if (n !== 'UI') applyStatus(n, 'error', 'Backend unreachable');
      });
    }
  }
}

// ── Retry a specific component ──
async function retryNeo4j() {
  appendSysMsg('Attempting to reconnect Neo4j on port 7687…');
  await loadHealth();
  const neo4jStatus = document.getElementById('badge-neo4j')?.textContent || '';
  if (neo4jStatus.includes('Connected')) {
    appendSysMsg('✓ Neo4j reconnected successfully.');
  } else {
    appendSysMsg('Neo4j still unreachable. Check if service is running on port 7687.');
  }
}

// ── Refresh all ──
async function refreshAll() {
  await loadHealth();
  appendSysMsg('Status refreshed.');
}

function appendSysMsg(text) {
  const msgs = document.getElementById('chatMsgs');
  if (!msgs) return;
  const now = new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const m = document.createElement('div'); m.className='msg sys';
  m.innerHTML=`<div class="bubble">${text}</div><div class="msg-meta">SYSTEM · ${now}</div>`;
  msgs.appendChild(m); msgs.scrollTop=msgs.scrollHeight;
}

// Auto-refresh every 30s
loadHealth();
setInterval(loadHealth, 30000);

// Chat
// shared with dashboard — real /qa endpoint
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 130000;
let currentMachineId = '';

function nowStr(){return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function appendMsg(cls,html,meta){const msgs=document.getElementById('chatMsgs');const el=document.createElement('div');el.className=`msg ${cls}`;el.innerHTML=`<div class="bubble">${html}</div><div class="msg-meta">${meta}</div>`;msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function appendTyping(){const msgs=document.getElementById('chatMsgs');const el=document.createElement('div');el.className='msg sys';el.innerHTML='<div class="typing-wrap"><span></span><span></span><span></span></div>';msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function formatResult(r){if(typeof r==='string')return r;let h='';if(r.Impact_analysis)h+=`<strong>Impact Analysis</strong><br>${r.Impact_analysis}<br><br>`;if(r.cascade_effects&&r.cascade_effects.length){h+='<strong>Cascade Effects</strong><br>';r.cascade_effects.forEach((e,i)=>{const l=['Immediate','Short-term','Long-term'];h+=`• ${l[i]||i+1}: ${e}<br>`;});h+='<br>';}if(r.solutions)h+=`<strong>Recommended Action</strong><br>${r.solutions}`;if(r.sources&&r.sources.length)h+=`<br><br><span style="font-size:10px;color:var(--muted);">Sources: ${r.sources.join(', ')}</span>`;return h||JSON.stringify(r,null,2);}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result?.result??data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">⚠ ${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">⚠ ${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">⏱ Request timed out.</span>',`SYSTEM · ${nowStr()}`);}
async function sendMsg(){const input=document.getElementById('chatInput');const text=input.value.trim();if(!text)return;input.disabled=true;document.querySelector('.send-btn').disabled=true;appendMsg('user',text,`OPERATOR · ${nowStr()}`);input.value='';const typingEl=appendTyping();try{const res=await fetch(`${CA_URL}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({machine_id:currentMachineId||'',question:text})});if(!res.ok){const err=await res.json().catch(()=>({}));typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">⚠ ${res.status}: ${err.detail||res.statusText}</span>`,`SYSTEM · ${nowStr()}`);return;}const data=await res.json();if(!data.job_id){typingEl.remove();appendMsg('sys','<span style="color:var(--accent2)">⚠ No job_id returned.</span>',`SYSTEM · ${nowStr()}`);return;}await pollJob(data.job_id,typingEl);}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">⚠ Cannot reach backend: ${err.message}</span>`,`SYSTEM · ${nowStr()}`);}finally{input.disabled=false;document.querySelector('.send-btn').disabled=false;input.focus();}}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}

// Unified rich answer renderer
function escapeHtml(text){return String(text??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function formatInlineMarkdown(text){return escapeHtml(text).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-family:var(--font-mono);font-size:.95em;">$1</code>');}
function renderTableBlock(lines){const rows=lines.map(line=>line.trim()).filter(Boolean).map(line=>line.split('|').map(cell=>cell.trim()).filter((cell,idx,arr)=>!(idx===0&&cell==='')&&!(idx===arr.length-1&&cell==='')));if(rows.length<2)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;const [header,...body]=rows.filter(row=>!row.every(cell=>/^:?-{3,}:?$/.test(cell)));if(!header||!body.length)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;return `<div style="overflow:auto;margin:0 0 14px 0;"><table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text);"><thead><tr>${header.map(cell=>`<th style="text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--muted);font-family:var(--font-mono);font-size:10px;letter-spacing:.04em;text-transform:uppercase;">${formatInlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${body.map(row=>`<tr>${header.map((_,idx)=>`<td style="padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:top;">${formatInlineMarkdown(row[idx]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function renderRichText(text){const normalized=String(text??'').replace(/\r\n/g,'\n').trim();if(!normalized)return '';const blocks=normalized.split(/\n\s*\n/);return blocks.map(block=>{const lines=block.split('\n').map(line=>line.trim()).filter(Boolean);if(!lines.length)return '';if(lines.some(line=>/\|/.test(line))&&lines.length>=2){return renderTableBlock(lines);}if(lines.every(line=>/^[-*•]\s+/.test(line))){return `<ul style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^[-*•]\s+/,''))}</li>`).join('')}</ul>`;}if(lines.every(line=>/^\d+[.)]\s+/.test(line))){return `<ol style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^\d+[.)]\s+/,''))}</li>`).join('')}</ol>`;}if(lines.length===1&&/^#{1,4}\s+/.test(lines[0])){const level=Math.min(4,(lines[0].match(/^#+/)||['#'])[0].length);const size={1:22,2:19,3:16,4:14}[level];return `<div style="margin:2px 0 10px 0;font-size:${size}px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/^#{1,4}\s+/,''))}</div>`;}if(lines.length===1&&/^[A-Za-z][A-Za-z /&-]{2,}:\s*$/.test(lines[0])){return `<div style="margin:2px 0 8px 0;font-size:15px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/:\s*$/,''))}</div>`;}return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;}).join('');}
function renderSection(title,body){if(!body)return '';return `<div style="margin:0 0 16px 0;"><div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">${escapeHtml(title)}</div>${renderRichText(body)}</div>`;}
function formatVisuals(result){const urls=[];if(result?.visuals?.line_plot)urls.push({label:'Line Chart',url:result.visuals.line_plot});if(result?.visuals?.heatmap)urls.push({label:'Heatmap',url:result.visuals.heatmap});if(!urls.length&&Array.isArray(result?.visual_url)){result.visual_url.forEach((url,i)=>urls.push({label:i===0?'Line Chart':i===1?'Heatmap':`Visual ${i+1}`,url}));}if(!urls.length)return '';return `<div style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">${urls.map(v=>`<a href="${v.url}" target="_blank" style="display:block;text-decoration:none;color:var(--text);"><div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:4px;">${v.label}</div><img src="${v.url}" alt="${v.label}" style="width:100%;max-height:180px;object-fit:cover;border:1px solid var(--border);border-radius:6px;background:var(--surface2);" /></a>`).join('')}</div>`;}
function formatResult(result){if(typeof result==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(result)}</div>`;const payload=result?.result??result;if(typeof payload==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(payload)}${formatVisuals(result)}</div>`;let html='';html+=renderSection('Impact Analysis',payload.Impact_analysis);if(payload.cascade_effects&&payload.cascade_effects.length){const labels=['Immediate','Short-term','Long-term'];const cascadeText=payload.cascade_effects.map((e,i)=>`- ${labels[i]||i+1}: ${e}`).join('\n');html+=renderSection('Cascade Effects',cascadeText);}html+=renderSection('Recommended Action',payload.solutions);if(payload.sources&&payload.sources.length){html+=`<div style="margin-top:8px;font-size:11px;color:var(--muted);">Sources: ${payload.sources.map(escapeHtml).join(', ')}</div>`;}if(!html)html=renderRichText(JSON.stringify(payload,null,2));return `<div style="display:flex;flex-direction:column;gap:2px;">${html}${formatVisuals(result)}</div>`;}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">TIMEOUT Request timed out.</span>',`SYSTEM · ${nowStr()}`);}
