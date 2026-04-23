const BACKEND_URL = 'http://localhost:8005';

function tick(){const t=new Date().toLocaleTimeString('en-GB');const e=document.getElementById('clk');if(e)e.textContent=t;}
tick();setInterval(tick,1000);
const chatInitEl = document.getElementById('chatInitTime');
if (chatInitEl) chatInitEl.textContent = new Date().toLocaleTimeString('en-GB');
loadSessions();
setInterval(loadSessions, 5000);
let openSessionId = null;
function setTab(el){el.closest('.tabs').querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));el.classList.add('active');}
function toggleThread(id){document.getElementById(id).classList.toggle('open');}

// â”€â”€ Load real chat sessions from backend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function loadSessions() {
  try {
    const res  = await fetch(`${BACKEND_URL}/chat/sessions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const sessions = data.sessions || [];

    const container = document.querySelector('.vscroll');
    const label     = document.getElementById('sessionsLabel');
    if (!container) return;

    // Remove old cards and prior empty-state placeholders
    container.querySelectorAll('.hcard, .sessions-empty').forEach(c => c.remove());

    if (label) label.textContent = `Conversation Records - ${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

    if (sessions.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'sessions-empty';
      empty.style.cssText = 'color:var(--muted);font-family:var(--font-mono);font-size:10px;padding:12px 0;';
      empty.textContent = 'No chat sessions recorded yet. Sessions appear after first anomaly or chat.';
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
        <div class="hpreview" id="prev-${threadId}">Tap to load messages...</div>
        <div class="hfooter"><div class="hturns" id="turns-${threadId}">- turns</div><div style="flex:1"></div></div>
        <div class="hthread" id="${threadId}"></div>`;
      card.onclick = () => loadThread(sessionId, card);
      container.appendChild(card);

      if (openSessionId === sessionId) {
        await loadThread(sessionId, card, true);
      }
    }
  } catch(e) {
    const label = document.getElementById('sessionsLabel');
    if (label) label.textContent = 'Conversation Records - backend offline';
    console.log('Chat history load failed:', e.message);
  }
}

async function loadThread(sessionId, card, forceOpen = false) {
  const threadId = 'thread-' + sessionId.replace(/[^a-z0-9]/gi,'_');
  const thread   = document.getElementById(threadId);
  if (!thread) return;

  if (thread.classList.contains('open') && !forceOpen) {
    thread.classList.remove('open');
    openSessionId = null;
    return;
  }

  openSessionId = sessionId;

  thread.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">Loading...</div>';
  thread.classList.add('open');

  try {
    const res  = await fetch(`${BACKEND_URL}/chat/history/${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    const msgs = data.messages || [];

    const preview = document.getElementById(`prev-${threadId}`);
    const turns   = document.getElementById(`turns-${threadId}`);
    if (preview) preview.textContent = msgs.length ? msgs[0].content.substring(0,100) + '...' : 'No messages.';
    if (turns)   turns.textContent   = `${msgs.length} turns`;

    thread.innerHTML = msgs.length
      ? msgs.map(m => {
          const cls = m.role === 'human' ? 'user' : 'sys';
          return `<div class="hmsg ${cls}"><div class="hbubble">${m.content}</div><div class="hmeta">${m.role.toUpperCase()}</div></div>`;
        }).join('')
      : '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No messages in this session.</div>';

    if (msgs.length === 0) {
      thread.innerHTML = '<div style="font-family:var(--font-mono);font-size:10px;color:var(--muted);padding:8px 0;">No messages in this session.</div>';
    }
  } catch(e) {
    thread.innerHTML = `<div style="font-family:var(--font-mono);font-size:10px;color:var(--accent2);padding:8px 0;">Error loading: ${e.message}</div>`;
  }
}

// Try to load real sessions, fall back to mock if backend is offline
loadSessions();

// â”€â”€ Chat panel â€” real /qa endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
async function sendMsg(){const input=document.getElementById('chatInput');if(!input)return;const text=input.value.trim();if(!text)return;input.disabled=true;const btn=document.querySelector('.send-btn');if(btn)btn.disabled=true;appendMsg('user',text,`OPERATOR | ${nowStr()}`);input.value='';const typingEl=appendTyping();try{const res=await fetch(`${CA_URL}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({machine_id:currentMachineId,question:text,session_id:currentSessionId})});if(!res.ok){const err=await res.json().catch(()=>({}));typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN ${res.status}: ${err.detail||res.statusText}</span>`,`SYSTEM | ${nowStr()}`);return;}const data=await res.json();if(data.session_id)currentSessionId=data.session_id;if(!data.job_id){typingEl.remove();appendMsg('sys','<span style="color:var(--accent2)">WARN No job_id returned.</span>',`SYSTEM | ${nowStr()}`);return;}await pollJob(data.job_id,typingEl);await loadSessions();}catch(err){typingEl.remove();appendMsg('sys',`<span style="color:var(--accent2)">WARN Cannot reach backend: ${err.message}</span>`,`SYSTEM | ${nowStr()}`);}finally{input.disabled=false;if(btn)btn.disabled=false;input.focus();}}
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}

// Wire up the send button and textarea (static HTML doesn't have onclick)
document.addEventListener('DOMContentLoaded', () => {
  const btn   = document.querySelector('.send-btn');
  const input = document.getElementById('chatInput');
  if (btn)   btn.addEventListener('click', sendMsg);
  if (input) input.addEventListener('keydown', handleKey);
});
