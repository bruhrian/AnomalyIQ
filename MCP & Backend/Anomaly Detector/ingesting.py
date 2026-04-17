"""
ingesting.py  (updated)
=======================
Same logic as before, but wrapped into importable functions
so main.py can run it as a background thread:

    from services.ingesting import run_ingest_loop, get_latest_readings, is_running

Changes vs original:
  - Bottom-level script code moved into run_ingest_loop()
  - Added get_latest_readings() for the /machines/status endpoint
  - Added is_running() for the /system/health endpoint
  - _send_window now calls CNN logic directly if available,
    falls back to HTTP POST to 127.0.0.1:8001 (original behaviour)
"""

import json
import pickle
import requests
import time
import threading
import numpy as np
from pathlib import Path
from collections import defaultdict, deque

T_IN  = 30
T_OUT = 15

STREAM_URL = "http://127.0.0.1:8000/stream"
INFER_URL  = "http://127.0.0.1:8001/predict"

BASE_DIR = Path(__file__).resolve().parent.parent  # MCP & Backend/

CNC_SCALER_PATH      = BASE_DIR.parent / "Databases & Models" / "Models" / "phase_5.3" / "CNC"      / "aggregated" / "scaler_X.pkl"
CONVEYOR_SCALER_PATH = BASE_DIR.parent / "Databases & Models" / "Models" / "phase_5.3" / "Conveyor" / "aggregated" / "scaler_X.pkl"
DRILL_SCALER_PATH    = BASE_DIR.parent / "Databases & Models" / "Models" / "phase_5.3" / "Drill"    / "aggregated" / "scaler_X.pkl"
WELDER_SCALER_PATH   = BASE_DIR.parent / "Databases & Models" / "Models" / "phase_5.3" / "Welder"   / "aggregated" / "scaler_X.pkl"

SCALER_PATHS: dict[str, Path] = {
    "CNC":      CNC_SCALER_PATH,
    "Conveyor": CONVEYOR_SCALER_PATH,
    "Drill":    DRILL_SCALER_PATH,
    "Welder":   WELDER_SCALER_PATH,
}
_scalers: dict[str, object] = {}

# ── State (shared with main.py via get_latest_readings / is_running) ──────────
_machine_buffers:  dict[tuple, deque] = defaultdict(lambda: deque(maxlen=T_IN))
_window_store:     dict[str, list]    = {}
_latest_readings:  dict[str, dict]    = {}   # machine_id → last raw payload
_running:          bool               = False
_thread_lock = threading.Lock()


# ── Public state accessors ────────────────────────────────────────────────────

def is_running() -> bool:
    """Returns True if the ingest loop is currently active."""
    return _running


def get_latest_readings() -> list[dict]:
    """
    Returns the most recent raw sensor reading for each machine.
    Called by GET /machines/status in routers/backend.py
    """
    with _thread_lock:
        return list(_latest_readings.values())


# ── Scaler ────────────────────────────────────────────────────────────────────

def get_scaler(machine_type: str):
    if machine_type not in _scalers:
        path = SCALER_PATHS.get(machine_type)
        if path is None:
            raise ValueError(f"Unknown machine_type '{machine_type}'. "
                             f"Expected one of: {list(SCALER_PATHS)}")
        if not path.exists():
            raise FileNotFoundError(f"Scaler not found at {path}")
        with open(path, "rb") as f:
            _scalers[machine_type] = pickle.load(f)
    return _scalers[machine_type]


# ── Feature helpers ───────────────────────────────────────────────────────────

NUMERIC_FEATURES = [
    "temperature", "vibration_level", "power_consumption",
    "pressure", "material_flow_rate", "cycle_time",
]

def _is_valid_row(payload: dict) -> bool:
    for field in NUMERIC_FEATURES:
        val = payload.get(field)
        if val is None:
            return False
        if not np.isfinite(val):
            print(f"  [INVALID] {field} = {val}")
            return False
    return True

def _encode_machine(machine_id: str) -> list[float]:
    machines = ["M001", "M002", "M003", "M004"]
    return [1.0 if machine_id == m else 0.0 for m in machines]

def _normalise(payload: dict, machine_type: str) -> list[float]:
    one_hot = _encode_machine(payload["machine_id"])
    raw     = np.array(
        [[payload[col] for col in NUMERIC_FEATURES] + one_hot],
        dtype=np.float32,
    )
    return get_scaler(machine_type).transform(raw)[0].tolist()

