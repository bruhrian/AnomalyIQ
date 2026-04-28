import sys
import os
import asyncio
import threading
import json
import importlib.util
import time
import re
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
GRAPH_DIR  = REPO_ROOT / "Data" / "Graphs"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(AGENTS_DIR))

from Agents.orchestrator import orchestrator_response
from Agents.audit_agent import query_logs, _get_conn, log_event
from langchain_community.chat_message_histories import SQLChatMessageHistory

STREAMING_URL = os.getenv("STREAMING_URL")
MCP_URL       = os.getenv("mcp_server_ip")
AGENTS_DB     = os.getenv("agents_memory")
FRONTEND_DIR  = os.getenv("FRONTEND_DIR")
CHAT_REQUEST_TIMEOUT_SECONDS = float(os.getenv("CHAT_REQUEST_TIMEOUT_SECONDS", "90"))

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
_latest_machine_snapshot: dict[str, dict] = {}


def _machine_state_key(machine_id: str, machine_type: str) -> str:
    return f"{machine_id}::{machine_type}"


def _machine_snapshot_key(machine_id: str, machine_type: str) -> str:
    return f"{machine_id}::{machine_type}"


def _iter_latest_states():
    return list(_latest_machine_state.values())


def _iter_known_machines():
    merged: dict[str, dict] = {}
    for snapshot in _latest_machine_snapshot.values():
        key = _machine_state_key(str(snapshot.get("machine_id", "")), str(snapshot.get("machine_type", "")))
        merged[key] = dict(snapshot)
    for state in _latest_machine_state.values():
        key = _machine_state_key(str(state.get("machine_id", "")), str(state.get("machine_type", "")))
        base = merged.get(key, {})
        base.update(state)
        merged[key] = base
    return list(merged.values())


def _get_latest_snapshot(machine_id: str, machine_type: str) -> dict:
    return _latest_machine_snapshot.get(_machine_snapshot_key(machine_id, machine_type), {})


def _latest_log_by_event(machine_logs, event_name: str):
    for log in machine_logs:
        if str(getattr(log, "event", "")).upper() == event_name.upper():
            return log
    return None


def _is_timeout_like_response(text: str, error: str = "") -> bool:
    combined = f"{text or ''}\n{error or ''}".lower()
    return "timed out" in combined or "timeout" in combined


def _has_visual_urls(visual_urls: list[str] | None) -> bool:
    return bool(visual_urls and any(str(url).strip() for url in visual_urls))


