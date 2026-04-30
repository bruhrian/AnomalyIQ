import json
import os, pickle, traceback, uvicorn, httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tensorflow import keras
from VisualGen import generate_visual
from pathlib import Path

def resolve(path_str: str):
    return (REPO_ROOT / path_str).resolve()

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv()
CNN_saved_path = resolve(os.getenv('CNN_MODEL'))

CA_URL = os.getenv("CA_URL", "http://main:8005")
CA_TIMEOUT_SECONDS = float(os.getenv("CA_TIMEOUT_SECONDS", "10"))
CNN_FAKE_ANOMALY_ONCE = os.getenv("CNN_FAKE_ANOMALY_ONCE", "0").lower() in {"1", "true", "yes", "on"}
CNN_FAKE_ANOMALY_CONFIDENCE = float(os.getenv("CNN_FAKE_ANOMALY_CONFIDENCE", "0.88"))

if not CNN_saved_path:
    raise RuntimeError("CNN_MODEL environment variable is not set. Check your .env file.")
if not os.path.exists(CNN_saved_path):
    raise RuntimeError(f"CNN_MODEL path does not exist: {CNN_saved_path}")

app = FastAPI()

class WindowPayload(BaseModel):
    machine_id:   str
    machine_type: str
    window:       list[list[float]]  # (30, 10)


_model_cache: dict[str, dict] = {}

TYPE_MAP = {"cnc": "CNC", "conveyor": "Conveyor", "drill": "Drill", "welder": "Welder"}
AGG_TARGETS = ["max_error_rate", "sum_downtime", "maintenance_present", "min_efficiency", "last_production_status"]
_fake_anomaly_used = False

def _get_models(mach_type: str) -> dict:
    if mach_type not in _model_cache:
        best_model = "best_model.h5"
        mach_dir   = os.path.join(CNN_saved_path, mach_type)

        agg_path  = os.path.join(mach_dir, "aggregated",  best_model)
        scaler_y_path = os.path.join(mach_dir, "aggregated", "scaler_y_agg.pkl")

        if not os.path.exists(agg_path):
            raise FileNotFoundError(f"Aggregated model not found: {agg_path}")
        if not os.path.exists(scaler_y_path):
            raise FileNotFoundError(f"Aggregated output scaler not found: {scaler_y_path}")

        with open(scaler_y_path, "rb") as f:
            scaler_y = pickle.load(f)

        _model_cache[mach_type] = {
            "aggregated":  keras.models.load_model(agg_path,        compile=False),
            "scaler_y": scaler_y,
        }
        print(f"  [MODEL LOADED] {mach_type}")

    return _model_cache[mach_type]

def _publish_machine_state(machine_state: dict) -> dict:
    try:
        resp = httpx.post(f"{CA_URL.rstrip('/')}/machine-state", json=machine_state, timeout=CA_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

@app.post("/predict")
def predict_endpoint(body: WindowPayload):
    global _fake_anomaly_used
    try:
        machine_type = TYPE_MAP.get(body.machine_type.lower(), body.machine_type)

        X = np.array(body.window, dtype=np.float32)

        if X.shape != (30, 10):
            raise ValueError(f"Expected window shape (30, 10), got {X.shape}")

        X = np.expand_dims(X, axis=0)  

        models = _get_models(machine_type) 

        agg_pred_scaled = models["aggregated"].predict(X, verbose=0)
        agg_pred = models["scaler_y"].inverse_transform(agg_pred_scaled)

        pred_list = agg_pred.tolist()
        decoded_targets = dict(zip(AGG_TARGETS, [float(v) for v in pred_list[0]]))
        maintenance_score_raw = decoded_targets["maintenance_present"]
        maintenance_score = float(np.clip(maintenance_score_raw, 0.0, 1.0))
        forced_test_anomaly = False

        if CNN_FAKE_ANOMALY_ONCE and not _fake_anomaly_used:
            _fake_anomaly_used = True
            forced_test_anomaly = True
            maintenance_score = max(maintenance_score, CNN_FAKE_ANOMALY_CONFIDENCE)
            decoded_targets["maintenance_present"] = maintenance_score
            print(
                "[CNN TEST] Forcing one needs_maintenance output "
                f"for {body.machine_id} ({machine_type})"
            )

        maintenance = 1 if maintenance_score >= 0.5 else 0
        confidence = maintenance_score if maintenance == 1 else 1.0 - maintenance_score
        decoded_targets["maintenance_score_raw"] = float(maintenance_score_raw)
        decoded_targets["maintenance_threshold"] = 0.5

        if maintenance == 1:
            visual_result = generate_visual(
                machine_id = body.machine_id,
                machine_type = machine_type,
                label      = "maintenance",
                confidence = confidence,
                window     = body.window,
            )

            ca_payload = {
                "machine_id":   body.machine_id,
                "machine_type": machine_type,
                "label":        "needs_maintenance",
                "confidence":   confidence,
                "visual_url": [
                    visual_result["line_plot"],
                    visual_result["heatmap"],
                ],
                "visuals": {
                    "line_plot": visual_result["line_plot"],
                    "heatmap": visual_result["heatmap"],
                },
            }
            ca_payload["cnn_targets"] = decoded_targets
            ca_payload["stream_status"] = _publish_machine_state(ca_payload)

            try:
                ca_resp = httpx.post(f"{CA_URL.rstrip('/')}/anomaly", json=ca_payload, timeout=CA_TIMEOUT_SECONDS)
                ca_resp.raise_for_status()
                ca_payload["ca_status"] = ca_resp.json()
            except Exception as e:
                # CA being down should never crash the CNN response
                ca_payload["ca_status"] = {"error": str(e)}

            ca_payload["forced_test_anomaly"] = forced_test_anomaly
            print("[CNN OUTPUT]")
            print(json.dumps(ca_payload, indent=2, default=str))
            return ca_payload
        else:
            result = {
                "machine_id": body.machine_id,
                "machine_type": machine_type,
                "label": "normal",
                "confidence": confidence,
                "visual_url": [],
                "cnn_targets": decoded_targets,
                "stream_status": _publish_machine_state({
                    "machine_id": body.machine_id,
                    "machine_type": machine_type,
                    "label": "normal",
                    "confidence": confidence,
                    "visual_url": [],
                }),
            }
            print("[CNN OUTPUT]")
            print(json.dumps(result, indent=2, default=str))
            return result


    except FileNotFoundError as e:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")
    
@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
