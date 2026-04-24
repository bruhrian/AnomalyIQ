import numpy as np
from sklearn.metrics import mean_absolute_error


INPUT_FEATURE_NAMES = [
    "temperature",
    "vibration_level",
    "power_consumption",
    "pressure",
    "material_flow_rate",
    "cycle_time",
    "machine_M001",
    "machine_M002",
    "machine_M003",
    "machine_M004",
]


def calculate_permutation_importance(
    model,
    X_test,
    y_test,
    scaler_y,
    feature_names,
    target_index=1,
    n_repeats=3,
    top_k=5,
):
    y_pred_scaled = model.predict(X_test, verbose=0)
    y_pred = scaler_y.inverse_transform(y_pred_scaled)

    baseline_mae = mean_absolute_error(y_test[:, target_index], y_pred[:, target_index])
    print(f"Baseline MAE for target {target_index}: {baseline_mae:.4f}")

    importance_scores = {}

    for feature_idx, feature_name in enumerate(feature_names):
        print(f"  Computing importance for {feature_name}...")
        score_drops = []

        for _ in range(n_repeats):
            X_test_shuffled = X_test.copy()
            np.random.shuffle(X_test_shuffled[:, :, feature_idx])

            y_pred_scaled_shuffled = model.predict(X_test_shuffled, verbose=0)
            y_pred_shuffled = scaler_y.inverse_transform(y_pred_scaled_shuffled)

            shuffled_mae = mean_absolute_error(y_test[:, target_index], y_pred_shuffled[:, target_index])
            score_drops.append(shuffled_mae - baseline_mae)

        importance_scores[feature_name] = float(np.mean(score_drops))

    ranked = sorted(importance_scores.items(), key=lambda item: item[1], reverse=True)
    top_features = ranked[:top_k]

    return {
        "baseline_mae": float(baseline_mae),
        "top_features": top_features,
        "all_ranked": ranked,
    }
