import matplotlib
matplotlib.use("Agg")  
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

T_IN = 30 

BASE_DIR = Path(__file__).resolve().parent  
GRAPH_DIR = BASE_DIR.parent.parent / "Data" / "Graphs"
GRAPH_DIR.mkdir(exist_ok=True)

FEATURES = [
    "Temperature", "Vibration Level", "Power Consumption",
    "Pressure", "Material Flow Rate", "Cycle Time",
]

def _decode_machine_ids(data: np.ndarray) -> list[str]:
    labels = ["M001", "M002", "M003", "M004"]
    ids = []
    for row in data:
        one_hot = row[6:10]
        idx = np.argmax(one_hot)
        ids.append(labels[idx] if one_hot[idx] == 1.0 else "Unknown")
    return ids


def generate_visual(
    machine_id: str,
    machine_type: str,
    label:      str,
    confidence: float,
    window:     list[list[float]],
    ) -> dict:

    if window is None:  
        return {"status": "error", "reason": "no window found"}

    data        = np.array(window, dtype=np.float32)  # (30, 10)
    machine_ids = _decode_machine_ids(data)
    machine_set = set(machine_ids)
    title_suffix = f"Machine {machine_id} ({machine_type})  |  {label.upper()}  |  Confidence: {confidence:.1%}"

    # ── Line plot — one line per row, all 6 features on x-axis ───────────────
    plt.figure(figsize=(12, 6))
    time_steps = range(1, T_IN + 1)  # 1 to 30

    for i, feature in enumerate(FEATURES):
        plt.plot(time_steps, data[:, i], marker="o", linewidth=1.2,
                markersize=3, alpha=0.8, label=feature)

    plt.title(f"Feature trends across 30-row window\n{title_suffix}")
    plt.xlabel("Time Step")
    plt.ylabel("Normalised value")
    plt.xticks(time_steps[::2])  # show every 2nd tick to avoid crowding
    plt.legend(loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    line_path = GRAPH_DIR / f"{machine_id}_{machine_type}_line_plot.png"
    plt.savefig(line_path, dpi=120)
    plt.close()

    # ── Bar chart — column averages across all 30 rows ────────────────────────
    col_means = data[:, :6].mean(axis=0)
    plt.figure(figsize=(10, 6))
    plt.bar(FEATURES, col_means, color="skyblue")
    plt.title(f"Average feature values (30-row window)\n{title_suffix}")
    plt.xlabel("Feature")
    plt.ylabel("Average normalised value")
    plt.xticks(rotation=45)
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    bar_path = GRAPH_DIR / f"{machine_id}_{machine_type}_bar_chart.png"
    plt.savefig(bar_path, dpi=120)
    plt.close()

    print(f"  [VISUAL] Saved: {line_path}")
    print(f"  [VISUAL] Saved: {bar_path}")

    return {
        "line_plot": str(line_path),
        "bar_chart": str(bar_path),
    }   