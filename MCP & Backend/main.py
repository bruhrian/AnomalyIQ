import sys
import os
import asyncio
import threading
import json
import asyncio
import importlib.util
import time
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
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
REPO_ROOT  = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "Agents"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENTS_DIR))

from orchestrator import orchestrator_response
from Agents.audit_agent import query_logs, _get_conn
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
_chat_queue:    asyncio.Queue   = None
_ingest_running                  = False
_latest_machine_state: dict[str, dict] = {}


def _machine_state_key(machine_id: str, machine_type: str) -> str:
    return f"{machine_id}::{machine_type}"


def _start_ingesting():
    global _ingest_running
    _ingest_running = True

    ingest_path = Path(os.getenv('ingesting', ''))
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


async def _worker(worker_id: int, queue: asyncio.Queue, queue_name: str):
    print(f"[WORKER {queue_name}-{worker_id}] Ready")
    while True:
        job_id, coro_fn = await queue.get()
        _jobs[job_id] = {"status": "processing", "queue": queue_name}
        try:
            result = await coro_fn()
            _jobs[job_id] = {"status": "done", "result": result, "queue": queue_name}
        except Exception as e:
            _jobs[job_id] = {"status": "error", "detail": str(e), "queue": queue_name}
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _job_queue, _chat_queue

    _job_queue = asyncio.Queue(maxsize=200)
    _chat_queue = asyncio.Queue(maxsize=50)
    for i in range(2):
        asyncio.create_task(_worker(i, _job_queue, "agent"))
    asyncio.create_task(_worker(0, _chat_queue, "chat"))

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

class MachineStateUpdate(BaseModel):
    machine_id: str
    machine_type: str
    label: str
    confidence: float
    visual_url: list[str] = []


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": _job_queue.qsize() if _job_queue else 0,
        "chat_queue_size": _chat_queue.qsize() if _chat_queue else 0,
    }


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
    if _chat_queue.full():
        raise HTTPException(status_code=429, detail="Chat queue full - try again later")

    job_id = str(uuid4())
    session_id = req.session_id or f"chat-{req.machine_id}-{uuid4().hex[:8]}"
    _jobs[job_id] = {"status": "queued", "queue": "chat", "session_id": session_id}

    async def run():
        q_lower = req.question.lower()
        if any(term in q_lower for term in ("backend", "connected", "connection", "health", "status")):
            return {
                "result": (
                    "Backend is connected. This request reached the backend /chat endpoint, "
                    f"agent queue size is {_job_queue.qsize() if _job_queue else 0}, "
                    f"chat queue size is {_chat_queue.qsize() if _chat_queue else 0}."
                ),
                "session_id": session_id,
                "elapsed_time": 0,
            }

        if any(term in q_lower for term in ("anomaly", "anomalies", "maintenance", "abnormal")):
            try:
                recent = query_logs(limit=10)
                result = recent.get("result")
                logs = getattr(result, "logs", []) if result else []
                anomaly_logs = [
                    log for log in logs
                    if str(log.event).lower() in {"detect", "anomaly_detected"}
                    or "needs_maintenance" in str(log.details).lower()
                ]
                if anomaly_logs:
                    lines = []
                    for log in anomaly_logs[:5]:
                        details = log.details or {}
                        machine = details.get("machine_id") or details.get("sensor_id") or "unknown machine"
                        lines.append(f"{log.timestamp}: {log.event} for {machine}")
                    answer = "Recent anomaly records found:\n" + "\n".join(lines)
                else:
                    answer = "No recent anomaly records are available in the audit log context."
                return {"result": answer, "session_id": session_id, "elapsed_time": 0}
            except Exception as e:
                return {
                    "result": f"Could not read anomaly records from audit log: {str(e)}",
                    "session_id": session_id,
                    "error": str(e),
                }

        context = "Backend API status: connected; this chat request reached /chat successfully."
        try:
            recent = query_logs(limit=5)
            result = recent.get("result")
            logs = getattr(result, "logs", []) if result else []
            if logs:
                context += "\nRecent audit records:\n" + "\n".join(
                    f"- {log.timestamp} | {log.agent} | {log.event} | {log.details}"
                    for log in logs[:5]
                )
            else:
                context += "\nRecent audit records: none available."
        except Exception as e:
            context += f"\nRecent audit records unavailable: {str(e)}"

        return await orchestrator_response(
            query      = f"[Machine: {req.machine_id}] {req.question}\n\nBackend context:\n{context}",
            session_id = session_id,
            use_tools  = False,
        )

    await _chat_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued", "session_id": session_id}


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
                            raw = line[len("data:"):].strip()
                            payload = json.loads(raw)
                            machine_id = payload.get("machine_id")
                            machine_type = payload.get("machine_type")
                            state = (
                                _latest_machine_state.get(_machine_state_key(machine_id, machine_type))
                                if machine_id and machine_type
                                else None
                            )
                            if state:
                                payload.update({
                                    "label": state.get("label", payload.get("label", "normal")),
                                    "confidence": state.get("confidence", payload.get("confidence")),
                                    "visual_url": state.get("visual_url", payload.get("visual_url", [])),
                                    "state_source": "cnn",
                                })
                            else:
                                payload.setdefault("label", "normal")
                                payload.setdefault("visual_url", [])
                                payload.setdefault("state_source", "stream")
                            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/machine-state")
