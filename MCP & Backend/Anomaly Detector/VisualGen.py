import json
import os
import re
from pathlib import Path
from datetime import datetime
from uuid import uuid4

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

T_IN = 30

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
GRAPH_DIR = REPO_ROOT / "Data" / "Graphs"
GRAPH_DIR.mkdir(exist_ok=True)

FEATURE_COLUMNS = [
    "temperature",
    "vibration_level",
    "power_consumption",
    "pressure",
    "material_flow_rate",
    "cycle_time",
]

FEATURE_LABELS = {
    "temperature": "Temperature",
    "vibration_level": "Vibration Level",
    "power_consumption": "Power Consumption",
    "pressure": "Pressure",
    "material_flow_rate": "Material Flow Rate",
    "cycle_time": "Cycle Time",
}

FEATURE_INDEX = {name: idx for idx, name in enumerate(FEATURE_COLUMNS)}


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_") or "unknown"


def _visual_stem(machine_id: str, machine_type: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = uuid4().hex[:8]
    return f"{_safe_slug(machine_id)}_{_safe_slug(machine_type)}_{timestamp}_{suffix}"


def _decode_machine_ids(data: np.ndarray) -> list[str]:
    labels = ["M001", "M002", "M003", "M004"]
    ids = []
    for row in data:
        one_hot = row[6:10]
        idx = np.argmax(one_hot)
        ids.append(labels[idx] if one_hot[idx] == 1.0 else "Unknown")
    return ids


def _metrics_path(machine_type: str) -> Path:
    model_root = os.getenv("CNN_MODEL", "").strip()
    if not model_root:
        return Path("")
    return Path(model_root) / machine_type / "aggregated" / "test_evaluation_metrics.json"


def _fallback_rank(data: np.ndarray) -> list[str]:
    scores = []
    for idx, feature in enumerate(FEATURE_COLUMNS):
        series = data[:, idx]
        volatility = float(np.std(series))
        range_span = float(np.max(series) - np.min(series))
        recent_shift = float(abs(series[-1] - np.mean(series)))
        score = volatility * 0.45 + range_span * 0.35 + recent_shift * 0.20
        scores.append((feature, score))
    return [name for name, _ in sorted(scores, key=lambda item: item[1], reverse=True)[:5]]


def _load_top_ranked_features(machine_type: str, data: np.ndarray) -> tuple[list[str], str]:
    metrics_path = _metrics_path(machine_type)
    if metrics_path.exists():
        try:
            payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            perm = payload.get("permutation_importance") or {}
            ranked = perm.get("top_5") or perm.get("all_ranked") or []
            selected = []
            for item in ranked:
                if isinstance(item, list) and item:
                    feature = str(item[0])
                elif isinstance(item, tuple) and item:
                    feature = str(item[0])
                else:
                    continue
                if feature in FEATURE_INDEX and feature not in selected:
                    selected.append(feature)
                if len(selected) == 5:
                    break
            if len(selected) == 5:
                return selected, "permutation rank"
        except Exception as exc:
            print(f"  [VISUAL] Could not load permutation ranks from {metrics_path}: {exc}")
    return _fallback_rank(data), "window anomaly intensity"


def _build_explanation(top_features: list[str], data: np.ndarray, confidence: float) -> list[str]:
    series_map = {feature: data[:, FEATURE_INDEX[feature]] for feature in top_features}
    hottest_feature = max(series_map.items(), key=lambda item: float(item[1][-1]))[0]
    most_volatile = max(series_map.items(), key=lambda item: float(np.std(item[1])))[0]
    steepest_change = max(
        series_map.items(),
        key=lambda item: float(abs(item[1][-1] - item[1][0])),
    )[0]
    return [
        f"Showing top 5 features most relevant to this anomaly window.",
        f"Highest latest value: {FEATURE_LABELS[hottest_feature]}.",
        f"Most volatile over 30 steps: {FEATURE_LABELS[most_volatile]}.",
        f"Largest start-to-end shift: {FEATURE_LABELS[steepest_change]}.",
        f"Model confidence for this anomaly: {confidence:.1%}.",
    ]


def generate_visual(
    machine_id: str,
    machine_type: str,
    label: str,
    confidence: float,
    window: list[list[float]],
) -> dict:

    if window is None:
        return {"status": "error", "reason": "no window found"}

    data = np.array(window, dtype=np.float32)
    if data.shape[0] < 2 or data.shape[1] < 6:
        return {"status": "error", "reason": f"unexpected window shape: {data.shape}"}

    machine_ids = _decode_machine_ids(data)
    machine_set = sorted(set(machine_ids))
    top_features, ranking_source = _load_top_ranked_features(machine_type, data)
    selected_indices = [FEATURE_INDEX[name] for name in top_features]
    selected_labels = [FEATURE_LABELS[name] for name in top_features]
    selected_data = data[:, selected_indices]
    explanation_lines = _build_explanation(top_features, data, confidence)
    title_suffix = (
        f"Machine {machine_id} ({machine_type}) | {label.upper()} | "
        f"Confidence: {confidence:.1%} | Window IDs: {', '.join(machine_set)}"
    )
    time_steps = np.arange(1, data.shape[0] + 1)

    # Line chart
    fig, ax = plt.subplots(figsize=(12.5, 7.2))
    colors = ["#7f1d1d", "#991b1b", "#b91c1c", "#dc2626", "#ef4444"]
    for i, feature in enumerate(top_features):
        ax.plot(
            time_steps,
            data[:, FEATURE_INDEX[feature]],
            marker="o",
            linewidth=2.0,
            markersize=3.5,
            alpha=0.95,
            color=colors[i],
            label=FEATURE_LABELS[feature],
        )

    ax.set_title(f"Top-5 Feature Trends Across 30-Step Anomaly Window\n{title_suffix}", fontsize=12, pad=18)
    ax.set_xlabel("Time Step")
    ax.set_ylabel("Normalized Value")
    ax.set_xticks(time_steps[::2])
    ax.grid(True, alpha=0.22, linestyle="--")
    ax.legend(loc="upper left", ncol=2, frameon=False, fontsize=9)
    fig.text(
        0.02,
        0.02,
        "\n".join(explanation_lines),
        fontsize=9,
        color="#4b5563",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#f8fafc", edgecolor="#d1d5db"),
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    file_stem = _visual_stem(machine_id, machine_type)
    line_path = GRAPH_DIR / f"{file_stem}_line_plot.png"
    fig.savefig(line_path, dpi=140)
    plt.close(fig)

    # Heatmap
    fig, ax = plt.subplots(figsize=(12.5, 6.8))
    im = ax.imshow(
        selected_data.T,
        aspect="auto",
        cmap="Reds",
        interpolation="nearest",
        vmin=float(np.percentile(selected_data, 5)),
        vmax=float(np.percentile(selected_data, 98)),
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("Normalized Value")
    ax.set_yticks(range(len(selected_labels)), selected_labels)
    ax.set_xticks(range(0, data.shape[0], 2), range(1, data.shape[0] + 1, 2))
    ax.set_title(f"Top-5 Ranked Feature Heatmap\n{title_suffix}", fontsize=12, pad=18)
    ax.set_xlabel("Time Step")
    ax.set_ylabel("Feature")
    fig.text(
        0.02,
        0.02,
        "Darker red means stronger activation in the anomaly window.\n"
        f"Features are ordered by {ranking_source}.",
        fontsize=9,
        color="#4b5563",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fff7f7", edgecolor="#fecaca"),
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    heatmap_path = GRAPH_DIR / f"{file_stem}_heatmap.png"
    fig.savefig(heatmap_path, dpi=140)
    plt.close(fig)

    print(f"  [VISUAL] Saved: {line_path}")
    print(f"  [VISUAL] Saved: {heatmap_path}")

    return {
        "line_plot": str(line_path),
        "heatmap": str(heatmap_path),
        "bar_chart": str(heatmap_path),
        "top_features": selected_labels,
        "explanation": explanation_lines,
    }
