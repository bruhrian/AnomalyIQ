const BACKEND_URL = 'http://localhost:8005';
document.getElementById('chatMsgs')?.replaceChildren();

function tick(){const t=new Date().toLocaleTimeString('en-GB');const e=document.getElementById('clk');if(e)e.textContent=t;}
tick();setInterval(tick,1000);
loadSessions();
setInterval(loadSessions, 10000);
function setTab(el){el.closest('.tabs').querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));el.classList.add('active');}
function toggleThread(id){document.getElementById(id).classList.toggle('open');}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function displayHistoryContent(message) {
  let content = String(message?.content ?? '');
  if (message?.role === 'human') {
    content = content.split('\n\nBackend context:')[0];
    content = content.replace(/^\[Machine:\s*([^\]]+)\]\s*/i, '');
  }
  return content;
}

function summarizeSessionMessages(messages) {
  const userMsgs = messages.filter(m => String(m.role).toLowerCase() === 'human');
  const aiMsgs = messages.filter(m => String(m.role).toLowerCase() !== 'human');
  return {
    latestUser: userMsgs.length ? displayHistoryContent(userMsgs[userMsgs.length - 1]) : 'No user prompt yet.',
    latestAI: aiMsgs.length ? displayHistoryContent(aiMsgs[aiMsgs.length - 1]) : 'No assistant response yet.'
  };
}