async def machine_state(update: MachineStateUpdate):
    state = update.model_dump()
    state["updated_at"] = time.time()
    _latest_machine_state[_machine_state_key(update.machine_id, update.machine_type)] = state
    return {"status": "ok", "machine_id": update.machine_id, "machine_type": update.machine_type}


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
        engine = create_engine(AGENTS_DB)
        with engine.connect() as conn:
            result = conn.execute(text(
                """
                SELECT session_id
                FROM message_store
                GROUP BY session_id
                ORDER BY MAX(id) DESC
                LIMIT 50
                """
            ))
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

    # ── Regular HTTP ping ──
    async def ping(name: str, url: str, timeout: float = 3.0):
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                results[name] = {
                    "status": "ok" if r.status_code < 400 else "degraded",
                    "detail": f"HTTP {r.status_code}",
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                }
        except httpx.ConnectError:
            results[name] = {"status": "error", "detail": "Connection refused", "latency_ms": round((time.perf_counter() - start) * 1000)}
        except httpx.TimeoutException:
            results[name] = {"status": "error", "detail": "Timeout", "latency_ms": round((time.perf_counter() - start) * 1000)}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)[:60], "latency_ms": round((time.perf_counter() - start) * 1000)}

    # ── SSE ping: only reads response headers, doesn't consume the stream ──
    async def ping_sse(name: str, url: str, timeout: float = 3.0):
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url) as r:
                    results[name] = {
                        "status": "ok" if r.status_code < 400 else "error",
                        "detail": f"HTTP {r.status_code}",
                        "latency_ms": round((time.perf_counter() - start) * 1000),
                    }
        except httpx.ConnectError:
            results[name] = {"status": "error", "detail": "Connection refused", "latency_ms": round((time.perf_counter() - start) * 1000)}
        except httpx.TimeoutException:
            results[name] = {"status": "error", "detail": "Timeout", "latency_ms": round((time.perf_counter() - start) * 1000)}
        except Exception as e:
            results[name] = {"status": "error", "detail": str(e)[:60], "latency_ms": round((time.perf_counter() - start) * 1000)}

    # ── Static results ──
    results["UI"]      = {"status": "ok", "detail": "Frontend served", "latency_ms": 0}
    results["Backend"] = {"status": "ok", "detail": "Running", "latency_ms": 0}

    # ── Concurrent HTTP pings ──
    tasks = [ping("Streaming", f"{STREAMING_URL}/health")]
    if MCP_URL:
        tasks.append(ping_sse("MCP", MCP_URL))
    else:
        results["MCP"] = {"status": "error", "detail": "MCP_URL not configured"}
    await asyncio.gather(*tasks)

    # ── PostgreSQL ──
    try:
        start = time.perf_counter()
        _get_conn()
        results["PostgreSQL"] = {"status": "ok", "detail": "Connected", "latency_ms": round((time.perf_counter() - start) * 1000)}
    except Exception as e:
        results["PostgreSQL"] = {"status": "error", "detail": str(e)[:60], "latency_ms": round((time.perf_counter() - start) * 1000)}

    # ── Neo4j ──
    try:
        start = time.perf_counter()
        from neo4j import AsyncGraphDatabase
        neo4j_uri  = os.getenv("NEO4J_URI", "bolt://localhost:7687").strip()
        print(f"DEBUG NEO4J_URI = [{neo4j_uri}]") 
        neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j").strip()
        neo4j_pass = os.getenv("NEO4J_PASSWORD", "").strip()
        async with AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass)) as driver:
            await driver.verify_connectivity()
        results["Neo4j"] = {"status": "ok", "detail": "Connected", "latency_ms": round((time.perf_counter() - start) * 1000)}
    except Exception as e:
        results["Neo4j"] = {"status": "error", "detail": str(e)[:60], "latency_ms": round((time.perf_counter() - start) * 1000)}

    # ── Data Simulator ──
    results["DataSimulator"] = {
        "status": "ok" if _ingest_running else "degraded",
        "detail": "Thread alive" if _ingest_running else "Not started",
        "latency_ms": 0,
    }

    # ── Overall ──
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
    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=False)
