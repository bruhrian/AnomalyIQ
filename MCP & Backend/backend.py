import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import uvicorn
from uuid import uuid4
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from Agents.coordinator_agent import handle_anomaly_alert, handle_qa_question

# ── In-memory stores ───────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_job_queue: asyncio.Queue = None


# ── Request models ─────────────────────────────────────────────────────────────

class AnomalyAlert(BaseModel):
    machine_id:   str
    machine_type: str
    label:        str
    confidence:   float
    visual_url:   list[str]


class QARequest(BaseModel):
    machine_id: str
    question:   str


# ── Worker ─────────────────────────────────────────────────────────────────────

async def _worker(worker_id: int):
    print(f"[WORKER {worker_id}] Started and waiting for jobs...")
    while True:
        job_id, coro_fn = await _job_queue.get()
        print(f"[WORKER {worker_id}] Picked up job {job_id} — queue remaining: {_job_queue.qsize()}")
        _jobs[job_id] = {"status": "processing"}
        try:
            result = await coro_fn()
            _jobs[job_id] = {"status": "done", "result": result}
            print(f"[WORKER {worker_id}] Job {job_id} done")
        except Exception as e:
            _jobs[job_id] = {"status": "error", "detail": str(e)}
            print(f"[WORKER {worker_id}] Job {job_id} failed: {e}")
        finally:
            _job_queue.task_done()


# ── Lifespan — replaces @app.on_event("startup") ─────────────────────────────
# Works correctly with uvicorn reload=True unlike on_event

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _job_queue
    _job_queue = asyncio.Queue(maxsize=200)

    N_WORKERS = 2
    workers = []
    for i in range(N_WORKERS):
        task = asyncio.create_task(_worker(i))
        workers.append(task)
        print(f"[STARTUP] Worker {i} launched")

    print(f"[STARTUP] CA backend ready — {N_WORKERS} workers running")

    yield  # app runs here

    # Shutdown — cancel all workers cleanly
    for task in workers:
        task.cancel()
    print("[SHUTDOWN] Workers stopped")


app = FastAPI(title="CA — Coordinator Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/anomaly")
async def anomaly(alert: AnomalyAlert):
    if _job_queue.full():
        raise HTTPException(status_code=429, detail="Queue full — try again later")
    
    print(alert.visual_url)

    job_id = str(uuid4())
    _jobs[job_id] = {"status": "queued", "position": _job_queue.qsize() + 1}
    print(f"[CA] Anomaly received — machine: {alert.machine_id} | job: {job_id}")

    async def run():
        return await handle_anomaly_alert(
            machine_id   = alert.machine_id,
            machine_type = alert.machine_type,
            label        = alert.label,
            confidence   = alert.confidence,
            visual_url   = alert.visual_url,
        )

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
        return await handle_qa_question(
            machine_id = request.machine_id,
            question   = request.question,
        )

    await _job_queue.put((job_id, run))
    return {"job_id": job_id, "status": "queued", "position": _job_queue.qsize()}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": _job_queue.qsize() if _job_queue else 0}


if __name__ == "__main__":
    uvicorn.run("backend:app", host="0.0.0.0", port=8005, reload=False)