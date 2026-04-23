// ==================== CLOCK (unchanged from original) ====================
function tick() {
  const t = new Date().toLocaleTimeString('en-GB');
  const el = document.getElementById('clk'); if(el) el.textContent = t;
  ['ts1','ts2','ts3','ts4'].forEach(id => { const e=document.getElementById(id); if(e) e.textContent=t; });
}
tick(); setInterval(tick, 1000);
const dashInitEl = document.getElementById('dashInitTime');
if (dashInitEl) dashInitEl.textContent = new Date().toLocaleTimeString('en-GB');

// ==================== NAVIGATION (FIXED - added) ====================
const viewMap = {
  'nb-dashboard': 'view-dashboard',
  'nb-audit': 'view-audit',
  'nb-history': 'view-history',
  'nb-livefeed': 'view-livefeed',
  'nb-analytics': 'view-analytics',
  'nb-status': 'view-status',
  'nb-profile': 'view-profile'
};

const breadcrumbMap = {
  'nb-dashboard': '/ Machine Monitor',
  'nb-audit': '/ Audit Log',
  'nb-history': '/ Chat History',
  'nb-livefeed': '/ Live Feed',
  'nb-analytics': '/ Analytics',
  'nb-status': '/ System Status',
  'nb-profile': '/ Profile'
};

function switchToView(buttonId) {
  document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
  const clickedBtn = document.getElementById(buttonId);
  if (clickedBtn) clickedBtn.classList.add('active');
  
  document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
  const targetViewId = viewMap[buttonId];
  if (targetViewId) {
    const targetView = document.getElementById(targetViewId);
    if (targetView) targetView.classList.add('active');
  }
  
  const breadcrumb = document.getElementById('breadcrumb');
  if (breadcrumb && breadcrumbMap[buttonId]) breadcrumb.textContent = breadcrumbMap[buttonId];
}

Object.keys(viewMap).forEach(btnId => {
  const btn = document.getElementById(btnId);
  if (btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      switchToView(btnId);
    });
  }
});

// ==================== ORIGINAL CHAT FUNCTIONS (RESTORED) ====================
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 180000;
let currentMachineId = 'M001';
let currentSessionId = (window.crypto && crypto.randomUUID)
  ? crypto.randomUUID()
  : `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function nowStr() {
  return new Date().toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
}

function appendMsg(cls, html, metaText) {
  const msgs = document.getElementById('chatMsgs');
  const el = document.createElement('div');
  el.className = `msg ${cls}`;
  el.innerHTML = `<div class="bubble">${html}</div><div class="msg-meta">${metaText}</div>`;
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
  return el;
}

function appendTyping() {
  const msgs = document.getElementById('chatMsgs');
  const el = document.createElement('div');
  el.className = 'msg sys';
  el.innerHTML = '<div class="typing-wrap"><span></span><span></span><span></span></div>';
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
  return el;
}

function formatResult(result) {
  if (typeof result === 'string') return result;
  let html = '';
  if (result.Impact_analysis) html += `<strong>Impact Analysis</strong><br>${result.Impact_analysis}<br><br>`;
  if (result.cascade_effects && result.cascade_effects.length) {
    html += `<strong>Cascade Effects</strong><br>`;
    result.cascade_effects.forEach((e, i) => {
      const labels = ['Immediate', 'Short-term', 'Long-term'];
      html += `- ${labels[i] || i+1}: ${e}<br>`;
    });
    html += '<br>';
  }
  if (result.solutions) html += `<strong>Recommended Action</strong><br>${result.solutions}`;
  if (result.sources && result.sources.length) html += `<br><br><span style="font-size:10px;color:var(--muted);">Sources: ${result.sources.join(', ')}</span>`;
  return html || JSON.stringify(result, null, 2);
}

async function pollJob(jobId, typingEl) {
  const deadline = Date.now() + POLL_TIMEOUT;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, POLL_MS));
    try {
      const res = await fetch(`${CA_URL}/jobs/${jobId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.status === 'done') {
        typingEl.remove();
        const result = data.result;
        const html = formatResult(result?.result ?? result);
        appendMsg('sys', html, `SYSTEM | ${nowStr()}`);
        return;
      }
      if (data.status === 'error') {
        typingEl.remove();
        appendMsg('sys', `<span style="color:var(--accent2)">WARN Error: ${data.detail || 'Unknown error'}</span>`, `SYSTEM | ${nowStr()}`);
        return;
      }
    } catch (err) {
      typingEl.remove();
      appendMsg('sys', `<span style="color:var(--accent2)">WARN Lost connection: ${err.message}</span>`, `SYSTEM | ${nowStr()}`);
      return;
    }
  }
  typingEl.remove();
  appendMsg('sys', `<span style="color:var(--warn)">TIMEOUT Request timed out after ${POLL_TIMEOUT/1000}s</span>`, `SYSTEM | ${nowStr()}`);
}

