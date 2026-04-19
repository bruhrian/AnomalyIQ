import sys
import os
import asyncio
import threading
import json
import importlib.util

from uuid import uuid4
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT  = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "Agents"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENTS_DIR))

from orchestrator import orchestrator_response
from audit_agent import query_logs, _get_conn
from langchain_community.chat_message_histories import SQLChatMessageHistory

STREAMING_URL = os.getenv("STREAMING_URL")
MCP_URL       = os.getenv("mcp_server_ip")
AGENTS_DB     = os.getenv("agents_memory")
FRONTEND_DIR  = os.getenv("FRONTEND_DIR")

if not STREAMING_URL:
    raise ValueError("❌ STREAMING_URL not set in .env")
if not AGENTS_DB:
    raise ValueError("❌ agents_memory not set in .env")
if not FRONTEND_DIR:
    raise ValueError("❌ FRONTEND_DIR not set in .env")

print(f"✅ STREAMING_URL: {STREAMING_URL}")
if MCP_URL:
    print(f"✅ MCP_URL: {MCP_URL}")
else:
    print(f"ℹ️  MCP_URL not set (using stdio mode)")
print(f"✅ AGENTS_DB loaded.")
print(f"✅ FRONTEND_DIR: {FRONTEND_DIR}")

_jobs:          dict[str, dict] = {}
_job_queue:     asyncio.Queue   = None
_ingest_running                  = False


def _start_ingesting():
    global _ingest_running
    _ingest_running = True

    ingest_path = Path(__file__).parent / "Anomaly Detector" / "ingesting.py"
    if ingest_path.exists():
        spec = importlib.util.spec_from_file_location("ingesting", str(ingest_path))
        ing  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ing)
        print(f"✅ Ingesting started from {ingest_path}")
        if hasattr(ing, "run_ingest_loop"):
            ing.run_ingest_loop()
        else:
            print("❌ ingesting.py has no run_ingest_loop()")
    else:
        print(f"❌ ingesting.py not found at {ingest_path}")

    _ingest_running = False


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _job_queue

    _job_queue = asyncio.Queue(maxsize=200)
    for i in range(2):
        asyncio.create_task(_worker(i))

    threading.Thread(target=_start_ingesting, daemon=True).start()

    print(f"✅ AnomalyIQ backend ready — http://localhost:8005")
    print(f"✅ UI at http://localhost:8005/ui/1-dashboard.html")

    yield

    print("AnomalyIQ shutting down.")


app = FastAPI(title="AnomalyIQ Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")


class AnomalyAlert(BaseModel):
    machine_id:   str
    machine_type: str
    label:        str
    confidence:   float
    visual_url:   list[str]

class QARequest(BaseModel):
    machine_id: str
    question:   str

class ChatRequest(BaseModel):
    machine_id: str
    question:   str
    session_id: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": _job_queue.qsize() if _job_queue else 0}


@app.post("/anomaly")
async def anomaly(alert: AnomalyAlert):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued", "position": _job_queue.qsize() + 1}
    print(f"[CA] Anomaly received — machine: {alert.machine_id} | job: {job_id}")

    async def run():
        query = (
            f"ANOMALY ALERT — Machine {alert.machine_id} ({alert.machine_type})\n"
            f"Label: {alert.label} | Confidence: {alert.confidence:.1%}\n"
            f"Visuals: {', '.join(alert.visual_url) if alert.visual_url else 'none'}\n\n"
            f"Please analyse this anomaly, explain the root cause, cascade effects, and recommended actions."
        )
        return await orchestrator_response(query=query, session_id=f"anomaly-{alert.machine_id}")

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued", "position": _job_queue.qsize()}


@app.post("/qa")
async def qa(request: QARequest):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued", "position": _job_queue.qsize() + 1}
    print(f"[CA] QA received — machine: {request.machine_id} | job: {job_id}")

    async def run():
        return await orchestrator_response(
            query      = f"[Machine: {request.machine_id}] {request.question}",
            session_id = f"machine-{request.machine_id}",
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued", "position": _job_queue.qsize()}


@app.post("/chat")
async def chat(req: ChatRequest):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued"}

    async def run():
        return await orchestrator_response(
            query      = f"[Machine: {req.machine_id}] {req.question}",
            session_id = req.session_id or f"machine-{req.machine_id}",
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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


@app.get("/audit/logs")
async def audit_logs(agent: str = "", event: str = "", sensor_id: str = "", limit: int = 50):
    try:
        res    = query_logs(agent=agent, event=event, sensor_id=sensor_id, limit=limit)
        result = res["result"]
        return {"count": result.count, "logs": [log.model_dump() for log in result.logs]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/sessions")
async def chat_sessions():
    try:
        history  = SQLChatMessageHistory(session_id="__probe__", connection_string=AGENTS_DB)
        conn     = history.connection
        result   = conn.execute("SELECT DISTINCT session_id FROM message_store ORDER BY id DESC LIMIT 50")
        sessions = [row[0] for row in result.fetchall()]
        return {"sessions": sessions}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


@app.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    try:
        history  = SQLChatMessageHistory(session_id=session_id, connection_string=AGENTS_DB)
        messages = [{"role": msg.type, "content": msg.content} for msg in history.messages]
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/system/health")
async def system_health():
    results = {}

    async def ping(name: str, url: str, timeout: float = 3.0):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                results[name] = {"status": "ok" if r.status_code < 400 else "degraded", "detail": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            results[name] = {"status": "error", "detail": "Connection refused"}
        except httpx.TimeoutException:
            results[name] = {"status": "degraded", "detail": "Timeout"}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)}

    results["UI"]      = {"status": "ok", "detail": "Frontend served"}
    results["Backend"] = {"status": "ok", "detail": "Running"}

    tasks = [ping("Streaming", f"{STREAMING_URL}/data")]
    if MCP_URL:
        tasks.append(ping("MCP", MCP_URL.replace("/mcp", "").replace("/sse", "") + "/docs"))
    await asyncio.gather(*tasks)

    try:
        _get_conn()
        results["PostgreSQL"] = {"status": "ok", "detail": "Connected"}
    except Exception as e:
        results["PostgreSQL"] = {"status": "error", "detail": str(e)}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            neo4j_url = os.getenv("NEO4J_URI", "http://localhost:7687")
            r = await client.get(neo4j_url)
            results["Neo4j"] = {"status": "ok" if r.status_code < 400 else "degraded", "detail": f"HTTP {r.status_code}"}
    except Exception as e:
        results["Neo4j"] = {"status": "error", "detail": str(e)}

    results["DataSimulator"] = {
        "status": "ok" if _ingest_running else "degraded",
        "detail": "Thread alive" if _ingest_running else "Not started",
    }

    statuses = [v["status"] for v in results.values()]
    overall  = "error" if "error" in statuses else "degraded" if "degraded" in statuses else "ok"

    return {"overall": overall, "components": results}


@app.get("/anomalies")
async def anomalies(limit: int = 20):
    try:
        res    = query_logs(event="anomaly_detected", limit=limit)
        result = res["result"]
        return {"count": result.count, "anomalies": [log.model_dump() for log in result.logs]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    agent_mcp.run(transport="http", host="0.0.0.0", port=8080)