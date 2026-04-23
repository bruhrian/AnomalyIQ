import json, pickle, requests
import time
import numpy as np
from pathlib import Path
from collections import defaultdict, deque

T_IN  = 30
T_OUT = 15

STREAM_URL = "http://127.0.0.1:8000/stream"
INFER_URL = "http://127.0.0.1:8001/predict"
BASE_DIR = Path(__file__).resolve().parent  
CNC_SCALER_PATH      = BASE_DIR.parent.parent / "Databases & Models" / "Models" / "phase_5.3" / "CNC"      / "aggregated" / "scaler_X.pkl"
CONVEYOR_SCALER_PATH = BASE_DIR.parent.parent / "Databases & Models" / "Models" / "phase_5.3" / "Conveyor" / "aggregated" / "scaler_X.pkl"
DRILL_SCALER_PATH    = BASE_DIR.parent.parent / "Databases & Models" / "Models" / "phase_5.3" / "Drill"    / "aggregated" / "scaler_X.pkl"
WELDER_SCALER_PATH   = BASE_DIR.parent.parent / "Databases & Models" / "Models" / "phase_5.3" / "Welder"   / "aggregated" / "scaler_X.pkl"

SCALER_PATHS: dict[str, Path] = {
    "CNC":      CNC_SCALER_PATH,
    "Conveyor": CONVEYOR_SCALER_PATH,
    "Drill":    DRILL_SCALER_PATH,
    "Welder":   WELDER_SCALER_PATH,
}
_scalers: dict[str, object] = {}

def get_scaler(machine_type: str):
    if machine_type not in _scalers:
        path = SCALER_PATHS.get(machine_type)
        if path is None:
            raise ValueError(f"Unknown machine_type '{machine_type}'. Expected one of: {list(SCALER_PATHS)}")
        if not path.exists():
            raise FileNotFoundError(f"Scaler not found at {path}")
        with open(path, "rb") as f:
            _scalers[machine_type] = pickle.load(f)
    return _scalers[machine_type]

NUMERIC_FEATURES = [
    "temperature", "vibration_level", "power_consumption",
    "pressure", "material_flow_rate", "cycle_time",
]

FEATURE_COLUMNS = [
    "temperature", "vibration_level", "power_consumption",
    "pressure", "material_flow_rate", "cycle_time",
    "machine_M001", "machine_M002", "machine_M003", "machine_M004",
]

def _is_valid_row(payload: dict) -> bool:
    for field in NUMERIC_FEATURES:
        val = payload.get(field)
        if val is None:
            return False
        if not np.isfinite(val):  # catches NaN and inf
            print(f"  [INVALID] {field} = {val}")
            return False
    return True

def _encode_machine(machine_id: str) -> list[float]:
    machines = ["M001", "M002", "M003", "M004"]
    return [1.0 if machine_id == m else 0.0 for m in machines]

def _normalise(payload: dict, machine_type: str) -> list[float]:
    one_hot = _encode_machine(payload["machine_id"])
    raw = np.array([[payload[col] for col in NUMERIC_FEATURES] + one_hot], dtype=np.float32)
    
    # DEBUG — add these 3 lines temporarily
    print(f"  [DEBUG] raw input shape: {raw.shape}")
    print(f"  [DEBUG] raw values: {raw}")
    result = get_scaler(machine_type).transform(raw)[0].tolist()
    print(f"  [DEBUG] scaled output: {result}")
    
    return result

def _build_feature_row(payload: dict, machine_type: str) -> list[float]:
    normalised = _normalise(payload, machine_type) 
    print(f"  [DEBUG] Normalised features: {normalised}")
    return [*normalised]

def _is_window_ready(buffer: deque) -> bool:
    return len(buffer) >= T_IN

def _build_window(buffer: deque, machine_type: str) -> dict:
    X          = np.array(list(buffer), dtype=np.float32)
    X_expanded = np.expand_dims(X, axis=0)
    return {
        "machine_type": machine_type,
        "window":       X_expanded[0].tolist(),
        "shape":        list(X_expanded.shape),
    }

_machine_buffers: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=T_IN))
_window_store:    dict[str, list[list[float]]] = {}

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

def ingest_data(payload: dict, machine_id: str, machine_type: str, timestamp: str) -> dict:
    if not _is_valid_row(payload):
        return {
            "status":      "invalid",
            "machine_id":  machine_id,
            "buffer_size": 0,
        }

    key         = (machine_id, machine_type)
    feature_row = _build_feature_row(payload, machine_type)  # pass machine_type
    _machine_buffers[key].append(feature_row)

    buf = _machine_buffers[key]
    print(f"  [{timestamp}]  {machine_id} ({machine_type})  |  buffer {len(buf)}/{T_IN} rows")

    if not _is_window_ready(buf):
        return {
            "status":       "buffering",
            "machine_id":   machine_id,
            "machine_type": machine_type,
            "buffer_size":  len(buf),
        }

    window = _build_window(buf, machine_type)
    _window_store[machine_id] = window["window"]
    _send_window(machine_id, machine_type, window["window"])

    return {
        "status":       "ready",
        "machine_id":   machine_id,
        "machine_type": machine_type,
        "buffer_size":  len(buf),
    }

def run_ingest_loop():
    with requests.get(STREAM_URL, stream=True) as r:
        for line in r.iter_lines():
            if line and line.startswith(b"data:"):
                msg     = line.decode("utf-8")[len("data: "):]
                payload = json.loads(msg)

                if not _is_valid_row(payload):
                    continue

                machine_id   = payload.get("machine_id", "")
                machine_type = payload.get("machine_type", "")
                timestamp    = payload.get("timestamp", "")

                result = ingest_data(payload, machine_id, machine_type, timestamp)

                if result["status"] == "buffering" and result["buffer_size"] == T_IN - 1 or result["status"] == "ready" and result["buffer_size"] == T_IN:
                    print(f"  [DEBUG] Buffer at {result['buffer_size']}/{T_IN}, pausing 20s before next row...")
                    time.sleep(15)

if __name__ == "__main__":
    run_ingest_loop()
