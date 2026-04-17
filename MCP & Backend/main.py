"""
main.py  —  AnomalyIQ Unified Backend
======================================
Put this file inside:  MCP & Backend/main.py

Folder structure expected:
  MCP & Backend/
  ├── main.py          ← this file
  ├── backend.py       ← your original backend (kept for reference)
  ├── mcp-server.py    ← your MCP server
  └── Anomaly Detector/
      └── ingesting.py ← original ingesting script

  Agents/
  ├── audit_agent.py
  └── coordinator_agent.py

Run:
    cd "MCP & Backend"
    python main.py
"""

import sys
import os
import asyncio
import threading
import uvicorn
import httpx
import json
import sqlite3

from uuid import uuid4
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── Add Agents/ to path so we can import audit_agent, coordinator_agent ───────
REPO_ROOT  = Path(__file__).resolve().parent.parent   # AnomalyIQ/
AGENTS_DIR = REPO_ROOT / "Agents"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENTS_DIR))

# ── Config ────────────────────────────────────────────────────────────────────
STREAMING_URL = os.getenv("STREAMING_URL", "http://localhost:8000")
MCP_URL       = os.getenv("mcp_server_ip", "http://localhost:8080")

# ── Job queue (same pattern as original backend.py) ───────────────────────────
_jobs: dict[str, dict] = {}
_job_queue: asyncio.Queue = None

# ── Ingesting thread state ────────────────────────────────────────────────────
_ingest_running = False
_latest_readings: dict[str, dict] = {}


# ── Ingesting background thread ───────────────────────────────────────────────
def _start_ingesting():
    global _ingest_running
    _ingest_running = True

    # Try to import from Anomaly Detector folder
    ingest_path = Path(__file__).parent / "Anomaly Detector" / "ingesting.py"
    if not ingest_path.exists():
        # Try alternate location
        ingest_path = REPO_ROOT / "Data streaming simulator" / "ingesting.py"

    if ingest_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("ingesting", str(ingest_path))
        ing  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ing)
        print(f"[MAIN] Ingesting started from {ingest_path}")
        if hasattr(ing, "run_ingest_loop"):
            ing.run_ingest_loop()
        else:
            print("[MAIN] ingesting.py has no run_ingest_loop() — skipping")
    else:
        print(f"[MAIN] ingesting.py not found — skipping ingest thread")

    _ingest_running = False