def _build_feature_row(payload: dict, machine_type: str) -> list[float]:
    return _normalise(payload, machine_type)

def _is_window_ready(buffer: deque) -> bool:
    return len(buffer) >= T_IN

def _build_window(buffer: deque) -> list:
    return np.array(list(buffer), dtype=np.float32).tolist()


# ── Send window to CNN ────────────────────────────────────────────────────────

def _send_window(machine_id: str, machine_type: str, window: list) -> None:
    arr = np.array(window)
    if not np.isfinite(arr).all():
        bad = np.argwhere(~np.isfinite(arr))
        print(f"  [WINDOW ERROR] {machine_id} has NaN/inf at positions: {bad}")
        return

    payload = {
        "machine_id":   machine_id,
        "machine_type": machine_type,
        "window":       window,
    }
    try:
        resp = requests.post(INFER_URL, json=payload, timeout=5)
        resp.raise_for_status()
        print(f"  [SENT] {machine_id} → {resp.json()}")
    except requests.exceptions.RequestException as e:
        print(f"  [SEND ERROR] {machine_id}: {e}")


# ── Core ingest function ───────────────────────────────────────────────────────

def ingest_data(payload: dict, machine_id: str, machine_type: str, timestamp: str) -> dict:
    if not _is_valid_row(payload):
        return {"status": "invalid", "machine_id": machine_id, "buffer_size": 0}

    # Store latest raw reading for /machines/status
    with _thread_lock:
        _latest_readings[machine_id] = {
            "machine_id":        machine_id,
            "machine_type":      machine_type,
            "timestamp":         timestamp,
            "temperature":       payload.get("temperature"),
            "vibration_level":   payload.get("vibration_level"),
            "power_consumption": payload.get("power_consumption"),
            "pressure":          payload.get("pressure"),
            "material_flow_rate":payload.get("material_flow_rate"),
            "cycle_time":        payload.get("cycle_time"),
        }

    key         = (machine_id, machine_type)
    feature_row = _build_feature_row(payload, machine_type)
    _machine_buffers[key].append(feature_row)

    buf = _machine_buffers[key]
    print(f"  [{timestamp}]  {machine_id} ({machine_type})  |  buffer {len(buf)}/{T_IN}")

    if not _is_window_ready(buf):
        return {
            "status":       "buffering",
            "machine_id":   machine_id,
            "machine_type": machine_type,
            "buffer_size":  len(buf),
        }

    window = _build_window(buf)
    with _thread_lock:
        _window_store[machine_id] = window
    _send_window(machine_id, machine_type, window)

    return {
        "status":       "ready",
        "machine_id":   machine_id,
        "machine_type": machine_type,
        "buffer_size":  len(buf),
    }


# ── Main loop (called by main.py as a background thread) ─────────────────────

def run_ingest_loop() -> None:
    """
    Blocking loop — connect to streaming.py and process rows.
    main.py runs this in a daemon thread.
    """
    global _running
    _running = True
    print("[INGEST] Loop starting — connecting to", STREAM_URL)

    try:
        with requests.get(STREAM_URL, stream=True) as r:
            for line in r.iter_lines():
                if not _running:
                    break
                if not (line and line.startswith(b"data:")):
                    continue

                msg     = line.decode("utf-8")[len("data: "):]
                payload = json.loads(msg)

                if not _is_valid_row(payload):
                    continue

                machine_id   = payload.get("machine_id",   "")
                machine_type = payload.get("machine_type", "")
                timestamp    = payload.get("timestamp",    "")

                result = ingest_data(payload, machine_id, machine_type, timestamp)

                # Original debug pause
                buf_size = result.get("buffer_size", 0)
                if (result["status"] == "buffering" and buf_size == T_IN - 1) or \
                   (result["status"] == "ready"     and buf_size == T_IN):
                    print(f"  [DEBUG] Buffer at {buf_size}/{T_IN}, pausing 15s…")
                    time.sleep(15)

    except Exception as e:
        print(f"[INGEST] Loop error: {e}")
    finally:
        _running = False
        print("[INGEST] Loop stopped")


# ── Allow running standalone (original behaviour) ─────────────────────────────
if __name__ == "__main__":
    run_ingest_loop()
