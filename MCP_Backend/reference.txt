"""
routers/backend.py
Frontend-Facing API Routes
==========================
All endpoints the HTML frontend calls directly.

Routes:
  POST /chat                    ← send message to orchestrator
  GET  /jobs/{job_id}           ← poll job status (for chat responses)
  GET  /machines/status         ← latest sensor readings per machine
  GET  /machines/stream         ← SSE live data stream to frontend
  GET  /audit/logs              ← audit log page data
  GET  /chat/history/{session}  ← chat history page data
  GET  /system/health           ← system status page (pings all components)
  GET  /anomalies               ← list of past detected anomalies
"""

import asyncio
import httpx
import json
from uuid import uuid4
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter()

# ── In-memory job store (same pattern as original backend.py) ─────────────────
_jobs: dict[str, dict] = {}
_job_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

# Component URLs for health checks
STREAMING_URL = os.getenv("STREAMING_URL", "http://localhost:8000")
MCP_URL       = os.getenv("MCP_URL",       "http://localhost:8005/mcp")


# ── Worker (started by main.py lifespan via create_task) ─────────────────────
async def start_workers(n: int = 2):
    for i in range(n):
        asyncio.create_task(_worker(i))
        print(f"[BACKEND] Worker {i} started")

async def _worker(worker_id: int):
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


# ── Request models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    machine_id: str
    question:   str
    session_id: Optional[str] = None   # for conversation memory


# ── POST /chat ────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    """
    Send a question to the orchestrator (CA).
    Returns a job_id — poll GET /jobs/{job_id} for the result.
    """
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued", "position": _job_queue.qsize() + 1}

    async def run():
        from Agents.coordinator_agent import handle_qa_question
        return await handle_qa_question(
            machine_id = req.machine_id,
            question   = req.question,
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued"}


# ── GET /jobs/{job_id} ────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Poll job status. Returns status + result when done."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── GET /machines/status ──────────────────────────────────────────────────────

@router.get("/machines/status")
async def machines_status():
    """
    Returns the latest sensor reading for each active machine.
    Data comes from the in-memory state maintained by the ingesting service.
    """
    try:
        from services.ingesting import get_latest_readings
        return {"machines": get_latest_readings()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /machines/stream ──────────────────────────────────────────────────────

@router.get("/machines/stream")
async def machines_stream():
    """
    SSE proxy — forwards the live data stream from streaming.py to the frontend.
    Frontend can subscribe to this for real-time sensor updates.
    """
    async def event_gen():
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("GET", f"{STREAMING_URL}/stream") as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield f"{line}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── GET /audit/logs ───────────────────────────────────────────────────────────

@router.get("/audit/logs")
async def audit_logs(
    agent:     str = "",
    event:     str = "",
    sensor_id: str = "",
    limit:     int = 50,
):
    """
    Returns structured audit log entries for the Audit Log page.
    Supports optional filtering by agent, event type, or sensor/machine ID.
    """
    try:
        from Agents.audit_agent import query_logs
        res = query_logs(
            agent     = agent,
            event     = event,
            sensor_id = sensor_id,
            limit     = limit,
        )
        result = res["result"]
        return {
            "count": result.count,
            "logs":  [log.model_dump() for log in result.logs],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /chat/history/{session_id} ───────────────────────────────────────────

@router.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    """
    Returns conversation history for a given session from CA's SQLite memory.
    Used by the Chat History page.
    """
    try:
        from langchain_community.chat_message_histories import SQLChatMessageHistory
        history = SQLChatMessageHistory(
            session_id      = session_id,
            connection_string = "sqlite:///conversations.db",
        )
        messages = [
            {
                "role":    msg.type,          # "human" or "ai"
                "content": msg.content,
            }
            for msg in history.messages
        ]
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/sessions")
async def chat_sessions():
    """
    Returns a list of all session IDs that have conversation history.
    Used to populate the Chat History page session list.
    """
    try:
        import sqlite3
        conn = sqlite3.connect("conversations.db")
        cur  = conn.cursor()
        cur.execute(
            "SELECT DISTINCT session_id FROM message_store ORDER BY rowid DESC LIMIT 50"
        )
        sessions = [row[0] for row in cur.fetchall()]
        conn.close()
        return {"sessions": sessions}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


# ── GET /system/health ────────────────────────────────────────────────────────

@router.get("/system/health")
async def system_health():
    """
    Pings all system components and returns their connection status.
    Used by the System Status page.
    Status: "ok" | "degraded" | "error"
    """
    results = {}

    async def ping(name: str, url: str, timeout: float = 3.0):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                if r.status_code < 400:
                    results[name] = {"status": "ok",      "latency_ms": None}
                else:
                    results[name] = {"status": "degraded","detail": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            results[name] = {"status": "error", "detail": "Connection refused"}
        except httpx.TimeoutException:
            results[name] = {"status": "degraded", "detail": "Timeout"}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)}

    # UI is always reachable if this endpoint responds
    results["UI"] = {"status": "ok", "detail": "Frontend served"}

    # Check all backend components in parallel
    await asyncio.gather(
        ping("Streaming",      f"{STREAMING_URL}/data"),
        ping("MCP",            f"{MCP_URL}/health" if "health" in MCP_URL else MCP_URL),
        ping("Backend",        "http://localhost:8005/docs"),
    )

    # Check PostgreSQL via audit_agent
    try:
        from Agents.audit_agent import _get_conn
        _get_conn()
        results["PostgreSQL"] = {"status": "ok", "detail": "Connected"}
    except Exception as e:
        results["PostgreSQL"] = {"status": "error", "detail": str(e)}

    # Check Qdrant
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:6333/healthz")
            results["Qdrant"] = {
                "status": "ok" if r.status_code == 200 else "degraded",
                "detail": f"HTTP {r.status_code}",
            }
    except Exception as e:
        results["Qdrant"] = {"status": "error", "detail": str(e)}

    # Check ingesting thread
    try:
        from services.ingesting import is_running
        results["DataSimulator"] = {
            "status": "ok" if is_running() else "degraded",
            "detail": "Thread alive" if is_running() else "Thread not running",
        }
    except Exception as e:
        results["DataSimulator"] = {"status": "error", "detail": str(e)}

    # Overall status = worst of all
    statuses = [v["status"] for v in results.values()]
    if "error"    in statuses: overall = "error"
    elif "degraded" in statuses: overall = "degraded"
    else:                        overall = "ok"

    return {"overall": overall, "components": results}


# ── GET /anomalies ────────────────────────────────────────────────────────────

@router.get("/anomalies")
async def anomalies(limit: int = 20):
    """
    Returns list of past detected anomalies with their visual chart paths.
    Sourced from audit logs filtered by event = 'anomaly_detected'.
    """
    try:
        from Agents.audit_agent import query_logs
        res    = query_logs(event="anomaly_detected", limit=limit)
        result = res["result"]
        return {
            "count":     result.count,
            "anomalies": [log.model_dump() for log in result.logs],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /health (simple liveness check) ──────────────────────────────────────

@router.get("/health")
async def health():
    """Simple liveness check — returns ok if backend is running."""
    return {
        "status":     "ok",
        "queue_size": _job_queue.qsize(),
    }