# ── Workers ───────────────────────────────────────────────────────────────────
async def _worker(worker_id: int):
    print(f"[WORKER {worker_id}] Ready")
    while True:
        job_id, coro_fn = await _job_queue.get()
        _jobs[job_id] = {"status": "processing"}
        try:
            result = await coro_fn()
            _jobs[job_id] = {"status": "done", "result": result}
        except Exception as e:
            _jobs[job_id] = {"status": "error", "detail": str(e)}
        finally:
            _job_queue.task_done()


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _job_queue

    # Start job queue + workers
    _job_queue = asyncio.Queue(maxsize=200)
    for i in range(2):
        asyncio.create_task(_worker(i))

    # Start ingesting thread
    t = threading.Thread(target=_start_ingesting, daemon=True)
    t.start()

    print("[MAIN] AnomalyIQ backend ready on http://localhost:8005")
    print("[MAIN] Open your HTML files in the browser to use the UI")

    yield

    print("[MAIN] Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="AnomalyIQ Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
app.mount("/ui", StaticFiles(directory=r"C:\Users\jiang\AnomalyIQ\Frontend", html=True), name="ui")

# ═════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════

# ── Request models ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    machine_id: str
    question:   str
    session_id: Optional[str] = None

class AnomalyAlert(BaseModel):
    machine_id:   str
    machine_type: str
    label:        str
    confidence:   float
    visual_url:   list[str]

class QARequest(BaseModel):
    machine_id: str
    question:   str


# ── GET /health ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": _job_queue.qsize() if _job_queue else 0}


# ── POST /chat  (from UI chat panel) ─────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued"}

    async def run():
        from coordinator_agent import handle_qa_question
        return await handle_qa_question(
            machine_id = req.machine_id,
            question   = req.question,
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued"}


# ── POST /qa  (kept for backward compat with original backend.py) ─────────────
@app.post("/qa")
async def qa(request: QARequest):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued"}

    async def run():
        from coordinator_agent import handle_qa_question
        return await handle_qa_question(
            machine_id = request.machine_id,
            question   = request.question,
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued"}


# ── POST /anomaly  (called by CNN when anomaly detected) ──────────────────────
@app.post("/anomaly")
async def anomaly(alert: AnomalyAlert):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued"}

    async def run():
        from coordinator_agent import handle_anomaly_alert
        return await handle_anomaly_alert(
            machine_id   = alert.machine_id,
            machine_type = alert.machine_type,
            label        = alert.label,
            confidence   = alert.confidence,
            visual_url   = alert.visual_url,
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued"}


# ── GET /jobs/{job_id} ────────────────────────────────────────────────────────
@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── GET /machines/status ──────────────────────────────────────────────────────
@app.get("/machines/status")
async def machines_status():
    return {"machines": list(_latest_readings.values())}


# ── GET /machines/stream  (SSE proxy) ────────────────────────────────────────
@app.get("/machines/stream")
async def machines_stream():
    async def event_gen():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{STREAMING_URL}/stream") as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield f"{line}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── GET /audit/logs ───────────────────────────────────────────────────────────
@app.get("/audit/logs")
async def audit_logs(
    agent:     str = "",
    event:     str = "",
    sensor_id: str = "",
    limit:     int = 50,
):
    try:
        from audit_agent import query_logs
        res    = query_logs(agent=agent, event=event, sensor_id=sensor_id, limit=limit)
        result = res["result"]
        return {
            "count": result.count,
            "logs":  [log.model_dump() for log in result.logs],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /chat/sessions ────────────────────────────────────────────────────────
@app.get("/chat/sessions")
async def chat_sessions():
    db_path = os.getenv("ca_memory_db", "./data/conversations.db")
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        cur.execute(
            "SELECT DISTINCT session_id FROM message_store ORDER BY rowid DESC LIMIT 50"
        )
        sessions = [row[0] for row in cur.fetchall()]
        conn.close()
        return {"sessions": sessions}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


# ── GET /chat/history/{session_id} ───────────────────────────────────────────
@app.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    try:
        from langchain_community.chat_message_histories import SQLChatMessageHistory
        db_path = os.getenv("ca_memory_db", "./data/conversations.db")
        history = SQLChatMessageHistory(
            session_id        = session_id,
            connection_string = f"sqlite:///{db_path}",
        )
        messages = [
            {"role": msg.type, "content": msg.content}
            for msg in history.messages
        ]
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /system/health ────────────────────────────────────────────────────────
@app.get("/system/health")
async def system_health():
    results = {}

    async def ping(name: str, url: str, timeout: float = 3.0):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                results[name] = {
                    "status": "ok" if r.status_code < 400 else "degraded",
                    "detail": f"HTTP {r.status_code}",
                }
        except httpx.ConnectError:
            results[name] = {"status": "error", "detail": "Connection refused"}
        except httpx.TimeoutException:
            results[name] = {"status": "degraded", "detail": "Timeout"}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)}

    results["UI"]      = {"status": "ok",     "detail": "Frontend served"}
    results["Backend"] = {"status": "ok",     "detail": "Running"}

    await asyncio.gather(
        ping("Streaming", f"{STREAMING_URL}/data"),
        ping("MCP",       MCP_URL),
    )

    # PostgreSQL
    try:
        from audit_agent import _get_conn
        _get_conn()
        results["PostgreSQL"] = {"status": "ok", "detail": "Connected"}
    except Exception as e:
        results["PostgreSQL"] = {"status": "error", "detail": str(e)}

    # Qdrant
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:6333/healthz")
            results["Qdrant"] = {
                "status": "ok" if r.status_code == 200 else "degraded",
                "detail": f"HTTP {r.status_code}",
            }
    except Exception as e:
        results["Qdrant"] = {"status": "error", "detail": str(e)}

    # Data Simulator thread
    results["DataSimulator"] = {
        "status": "ok" if _ingest_running else "degraded",
        "detail": "Thread alive" if _ingest_running else "Not started",
    }

    statuses = [v["status"] for v in results.values()]
    overall  = "error" if "error" in statuses else "degraded" if "degraded" in statuses else "ok"

    return {"overall": overall, "components": results}


# ── GET /anomalies ────────────────────────────────────────────────────────────
@app.get("/anomalies")
async def anomalies(limit: int = 20):
    try:
        from audit_agent import query_logs
        res    = query_logs(event="anomaly_detected", limit=limit)
        result = res["result"]
        return {
            "count":     result.count,
            "anomalies": [log.model_dump() for log in result.logs],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=False)
