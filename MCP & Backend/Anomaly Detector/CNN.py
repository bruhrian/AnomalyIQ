import os, traceback, uvicorn, random, httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tensorflow import keras
from VisualGen import generate_visual

load_dotenv()
CNN_saved_path = os.getenv('CNN_MODEL')

CA_URL = os.getenv("CA_URL", "http://localhost:8002")

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

def _get_models(mach_type: str) -> dict:
    if mach_type not in _model_cache:
        best_model = "best_model.h5"
        mach_dir   = os.path.join(CNN_saved_path, mach_type)

        agg_path  = os.path.join(mach_dir, "aggregated",  best_model)

        if not os.path.exists(agg_path):
            raise FileNotFoundError(f"Aggregated model not found: {agg_path}")

        _model_cache[mach_type] = {
            "aggregated":  keras.models.load_model(agg_path,        compile=False),
        }
        print(f"  [MODEL LOADED] {mach_type}")

    return _model_cache[mach_type]

@app.post("/predict")
def predict_endpoint(body: WindowPayload):
    try:
        # Normalise machine_type casing
        TYPE_MAP = {"cnc": "CNC", "conveyor": "Conveyor", "drill": "Drill", "welder": "Welder"}
        machine_type = TYPE_MAP.get(body.machine_type.lower(), body.machine_type)  # ✅

        X = np.array(body.window, dtype=np.float32)

        if X.shape != (30, 10):
            raise ValueError(f"Expected window shape (30, 10), got {X.shape}")

        X = np.expand_dims(X, axis=0)  

        models = _get_models(machine_type) 

        agg_pred = models["aggregated"].predict(X, verbose=0)

        pred_list = agg_pred.tolist()
        maintenance_score = pred_list[0][2]
        maintenance = 1 if maintenance_score >= 0.5 else 0

        if maintenance == 1:
            visual_result = generate_visual(
                machine_id = body.machine_id,
                machine_type = machine_type,
                label      = "maintenance",
                confidence = random.uniform(0.0, 1.0),  
                window     = body.window,
            )

            ca_payload = {
                "machine_id":   body.machine_id,
                "machine_type": machine_type,
                "label":        "needs_maintenance",
                "confidence":   random.uniform(0.0, 1.0),
                "visual_url": [
                    visual_result["line_plot"],
                    visual_result["bar_chart"],
                ],
            }

            try:
                ca_resp = httpx.post("http://localhost:8005/anomaly", json=ca_payload)
                print(ca_resp.json())
                ca_payload["ca_status"] = ca_resp.json()
            except Exception as e:
                # CA being down should never crash the CNN response
                ca_payload["ca_status"] = {"error": str(e)}

            return ca_payload
        else:

            return {
                "machine_id": body.machine_id,
                "machine_type": machine_type,
                "label": "normal",
                "confidence": random.uniform(0.0, 1.0),
                "visual_url": [],
            }


    except FileNotFoundError as e:
        traceback.print_exc()
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)