// â”€â”€ Load real chat sessions from backend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function loadSessions() {
  try {
    const res  = await fetch(`${BACKEND_URL}/chat/sessions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const sessions = (data.sessions || []).filter(sessionId => !/^anomaly-/i.test(String(sessionId)));

    const container = document.querySelector('.vscroll');
    const label     = document.getElementById('sessionsLabel');
    if (!container) return;

    // Remove old cards
    container.querySelectorAll('.hcard').forEach(c => c.remove());

    if (label) label.textContent = `Conversation Records - ${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

    if (sessions.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'color:var(--muted);font-family:var(--font-mono);font-size:10px;padding:12px 0;';
      empty.textContent = 'No user chat sessions recorded yet.';
      container.appendChild(empty);
      return;
    }

    for (const sessionId of sessions) {
      const threadId = 'thread-' + sessionId.replace(/[^a-z0-9]/gi,'_');
      const card = document.createElement('div');
      card.className = 'hcard';
      card.innerHTML = `
        <div class="hcard-top">
          <div class="htag">${sessionId}</div>
          <div class="htime">tap to load</div>
        </div>
        <div class="hpreview" id="prev-${threadId}">Loading preview...</div>
        <div class="hfooter"><div class="hturns" id="turns-${threadId}">-- turns</div><div style="flex:1"></div></div>
        <div class="hthread" id="${threadId}"></div>`;
      card.onclick = () => loadThread(sessionId, card);
      container.appendChild(card);

      try {
        const histRes = await fetch(`${BACKEND_URL}/chat/history/${encodeURIComponent(sessionId)}`);
        if (histRes.ok) {
          const histData = await histRes.json();
          const msgs = histData.messages || [];
          const summary = summarizeSessionMessages(msgs);
          const preview = document.getElementById(`prev-${threadId}`);
          const turns = document.getElementById(`turns-${threadId}`);
          if (preview) {
            preview.innerHTML = `
              <div style="display:flex;flex-direction:column;gap:6px;">
                <div><span style="color:var(--muted);font-family:var(--font-mono);font-size:9px;">Latest user</span><div>${escapeHtml(summary.latestUser).slice(0, 120)}</div></div>
                <div><span style="color:var(--muted);font-family:var(--font-mono);font-size:9px;">Latest assistant</span><div>${escapeHtml(summary.latestAI).slice(0, 140)}</div></div>
              </div>`;
          }
          if (turns) turns.textContent = `${msgs.length} turns`;
        }
      } catch (_) {}
    }
  } catch(e) {
    const label = document.getElementById('sessionsLabel');
    if (label) label.textContent = 'Conversation Records - backend offline';
    console.log('Chat history load failed:', e.message);
  }
}

async function loadThread(sessionId, card) {
  const threadId = 'thread-' + sessionId.replace(/[^a-z0-9]/gi,'_');
  const thread   = document.getElementById(threadId);
  if (!thread) return;

  if (thread.classList.contains('open')) {
    thread.classList.remove('open');
    return;
  }

  thread.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">Loading...</div>';
  thread.classList.add('open');

  try {
    const res  = await fetch(`${BACKEND_URL}/chat/history/${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    const msgs = data.messages || [];

    const preview = document.getElementById(`prev-${threadId}`);
    const turns   = document.getElementById(`turns-${threadId}`);
    const summary = summarizeSessionMessages(msgs);
    if (preview) {
      preview.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:6px;">
          <div><span style="color:var(--muted);font-family:var(--font-mono);font-size:9px;">Latest user</span><div>${escapeHtml(summary.latestUser).slice(0, 120)}</div></div>
          <div><span style="color:var(--muted);font-family:var(--font-mono);font-size:9px;">Latest assistant</span><div>${escapeHtml(summary.latestAI).slice(0, 140)}</div></div>
        </div>`;
    }
    if (turns)   turns.textContent   = `${msgs.length} turns`;

    thread.innerHTML = msgs.length
      ? msgs.map(m => {
          const cls = m.role === 'human' ? 'user' : 'sys';
          const rendered = cls === 'user' ? escapeHtml(displayHistoryContent(m)) : renderRichText(displayHistoryContent(m));
          return `<div class="hmsg ${cls}"><div class="hbubble">${rendered}</div><div class="hmeta">${escapeHtml(m.role.toUpperCase())}</div></div>`;
        }).join('')
      : '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No messages in this session.</div>';

    if (msgs.length === 0) {
      thread.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No messages in this session.</div>';
    }
  } catch(e) {
    thread.innerHTML = `<div style="font-family:var(--font-mono);font-size:10px;color:var(--accent2);padding:8px 0;">Error loading: ${e.message}</div>`;
  }
}

// â”€â”€ Chat panel â€” real /qa endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const CA_URL = 'http://localhost:8005';
const POLL_MS = 1500;
const POLL_TIMEOUT = 130000;
let currentMachineId = '';
let currentSessionId = null;

function nowStr(){return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function appendMsg(cls,html,meta){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className=`msg ${cls}`;el.innerHTML=`<div class="bubble">${html}</div><div class="msg-meta">${meta}</div>`;msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function appendTyping(){const msgs=document.getElementById('chatMsgs');if(!msgs)return;const el=document.createElement('div');el.className='msg sys';el.innerHTML='<div class="typing-wrap"><span></span><span></span><span></span></div>';msgs.appendChild(el);msgs.scrollTop=msgs.scrollHeight;return el;}
function formatResult(r){if(typeof r==='string')return r;let h='';if(r.Impact_analysis)h+=`<strong>Impact Analysis</strong><br>${r.Impact_analysis}<br><br>`;if(r.cascade_effects&&r.cascade_effects.length){h+='<strong>Cascade Effects</strong><br>';r.cascade_effects.forEach((e,i)=>{const l=['Immediate','Short-term','Long-term'];h+=`- ${l[i]||i+1}: ${e}<br>`;});h+='<br>';}if(r.solutions)h+=`<strong>Recommended Action</strong><br>${r.solutions}`;if(r.sources&&r.sources.length)h+=`<br><br><span style="font-size:10px;color:var(--muted);">Sources: ${r.sources.join(', ')}</span>`;return h||JSON.stringify(r,null,2);}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result?.result??data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">Request timed out while waiting for the backend response.</span>',`SYSTEM · ${nowStr()}`);}
async function sendMsg(){
  const input = document.getElementById('chatInput');
  if(!input) return;
  let text = input.value.trim();
  if(!text) return;
  
  // ç¡®ä¿ text æ˜¯å­—ç¬¦ä¸²ï¼Œä¸æ˜¯å¯¹è±¡
  text = String(text);
  
  input.disabled=true;
  const btn=document.querySelector('.send-btn');
  if(btn) btn.disabled=true;
  appendMsg('user', text, `OPERATOR · ${nowStr()}`);
  input.value='';
  const typingEl=appendTyping();
  
  try{
    // æ˜Žç¡®æž„é€ è¦å‘é€çš„å¯¹è±¡ï¼Œç¡®ä¿æ²¡æœ‰é¢å¤–å±žæ€§
    const payload = {
      machine_id: String(currentMachineId || ''),
      question: text,
      session_id: currentSessionId
    };
    // å¦‚æžœåŽç«¯æ”¯æŒ session_idï¼Œå¯ä»¥åŠ ä¸Šï¼ˆå¯é€‰ï¼‰
    // payload.session_id = "chat-history-" + Date.now();
    
    const res=await fetch(`${CA_URL}/chat`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    
    if(!res.ok){
      const err=await res.json().catch(()=>({}));
      typingEl.remove();
      appendMsg('sys',`<span style="color:var(--accent2)">${res.status}: ${err.detail||res.statusText}</span>`,`SYSTEM · ${nowStr()}`);
      return;
    }
    const data=await res.json();
    if(data.session_id) currentSessionId = data.session_id;
    if(!data.job_id){
      typingEl.remove();
      appendMsg('sys','<span style="color:var(--accent2)">No job_id returned.</span>',`SYSTEM · ${nowStr()}`);
      return;
    }
    await pollJob(data.job_id, typingEl);
    await loadSessions();
  } catch(err){
    typingEl.remove();
    appendMsg('sys',`<span style="color:var(--accent2)">Cannot reach backend: ${err.message}</span>`,`SYSTEM · ${nowStr()}`);
  } finally{
    input.disabled=false;
    if(btn) btn.disabled=false;
    input.focus();
  }
}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}

// Wire up the send button and textarea (static HTML doesn't have onclick)
document.addEventListener('DOMContentLoaded', () => {
  const btn   = document.querySelector('.send-btn');
  const input = document.getElementById('chatInput');
  if (btn)   btn.addEventListener('click', sendMsg);
  if (input) input.addEventListener('keydown', handleKey);
});

// Unified rich answer renderer
function escapeHtml(text){return String(text??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function formatInlineMarkdown(text){return escapeHtml(text).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-family:var(--font-mono);font-size:.95em;">$1</code>');}
function renderTableBlock(lines){const rows=lines.map(line=>line.trim()).filter(Boolean).map(line=>line.split('|').map(cell=>cell.trim()).filter((cell,idx,arr)=>!(idx===0&&cell==='')&&!(idx===arr.length-1&&cell==='')));if(rows.length<2)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;const [header,...body]=rows.filter(row=>!row.every(cell=>/^:?-{3,}:?$/.test(cell)));if(!header||!body.length)return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;return `<div style="overflow:auto;margin:0 0 14px 0;"><table style="width:100%;border-collapse:collapse;font-size:12px;color:var(--text);"><thead><tr>${header.map(cell=>`<th style="text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);color:var(--muted);font-family:var(--font-mono);font-size:10px;letter-spacing:.04em;text-transform:uppercase;">${formatInlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${body.map(row=>`<tr>${header.map((_,idx)=>`<td style="padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:top;">${formatInlineMarkdown(row[idx]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function renderRichText(text){const normalized=String(text??'').replace(/\r\n/g,'\n').trim();if(!normalized)return '';const blocks=normalized.split(/\n\s*\n/);return blocks.map(block=>{const lines=block.split('\n').map(line=>line.trim()).filter(Boolean);if(!lines.length)return '';if(lines.some(line=>/\|/.test(line))&&lines.length>=2){return renderTableBlock(lines);}if(lines.every(line=>/^[-*•]\s+/.test(line))){return `<ul style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^[-*•]\s+/,''))}</li>`).join('')}</ul>`;}if(lines.every(line=>/^\d+[.)]\s+/.test(line))){return `<ol style="margin:0 0 14px 18px;padding:0;color:var(--text);">${lines.map(line=>`<li style="margin:0 0 8px 0;padding-left:4px;">${formatInlineMarkdown(line.replace(/^\d+[.)]\s+/,''))}</li>`).join('')}</ol>`;}if(lines.length===1&&/^#{1,4}\s+/.test(lines[0])){const level=Math.min(4,(lines[0].match(/^#+/)||['#'])[0].length);const size={1:22,2:19,3:16,4:14}[level];return `<div style="margin:2px 0 10px 0;font-size:${size}px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/^#{1,4}\s+/,''))}</div>`;}if(lines.length===1&&/^[A-Za-z][A-Za-z /&-]{2,}:\s*$/.test(lines[0])){return `<div style="margin:2px 0 8px 0;font-size:15px;font-weight:700;color:var(--text);">${formatInlineMarkdown(lines[0].replace(/:\s*$/,''))}</div>`;}return `<p style="margin:0 0 14px 0;color:var(--text);line-height:1.65;">${formatInlineMarkdown(lines.join(' '))}</p>`;}).join('');}
function renderSection(title,body){if(!body)return '';return `<div style="margin:0 0 16px 0;"><div style="font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px;">${escapeHtml(title)}</div>${renderRichText(body)}</div>`;}
function formatVisuals(result){const urls=[];if(result?.visuals?.line_plot)urls.push({label:'Line Chart',url:result.visuals.line_plot});if(result?.visuals?.heatmap)urls.push({label:'Heatmap',url:result.visuals.heatmap});if(!urls.length&&Array.isArray(result?.visual_url)){result.visual_url.forEach((url,i)=>urls.push({label:i===0?'Line Chart':i===1?'Heatmap':`Visual ${i+1}`,url}));}if(!urls.length)return '';return `<div style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;">${urls.map(v=>`<a href="${v.url}" target="_blank" style="display:block;text-decoration:none;color:var(--text);"><div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:4px;">${v.label}</div><img src="${v.url}" alt="${v.label}" style="width:100%;max-height:180px;object-fit:cover;border:1px solid var(--border);border-radius:6px;background:var(--surface2);" /></a>`).join('')}</div>`;}
function formatResult(result){if(typeof result==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(result)}</div>`;const payload=result?.result??result;if(typeof payload==='string')return `<div style="display:flex;flex-direction:column;gap:2px;">${renderRichText(payload)}${formatVisuals(result)}</div>`;let html='';html+=renderSection('Impact Analysis',payload.Impact_analysis);if(payload.cascade_effects&&payload.cascade_effects.length){const labels=['Immediate','Short-term','Long-term'];const cascadeText=payload.cascade_effects.map((e,i)=>`- ${labels[i]||i+1}: ${e}`).join('\n');html+=renderSection('Cascade Effects',cascadeText);}html+=renderSection('Recommended Action',payload.solutions);if(payload.sources&&payload.sources.length){html+=`<div style="margin-top:8px;font-size:11px;color:var(--muted);">Sources: ${payload.sources.map(escapeHtml).join(', ')}</div>`;}if(!html)html=renderRichText(JSON.stringify(payload,null,2));return `<div style="display:flex;flex-direction:column;gap:2px;">${html}${formatVisuals(result)}</div>`;}
async function pollJob(jobId,typingEl){const deadline=Date.now()+POLL_TIMEOUT;while(Date.now()<deadline){await new Promise(r=>setTimeout(r,POLL_MS));try{const res=await fetch(`${CA_URL}/jobs/${jobId}`);if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();if(data.status==='done'){typingEl.remove();appendMsg('sys',formatResult(data.result),`SYSTEM · ${nowStr()}`);return;}if(data.status==='error'){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${data.detail||'Error'}</span>`,`SYSTEM · ${nowStr()}`);return;}}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">${err.message}</span>`,`SYSTEM · ${nowStr()}`);return;}}typingEl.remove();appendMsg('sys','<span style="color:var(--warn)">Request timed out while waiting for the backend response.</span>',`SYSTEM · ${nowStr()}`);}
