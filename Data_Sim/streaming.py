import json
import math
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, Response
import time
from datetime import datetime
import uvicorn
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def resolve(path_str: str):
    if not path_str:
        raise ValueError("Path is missing (env variable not set)")
    return (REPO_ROOT / path_str).resolve()

REPO_ROOT = Path(__file__).resolve().parents[1]

CSV_PATH = resolve(os.getenv('MAIN_DATASET'))
INTERVAL_SECONDS = 1

app = FastAPI()

def load_data(path: str) -> list[dict]:
    df = pd.read_csv(path)
    return df.to_dict(orient="records")

def clean_row(row: dict) -> dict:
    cleaned = {}
    for k, v in row.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned

@app.get("/data")
def get_data():
    rows = load_data(CSV_PATH)
    cleaned_rows = [clean_row(r) for r in rows]
    return Response(
        content=json.dumps({"rows": cleaned_rows}),
        media_type="application/json"
    )

def event_generator(rows, interval: int):
    total = len(rows)
    for i, row in enumerate(rows, start=1):
        ts = datetime.now().strftime("%H:%M:%S")
        payload = clean_row({
            "timestamp":          ts,
            "row_num":            i,
            "total":              total,
            "machine_id":         row["machine_id"],
            "machine_type":       row["machine_type"],
            "temperature":        row["temperature"],
            "vibration_level":    row["vibration_level"],
            "power_consumption":  row["power_consumption"],
            "pressure":           row["pressure"],
            "material_flow_rate": row["material_flow_rate"],
            "cycle_time":         row["cycle_time"],
        })
        yield f"data: {json.dumps(payload)}\n\n"
        time.sleep(interval)

@app.get("/stream")
def stream(interval: int = INTERVAL_SECONDS):
    rows = load_data(CSV_PATH)
    return StreamingResponse(event_generator(rows, interval), media_type="text/event-stream")

@app.get("/health")
def health():
    try:
        if not CSV_PATH or not os.path.exists(CSV_PATH):
            return {"status": "error", "detail": "CSV not found"}
        df = pd.read_csv(CSV_PATH, nrows=1)  # 只读1行
        return {"status": "ok", "detail": "CSV reachable"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:60]}
        
if __name__ == "__main__":
    uvicorn.run("streaming:app", host="0.0.0.0", port=8000, reload=False)