def _remove_visual_evidence_section(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\n?Visual Evidence:\n(?:-.*(?:\n|$))*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value


def _build_anomaly_chat_response(machine_id: str, machine_type: str, machine_logs, target_visuals):
    answer_log = _latest_log_by_event(machine_logs, "ANSWER") or _latest_log_by_event(machine_logs, "ANOMALY_ANSWERED")
    summary_log = _latest_log_by_event(machine_logs, "SUMMARY")
    detect_log = _latest_log_by_event(machine_logs, "DETECT") or _latest_log_by_event(machine_logs, "ANOMALY_DETECTED")
    timeout_log = _latest_log_by_event(machine_logs, "ANSWER_TIMEOUT")

    details = {}
    valid_answer_log = None
    if answer_log and getattr(answer_log, "details", None):
        answer_details = answer_log.details or {}
        answer_response = str(answer_details.get("response", "")).strip()
        answer_error = str(answer_details.get("error", "")).strip()
        if not _is_timeout_like_response(answer_response, answer_error):
            valid_answer_log = answer_log

    if valid_answer_log and getattr(valid_answer_log, "details", None):
        details = valid_answer_log.details or {}
    elif summary_log and getattr(summary_log, "details", None):
        details = summary_log.details or {}
    elif detect_log and getattr(detect_log, "details", None):
        details = detect_log.details or {}
    elif timeout_log and getattr(timeout_log, "details", None):
        details = timeout_log.details or {}

    if valid_answer_log and getattr(valid_answer_log, "details", None):
        details = valid_answer_log.details or {}
    label = details.get("label") or ((detect_log.details or {}).get("label") if detect_log and getattr(detect_log, "details", None) else details.get("label"))
    confidence = details.get("confidence")
    response_text = ""
    if valid_answer_log and getattr(valid_answer_log, "details", None):
        response_text = str((valid_answer_log.details or {}).get("response", "")).strip()
    summary_text = ""
    if summary_log and getattr(summary_log, "details", None):
        summary_text = str((summary_log.details or {}).get("summary", "")).strip()

    visuals = details.get("visuals") or {}
    visual_url = details.get("visual_url") or target_visuals or []
    if not visuals and isinstance(visual_url, list):
        visuals = {
            "line_plot": visual_url[0] if len(visual_url) > 0 else "",
            "heatmap": visual_url[1] if len(visual_url) > 1 else "",
        }

    if not response_text:
        response_text = (
            "Summary:\n"
            f"- {machine_id} ({machine_type}) has a recorded anomaly.\n"
            f"- Current label: {label or 'needs_maintenance'}.\n\n"
            "Likely Cause:\n"
            f"- {summary_text if summary_text else 'The formal orchestrator answer is not ready yet, but the machine is already flagged as abnormal.'}\n\n"
            "Recommended Actions:\n"
            "1. Review the recorded anomaly details and attached visual evidence.\n"
            "2. Inspect the affected machine before continuing production.\n"
            "3. If the orchestrator answer is still pending, use this as a provisional response and refresh once processing completes.\n\n"
            "Visual Evidence:\n"
            f"- {'Visuals are attached for this anomaly.' if visual_url else 'No visuals are attached for this anomaly.'}"
        )

    return {
        "result": response_text,
        "visual_url": visual_url,
        "visuals": visuals,
        "resolved_machine_id": machine_id,
        "resolved_machine_type": machine_type,
        "anomaly_detected": True,
        "label": label,
        "confidence": confidence,
    }


def _build_provisional_anomaly_response(target_state: dict, target_snapshot: dict, target_visuals: list[str]) -> dict:
    machine_id = str(target_state.get("machine_id") or "Unknown")
    machine_type = str(target_state.get("machine_type") or "Unknown")
    label = str(target_state.get("label") or "needs_maintenance")
    confidence = target_state.get("confidence")

    snapshot_lines = []
    field_labels = {
        "timestamp": "Latest timestamp",
        "temperature": "Temperature C",
        "vibration": "Vibration",
        "power": "Power kW",
        "pressure": "Pressure Pa",
        "flow_rate": "Flow rate",
    }
    for key, pretty in field_labels.items():
        if key in (target_snapshot or {}):
            snapshot_lines.append(f"- {pretty}: {target_snapshot.get(key)}")

    result_text = (
        "Summary:\n"
        f"- {machine_id} ({machine_type}) is currently flagged as {label}.\n"
        f"- Confidence: {confidence if confidence is not None else 'unknown'}.\n\n"
        "Likely Cause:\n"
        "- A full orchestrator answer is still pending, but the current state already indicates a machine anomaly that needs operator attention.\n\n"
        "Recommended Actions:\n"
        "1. Review the attached visuals immediately.\n"
        "2. Inspect the machine before continuing production.\n"
        "3. Refresh again after the anomaly pipeline completes for the full orchestrator diagnosis.\n\n"
        "Visual Evidence:\n"
        f"- {'Visuals are attached below.' if target_visuals else 'No visuals are attached yet.'}"
    )
    if snapshot_lines:
        result_text += "\n\nCurrent Machine Data:\n" + "\n".join(snapshot_lines)

    return {
        "result": result_text,
        "visual_url": target_visuals,
        "visuals": {
            "line_plot": target_visuals[0] if len(target_visuals) > 0 else "",
            "heatmap": target_visuals[1] if len(target_visuals) > 1 else "",
        },
        "resolved_machine_id": machine_id,
        "resolved_machine_type": machine_type,
        "anomaly_detected": True,
        "label": label,
        "confidence": confidence,
        "provisional": True,
    }


def _build_current_state_response(target_machine_id: str, target_machine_type: str, target_snapshot: dict, target_visuals: list[str], anomaly_logs) -> dict:
    basic_lines = [
        f"Machine: {target_machine_id} ({target_machine_type})",
        "Current status: normal",
    ]
    if target_snapshot.get("timestamp"):
        basic_lines.append(f"Latest timestamp: {target_snapshot.get('timestamp')}")
    field_labels = {
        "temperature": "Temperature C",
        "vibration": "Vibration",
        "power": "Power kW",
        "pressure": "Pressure Pa",
        "flow_rate": "Flow rate",
    }
    for key, label in field_labels.items():
        if key in target_snapshot:
            basic_lines.append(f"{label}: {target_snapshot.get(key)}")

    historical_note = (
        "- Historical anomaly records exist for this machine, but the latest known state currently appears normal.\n"
        if anomaly_logs else
        "- No anomaly records are available for this machine right now.\n"
    )
    result_text = (
        "Summary:\n"
        f"- {target_machine_id} currently appears normal.\n"
        f"{historical_note}\n"
        "Current Machine Data:\n" +
        "\n".join(f"- {line}" for line in basic_lines)
    )
    if _has_visual_urls(target_visuals):
        result_text += "\n\nVisual Evidence:\n- Visuals are attached below."
    return {
        "result": result_text,
        "visual_url": target_visuals if _has_visual_urls(target_visuals) else [],
        "resolved_machine_id": target_machine_id,
        "resolved_machine_type": target_machine_type,
    }


def _resolve_target_machine(question: str, fallback_machine_id: str | None = None) -> dict:
    states = _iter_known_machines()
    q = (question or "").lower()

    explicit_id = re.search(r"\bm\d{3}\b", q)
    if explicit_id:
        wanted_id = explicit_id.group(0).upper()
        matches = [s for s in states if str(s.get("machine_id", "")).upper() == wanted_id]
        if matches:
            return max(matches, key=lambda s: s.get("updated_at", 0))

    aliases = {
        "cnc": "CNC",
        "conveyor": "Conveyor",
        "welder": "Welder",
        "drill": "Drill",
    }
    for token, machine_type in aliases.items():
        if token in q:
            matches = [s for s in states if str(s.get("machine_type", "")).lower() == machine_type.lower()]
            if matches:
                return max(matches, key=lambda s: s.get("updated_at", 0))

    if fallback_machine_id:
        matches = [s for s in states if str(s.get("machine_id", "")).lower() == fallback_machine_id.lower()]
        if matches:
            return max(matches, key=lambda s: s.get("updated_at", 0))

    if states:
        return max(states, key=lambda s: s.get("updated_at", 0))

    return {"machine_id": fallback_machine_id or "M001", "machine_type": "Unknown", "visual_url": [], "label": "unknown"}


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
app.mount("/graphs", StaticFiles(directory=GRAPH_DIR), name="graphs")


def _graph_public_url(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return f"/graphs/{path.resolve().relative_to(GRAPH_DIR.resolve()).as_posix()}"
    except ValueError:
        return path_value


def _save_chat_turn(session_id: str, user_message: str, assistant_message: str) -> None:
    try:
        history = SQLChatMessageHistory(session_id=session_id, connection_string=AGENTS_DB)
        history.add_user_message(user_message)
        history.add_ai_message(assistant_message)
    except Exception as e:
        print(f"Warning: failed to save chat turn for {session_id}: {e}")


class AnomalyAlert(BaseModel):
    machine_id:   str
    machine_type: str
    label:        str
    confidence:   float
    visual_url:   list[str]
    visuals:      dict[str, str] = {}
    cnn_targets:  dict[str, float] = {}

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

    line_plot = alert.visuals.get("line_plot") or (alert.visual_url[0] if len(alert.visual_url) > 0 else "")
    heatmap = alert.visuals.get("heatmap") or (alert.visual_url[1] if len(alert.visual_url) > 1 else "")
    line_plot_url = _graph_public_url(line_plot)
    heatmap_url = _graph_public_url(heatmap)
    public_visuals = [v for v in [line_plot_url, heatmap_url] if v]
    anomaly_context = {
        "job_id": job_id,
        "machine_id": alert.machine_id,
        "machine_type": alert.machine_type,
        "label": alert.label,
        "confidence": alert.confidence,
        "cnn_targets": alert.cnn_targets,
        "visuals": {
            "line_plot": line_plot_url,
            "heatmap": heatmap_url,
        },
    }
    audit_base = {
        "job_id": job_id,
        "sensor_id": alert.machine_id,
        "machine_id": alert.machine_id,
        "machine_type": alert.machine_type,
        "label": alert.label,
        "confidence": alert.confidence,
        "cnn_targets": alert.cnn_targets,
        "visual_url": public_visuals,
        "visuals": anomaly_context["visuals"],
    }
    log_event(
        agent="CNN",
        event="DETECT",
        details={
            **audit_base,
            "description": f"Anomaly detected for {alert.machine_id} ({alert.machine_type})",
        },
    )

    async def run():
        log_event(
            agent="CA",
            event="PROCESS",
            details={
                **audit_base,
                "description": "Orchestrator started anomaly analysis",
            },
        )
        _legacy_query = (
            f"ANOMALY ALERT — Machine {alert.machine_id} ({alert.machine_type})\n"
            f"Label: {alert.label} | Confidence: {alert.confidence:.1%}\n"
            f"Visuals: {', '.join(alert.visual_url) if alert.visual_url else 'none'}\n\n"
            f"Please analyse this anomaly, explain the root cause, cascade effects, and recommended actions."
        )
        query = (
            "ANOMALY ALERT - CNN has already detected an abnormal machine state.\n"
            "Do not ask the operator for more raw data. Use the complete JSON context below.\n"
            "Your final answer must include root cause, cascade effects, recommended actions, "
            "and a Visual Evidence section that explicitly references visuals.line_plot and visuals.heatmap.\n\n"
            f"ANOMALY_CONTEXT_JSON:\n{json.dumps(anomaly_context, indent=2)}"
        )
        anomaly_session_id = f"anomaly-{alert.machine_id}-{job_id[:8]}"
        analysis_mode = "mcp_orchestrator"
        result = await orchestrator_response(
            query=query,
            session_id=anomaly_session_id,
            use_tools=True,
            request_timeout_seconds=120,
            persist_history=False,
        )
        result_text = str(result.get("result", "")) if isinstance(result, dict) else str(result)
        result_error = str(result.get("error", "")) if isinstance(result, dict) else ""
        is_timeout = _is_timeout_like_response(result_text, result_error)

        if is_timeout:
            fallback_result = await orchestrator_response(
                query=query,
                session_id=f"{anomaly_session_id}-fallback",
                use_tools=False,
                request_timeout_seconds=90,
                persist_history=False,
            )
            fallback_text = str(fallback_result.get("result", "")) if isinstance(fallback_result, dict) else str(fallback_result)
            fallback_error = str(fallback_result.get("error", "")) if isinstance(fallback_result, dict) else ""
            if not _is_timeout_like_response(fallback_text, fallback_error):
                result = fallback_result
                result_text = fallback_text
                result_error = fallback_error
                is_timeout = False
                analysis_mode = "fallback_orchestrator"

        if not is_timeout:
            summary_text = result_text.strip().split("\n\n")[0][:800] if result_text else "Analysis completed"
            log_event(
                agent="CA",
                event="SUMMARY",
                details={
                    **audit_base,
                    "summary": summary_text,
                    "description": "Analysis summary generated",
                    "analysis_mode": analysis_mode,
                },
            )
            log_event(
                agent="CA",
                event="ANSWER",
                details={
                    **audit_base,
                    "response": result_text[:4000],
                    "description": "Returned anomaly response to operator",
                    "analysis_mode": analysis_mode,
                },
            )
        else:
            log_event(
                agent="CA",
                event="ANSWER_TIMEOUT",
                details={
                    **audit_base,
                    "response": result_text[:4000],
                    "error": result_error[:4000],
                    "description": "Orchestrator timed out before final anomaly answer was ready",
                    "analysis_mode": analysis_mode,
                },
            )
        if isinstance(result, dict):
            result["visual_url"] = public_visuals
            result["visuals"] = anomaly_context["visuals"]
            result["anomaly_context"] = anomaly_context
            result["analysis_mode"] = analysis_mode if not is_timeout else "timeout"
        return result

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
            history_user_message = request.question,
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
        target_state = _resolve_target_machine(req.question, req.machine_id)
        target_machine_id = str(target_state.get("machine_id") or req.machine_id)
        target_machine_type = str(target_state.get("machine_type") or "Unknown")
        target_visuals = target_state.get("visual_url", [])
        target_snapshot = _get_latest_snapshot(target_machine_id, target_machine_type)

        backend_status_requested = (
            ("backend" in q_lower or "system" in q_lower) and
            any(term in q_lower for term in ("connected", "connection", "health", "status"))
        )
        if backend_status_requested:
            result = {
                "result": (
                    "Backend is connected. This request reached the backend /chat endpoint, "
                    f"agent queue size is {_job_queue.qsize() if _job_queue else 0}, "
                    f"chat queue size is {_chat_queue.qsize() if _chat_queue else 0}.\n\n"
                    f"Resolved target machine: {target_machine_id} ({target_machine_type})."
                ),
                "session_id": session_id,
                "elapsed_time": 0,
                "visual_url": target_visuals,
            }
            _save_chat_turn(session_id, req.question, result["result"])
            return result

        if q_lower.strip() in {"hello", "hi", "hey", "hello!", "hi!", "hey!"}:
            result = {
                "result": (
                    f"Hello. I am operational and connected.\n\n"
                    f"Resolved target machine: {target_machine_id} ({target_machine_type}).\n"
                    "Ask me about anomaly risk, likely cause, recommended actions, or visual evidence."
                ),
                "session_id": session_id,
                "elapsed_time": 0,
                "visual_url": target_visuals,
            }
            _save_chat_turn(session_id, req.question, result["result"])
            return result

        snapshot_lines = []
        if target_snapshot:
            field_labels = {
                "timestamp": "Latest timestamp",
                "temperature": "Temperature C",
                "vibration": "Vibration",
                "power": "Power kW",
                "pressure": "Pressure Pa",
                "flow_rate": "Flow rate",
            }
            for key, label in field_labels.items():
                if key in target_snapshot:
                    snapshot_lines.append(f"{label}: {target_snapshot.get(key)}")

        recent = None
        logs = []
        machine_logs = []
        recent_global = None
        try:
            recent = query_logs(sensor_id=target_machine_id, limit=20)
            result = recent.get("result")
            machine_logs = getattr(result, "logs", []) if result else []
            recent_global = query_logs(limit=8)
            global_result = recent_global.get("result")
            logs = getattr(global_result, "logs", []) if global_result else []
        except Exception:
            machine_logs = []

        anomaly_logs = [
            log for log in machine_logs
            if str(log.event).upper() in {"DETECT", "PROCESS", "SUMMARY", "ANSWER", "ANOMALY_DETECTED", "ANOMALY_ANSWERED"}
            or "needs_maintenance" in str(log.details).lower()
        ]

        current_label = str(target_state.get("label", "unknown")).lower()

        if current_label == "normal":
            result = _build_current_state_response(
                target_machine_id,
                target_machine_type,
                target_snapshot,
                target_visuals,
                anomaly_logs,
            )
            result["session_id"] = session_id
            result["elapsed_time"] = 0
            _save_chat_turn(session_id, req.question, str(result.get("result", "")))
            return result

        if anomaly_logs and any(term in q_lower for term in ("anomaly", "abnormal", "maintenance", "risk", "reason", "cause", "respond", "response", "why")):
            result = _build_anomaly_chat_response(
                target_machine_id,
                target_machine_type,
                machine_logs,
                target_visuals,
            )
            result["session_id"] = session_id
            result["elapsed_time"] = 0
            _save_chat_turn(session_id, req.question, str(result.get("result", "")))
            return result

        if current_label not in {"normal", "unknown"} and any(term in q_lower for term in ("anomaly", "abnormal", "maintenance", "risk", "reason", "cause", "respond", "response", "why")):
            result = _build_provisional_anomaly_response(target_state, target_snapshot, target_visuals)
            result["session_id"] = session_id
            result["elapsed_time"] = 0
            _save_chat_turn(session_id, req.question, str(result.get("result", "")))
            return result

        context = (
            "Backend API status: connected; this chat request reached /chat successfully.\n"
            f"Resolved target machine: {target_machine_id}\n"
            f"Resolved machine type: {target_machine_type}\n"
            f"Latest state label: {target_state.get('label', 'unknown')}\n"
            f"Latest confidence: {target_state.get('confidence', 'unknown')}\n"
            f"Available visuals: {len(target_visuals)}\n"
            "Interpretation rule: if latest state label is normal and there are no anomaly records, say the machine currently appears normal."
        )
        if snapshot_lines:
            context += "\nLatest machine snapshot:\n" + "\n".join(f"- {line}" for line in snapshot_lines)
        try:
            if machine_logs or logs:
                context_logs = machine_logs[:5] if machine_logs else logs[:2]
                context += "\nRecent audit records:\n" + "\n".join(
                    f"- {log.timestamp} | {log.agent} | {log.event} | {log.details}"
                    for log in context_logs[:3]
                )
            else:
                context += "\nRecent audit records: none available."
        except Exception as e:
            context += f"\nRecent audit records unavailable: {str(e)}"

        result = await orchestrator_response(
            query      = f"[Machine: {target_machine_id}] {req.question}\n\nBackend context:\n{context}",
            session_id = session_id,
            use_tools  = False,
            request_timeout_seconds = CHAT_REQUEST_TIMEOUT_SECONDS,
            history_user_message = req.question,
        )
        if isinstance(result, dict):
            if not _has_visual_urls(target_visuals) and isinstance(result.get("result"), str):
                result["result"] = _remove_visual_evidence_section(result["result"])
            result["visual_url"] = target_visuals if _has_visual_urls(target_visuals) else []
            result["resolved_machine_id"] = target_machine_id
            result["resolved_machine_type"] = target_machine_type
        return result

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
                            if machine_id and machine_type:
                                snapshot = dict(payload)
                                snapshot["updated_at"] = time.time()
                                _latest_machine_snapshot[_machine_snapshot_key(machine_id, machine_type)] = snapshot
                            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/machine-state")
async def machine_state(update: MachineStateUpdate):
    state = update.model_dump()
    state["visual_url"] = [_graph_public_url(url) for url in state.get("visual_url", [])]
    state["updated_at"] = time.time()
    _latest_machine_state[_machine_state_key(update.machine_id, update.machine_type)] = state
    return {"status": "ok", "machine_id": update.machine_id, "machine_type": update.machine_type}


@app.get("/audit/logs")
async def audit_logs(agent: str = "", event: str = "", sensor_id: str = "", limit: int = 200):
    try:
        res    = query_logs(agent=agent, event=event, sensor_id=sensor_id, limit=limit)
        result = res["result"]
        return {"count": result.count, "logs": [log.model_dump() for log in result.logs]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/audit/stream")
async def audit_stream(limit: int = 200):
    async def event_gen():
        last_signature = None
        while True:
            try:
                res = query_logs(limit=limit)
                result = res["result"]
                logs = [log.model_dump() for log in result.logs]
                signature = tuple((log.get("id"), log.get("timestamp")) for log in logs[:10])
                if signature != last_signature:
                    last_signature = signature
                    yield f"data: {json.dumps({'count': len(logs), 'logs': logs})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


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