async function sendMsg() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  
  input.disabled = true;
  document.querySelector('.send-btn').disabled = true;
  
  appendMsg('user', text, `OPERATOR | ${nowStr()}`);
  input.value = '';
  
  const typingEl = appendTyping();
  
  try {
    const res = await fetch(`${CA_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ machine_id: currentMachineId, question: text, session_id: currentSessionId }),
    });
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      typingEl.remove();
      appendMsg('sys', `<span style="color:var(--accent2)">WARN Backend error ${res.status}: ${err.detail || res.statusText}</span>`, `SYSTEM | ${nowStr()}`);
      return;
    }
    
    const data = await res.json();
    const jobId = data.job_id;
    if (data.session_id) currentSessionId = data.session_id;
    
    if (!jobId) {
      typingEl.remove();
      appendMsg('sys', `<span style="color:var(--accent2)">WARN No job_id returned.</span>`, `SYSTEM | ${nowStr()}`);
      return;
    }
    
    await pollJob(jobId, typingEl);
  } catch (err) {
    typingEl.remove();
    appendMsg('sys', `<span style="color:var(--accent2)">WARN Cannot reach backend at ${CA_URL}. Is it running?<br><span style="font-size:10px;">${err.message}</span></span>`, `SYSTEM | ${nowStr()}`);
  } finally {
    input.disabled = false;
    document.querySelector('.send-btn').disabled = false;
    input.focus();
  }
}

function handleKey(e) { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); } }

document.getElementById('chatInput').addEventListener('keydown', handleKey);

function toggleThread(id) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('open');
}

console.log('Navigation fixed, AI chatbot original logic restored.');

// ==================== LIVE SSE DATA ====================
const STREAM_URL = 'http://localhost:8005/machines/stream';

const FIELD_RANGES = {
  temperature:        { min: 60,  max: 100 },
  vibration_level:    { min: 0,   max: 10  },
  power_consumption:  { min: 10,  max: 30  },  // real data: 14~28 kW
  pressure:           { min: 3.5, max: 6.5 },  // real data: 4~6 Pa
  material_flow_rate: { min: 15,  max: 25  },  // real data: 17~22
  cycle_time:         { min: 100, max: 140 },  // real data: 109~132s
};

const THRESHOLDS = {
  temperature:        { warn: 82,   alert: 88   },  // real data: 66~92C
  vibration_level:    { warn: 4.0,  alert: 6.0  },  // real data: 1.2~7.2
  power_consumption:  { warn: 22,   alert: 26   },  // real data: 14~28 kW
  pressure:           { warn: 5.3,  alert: 5.6  },  // real data: 4.1~5.8 Pa
  material_flow_rate: { warn: 18.0, alert: 17.0 },  // lower = worse, real: 17~22
  cycle_time:         { warn: 125,  alert: 130  },  // real data: 109~132s
};

function getLevel(field, val) {
  const t = THRESHOLDS[field];
  if (!t) return 'ok';
  if (field === 'material_flow_rate') {
    if (val <= t.alert) return 'alert';
    if (val <= t.warn)  return 'warn';
    return 'ok';
  }
  if (val >= t.alert) return 'alert';
  if (val >= t.warn)  return 'warn';
  return 'ok';
}

function getPct(field, val) {
  const r = FIELD_RANGES[field];
  if (!r) return 0;
  return Math.min(100, Math.max(0, ((val - r.min) / (r.max - r.min)) * 100));
}

function updateMachine(d) {
  const id = d.machine_id;
  const row = document.getElementById(`row-${id}`);
  if (!row) return;

  // Update machine type dynamically from SSE stream
  if (d.machine_type) {
    const nameEl = document.getElementById(`name-${id}`);
    if (nameEl) nameEl.textContent = d.machine_type;
  }

  const fields = ['temperature','vibration_level','power_consumption','pressure','material_flow_rate','cycle_time'];

// Use CNN label directly - no threshold logic needed
  const worstLevel = d.label === 'needs_maintenance' ? 'alert' : 'ok';

  fields.forEach(f => {
    const val = d[f];
    if (val == null) return;
    const el  = document.getElementById(`${id}-${f}`);
    const bar = document.getElementById(`${id}-${f}-bar`);
    // Bar colour follows CNN label, not individual thresholds
    const barCls = worstLevel === 'alert' ? 'alert' : 'ok';
    if (el)  { el.textContent = typeof val === 'number' ? val.toFixed(f==='pressure'?0:2) : val; el.className = `fv ${barCls}`; }
    if (bar) { bar.style.width = getPct(f, val) + '%'; bar.className = `bar ${barCls}`; }
  });

  const tsEl = document.getElementById(`${id}-timestamp`);
  if (tsEl) tsEl.textContent = d.timestamp || new Date().toLocaleTimeString('en-GB');

  const dot    = document.getElementById(`dot-${id}`);
  const status = document.getElementById(`status-${id}`);
  const colors = { ok:'var(--ok)', warn:'var(--warn)', alert:'var(--accent2)' };
  const labels = { ok:'Normal', warn:'Warning', alert:'Alert' };
  row.className = `mrow${worstLevel !== 'ok' ? ` s-${worstLevel}` : ''}`;
  if (dot)    dot.className    = `dot ${worstLevel}`;
  if (status) { status.textContent = labels[worstLevel]; status.style.color = colors[worstLevel]; }

  const badge = row.querySelector('.abadge');
  if (worstLevel === 'alert') {
if (!badge) { const b = document.createElement('div'); b.className = 'abadge'; b.textContent = '⚠ ANOMALY'; row.appendChild(b); }
  } else {
    if (badge) badge.remove();
  }
}

function startStream() {
  const es = new EventSource(STREAM_URL);
  es.onmessage = e => {
    try { updateMachine(JSON.parse(e.data)); } catch(_) {}
  };
  es.onerror = () => {
    es.close();
    setTimeout(startStream, 5000);
  };
}

startStream();

// ==================== LIVE CHART ====================
const MAX_POINTS = 60;
const chartBuffers = {};
['M001','M002','M003','M004'].forEach(id => {
  chartBuffers[id] = {};
  ['temperature','vibration_level','power_consumption','pressure','material_flow_rate','cycle_time'].forEach(f => {
    chartBuffers[id][f] = [];
  });
});

let liveChart = null;

function initChart() {
  const canvas = document.getElementById('liveChart');
  if (!canvas || !window.Chart) return;
  const ctx = canvas.getContext('2d');
  liveChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Temperature C',
        data: [],
        borderColor: '#00d4ff',
        backgroundColor: 'rgba(0,212,255,0.08)',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.3,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          grid: { color: 'rgba(42,48,72,0.8)' },
          ticks: { color: '#6b7394', font: { family: 'IBM Plex Mono', size: 10 } }
        }
      }
    }
  });
}

function updateChart() {
  if (!liveChart) return;
  const machine = document.getElementById('chartMachine')?.value || 'M001';
  const field   = document.getElementById('chartField')?.value   || 'temperature';
  const buf = chartBuffers[machine]?.[field] || [];

  liveChart.data.labels   = buf.map((_,i) => i);
  liveChart.data.datasets[0].data  = buf.map(p => p.v);
  liveChart.data.datasets[0].label = field;

  const vals = buf.map(p => p.v);
  const cur = vals[vals.length-1];
  const mn  = vals.length ? Math.min(...vals) : null;
  const mx  = vals.length ? Math.max(...vals) : null;

  const fmt = v => v == null ? '--' : (field === 'pressure' ? v.toFixed(0) : v.toFixed(2));
  document.getElementById('statCurrent').textContent = fmt(cur);
  document.getElementById('statMin').textContent     = fmt(mn);
  document.getElementById('statMax').textContent     = fmt(mx);
  document.getElementById('chartCount').textContent  = buf.length;

  liveChart.update('none');
}

// Patch updateMachine to also buffer chart data
const _origUpdate = updateMachine;
window.updateMachine = function(d) {
  _origUpdate(d);
  const id = d.machine_id;
  if (!chartBuffers[id]) return;
  ['temperature','vibration_level','power_consumption','pressure','material_flow_rate','cycle_time'].forEach(f => {
    if (d[f] == null) return;
    chartBuffers[id][f].push({ v: d[f], t: d.timestamp });
    if (chartBuffers[id][f].length > MAX_POINTS) chartBuffers[id][f].shift();
  });
  const selM = document.getElementById('chartMachine')?.value;
  const selF = document.getElementById('chartField')?.value;
  if (id === selM) updateChart();
};

document.getElementById('chartMachine')?.addEventListener('change', updateChart);
document.getElementById('chartField')?.addEventListener('change', updateChart);

// ==================== ANALYTICS ====================
const anomalyStats = { M001:0, M002:0, M003:0, M004:0 };
const latestLevels = { M001:'ok', M002:'ok', M003:'ok', M004:'ok' };
let barChart = null;
const anomalyLog = [];

function initBarChart() {
  const canvas = document.getElementById('barChart');
  if (!canvas || !window.Chart) return;
  barChart = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: ['M001', 'M002', 'M003', 'M004'],
      datasets: [{
        label: 'Anomalies',
        data: [0, 0, 0, 0],
        backgroundColor: ['rgba(0,212,255,.25)','rgba(255,107,53,.25)','rgba(0,232,122,.25)','rgba(255,184,0,.25)'],
        borderColor: ['#00d4ff','#ff6b35','#00e87a','#ffb800'],
        borderWidth: 2,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => ` ${ctx.parsed.y} anomalies`
        }}
      },
      scales: {
        x: {
          grid: { color: 'rgba(42,48,72,.8)' },
          ticks: { color: '#6b7394', font: { family: 'IBM Plex Mono', size: 10 } }
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(42,48,72,.8)' },
          ticks: { color: '#6b7394', font: { family: 'IBM Plex Mono', size: 10 }, stepSize: 1 }
        }
      }
    }
  });
}

function updateAnalyticsFromState() {
  const ids = ['M001','M002','M003','M004'];
  ids.forEach(id => {
    anomalyStats[id] = latestLevels[id] === 'alert' ? 1 : 0;
  });
  const alertCount = ids.filter(id => latestLevels[id] === 'alert').length;
  const warnCount = ids.filter(id => latestLevels[id] === 'warn').length;
  const okCount = ids.filter(id => latestLevels[id] === 'ok').length;
  const totalAnomalies = alertCount + warnCount;

  document.getElementById('an-total').textContent = totalAnomalies;
  document.getElementById('an-alert').textContent = alertCount;
  document.getElementById('an-warn').textContent  = warnCount;
  document.getElementById('an-ok').textContent    = okCount;

  if (barChart) {
    const vals = ids.map(id => anomalyStats[id] || 0);
    barChart.data.datasets[0].data = vals;
    barChart.update('none');
    ids.forEach(id => {
      const el = document.getElementById('leg-' + id);
      if (el) el.textContent = anomalyStats[id] || 0;
    });
  }
}

function recordAnomaly(machineId, level) {
  const ids = ['M001','M002','M003','M004'];
  if (!ids.includes(machineId)) return;
  const t = new Date().toLocaleTimeString('en-GB');
  anomalyLog.unshift({ t, id: machineId, level });
  if (anomalyLog.length > 20) anomalyLog.pop();

  const colors = { alert:'var(--accent2)', warn:'var(--warn)', ok:'var(--ok)' };
  document.getElementById('an-list').innerHTML = anomalyLog.slice(0,10).map(e =>
    `<div style="display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);min-width:60px;">${e.t}</span>
      <span style="color:${colors[e.level]};min-width:50px;">${e.level.toUpperCase()}</span>
      <span style="color:var(--text);">${e.id}</span>
    </div>`
  ).join('') || '<div style="color:var(--muted);padding:8px 0;">No anomalies recorded yet.</div>';
}

// Patch updateMachine to record anomalies
const _origUpdateM = window.updateMachine;
window.updateMachine = function(d) {
  const prevRow = document.getElementById('row-' + d.machine_id);
  const prevLevel = prevRow ? (prevRow.classList.contains('s-alert') ? 'alert' : prevRow.classList.contains('s-warn') ? 'warn' : 'ok') : 'ok';
  _origUpdateM(d);
  const newRow = document.getElementById('row-' + d.machine_id);
  const newLevel = newRow ? (newRow.classList.contains('s-alert') ? 'alert' : newRow.classList.contains('s-warn') ? 'warn' : 'ok') : 'ok';
  latestLevels[d.machine_id] = newLevel;
  updateAnalyticsFromState();
  if (newLevel !== 'ok' && newLevel !== prevLevel) recordAnomaly(d.machine_id, newLevel);
};

// ==================== SYSTEM STATUS (mini) ====================
let miniOnline = false;

async function loadMiniStatus() {
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 4000);
    const res = await fetch('http://localhost:8005/system/health', { signal: controller.signal });
    const data = await res.json();
    const overall = data.overall || 'unknown';
    miniOnline = true;

    const dot = document.getElementById('sys-dot');
    const ov  = document.getElementById('sys-overall');
    const det = document.getElementById('sys-detail');
    const comp = document.getElementById('sys-components');
    const colors = { ok:'var(--ok)', degraded:'var(--warn)', error:'var(--accent2)' };
    const labels = { ok:'All systems operational', degraded:'Some services degraded', error:'Connection errors detected' };
    if (dot) { dot.style.background = colors[overall] || 'var(--muted)'; dot.style.boxShadow = `0 0 8px ${colors[overall] || 'var(--muted)'}`; }
    if (ov)  ov.textContent = labels[overall] || 'Unknown';
    if (det) {
      const comps = Object.entries(data.components || {});
      const errs = comps.filter(([,v]) => v.status !== 'ok');
      det.textContent = errs.length ? `Issues: ${errs.map(([k])=>k).join(', ')}` : `${comps.length} components checked - all healthy`;
    }
    if (comp) {
      comp.innerHTML = Object.entries(data.components || {}).map(([name, info]) => {
        const c = colors[info.status] || 'var(--muted)';
        return `<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 16px;display:flex;align-items:center;justify-content:space-between;">
          <span style="font-size:12px;">${name}</span>
          <span style="font-family:var(--font-mono);font-size:10px;color:${c};">${info.status.toUpperCase()} - ${info.detail || ''}</span>
        </div>`;
      }).join('');
    }
  } catch(e) {
    miniOnline = false;
    const ov  = document.getElementById('sys-overall');
    const det = document.getElementById('sys-detail');
    const dot = document.getElementById('sys-dot');
    if (dot) { dot.style.background = 'var(--muted)'; dot.style.boxShadow = 'none'; }
    if (ov)  ov.textContent = 'Backend offline';
  if (det) det.textContent = 'Cannot reach main.py - retrying...';
  } finally {
    setTimeout(loadMiniStatus, 3000); // poll every 3s
  }
}
loadMiniStatus();

// ==================== PROFILE ====================
function saveProfile() {
  const name = document.getElementById('inp-name')?.value || 'Operator';
  document.getElementById('prof-name').textContent = name;
  const saved = document.getElementById('prof-saved');
  if (saved) { saved.style.display = 'block'; setTimeout(() => saved.style.display = 'none', 2000); }
}

// ==================== INIT BAR CHART ====================
// Load Chart.js then init
const chartScript = document.createElement('script');
chartScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js';
chartScript.onload = () => { initChart(); initBarChart(); };
document.head.appendChild(chartScript);
