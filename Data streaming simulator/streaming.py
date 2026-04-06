import json

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import time
import sys
from datetime import datetime

CSV_PATH = "Production System Dataset.csv"
INTERVAL_SECONDS = 1 # Change to 10 or 3 for faster streaming

app = FastAPI()

def load_data(path: str) -> list[dict]:
    df = pd.read_csv(path)
    return df.to_dict(orient="records")

@app.get("/data")
def get_data():
    """Return all rows at once."""
    rows = load_data(CSV_PATH)
    return {"rows": rows}

def event_generator(rows, interval: int):
    total = len(rows)
    for i, row in enumerate(rows, start=1):
        ts = datetime.now().strftime("%H:%M:%S")

        # Build a structured payload
        payload = {
            "timestamp": ts,
            "row_num": i,
            "total": total,
            "machine_id": row["machine_id"],
            "machine_type": row["machine_type"],
            "temperature": row["temperature"],
            "vibration_level": row["vibration_level"],
            "power_consumption": row["power_consumption"],
            "pressure": row["pressure"],
            "material_flow_rate": row["material_flow_rate"],
            "cycle_time": row["cycle_time"]
        }

        yield f"data: {json.dumps(payload)}\n\n"
        time.sleep(interval)


@app.get("/stream")
def stream(interval: int = INTERVAL_SECONDS):
    rows = load_data(CSV_PATH)
    return StreamingResponse(event_generator(rows, interval), media_type="text/event-stream")