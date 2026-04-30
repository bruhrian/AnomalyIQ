import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from CNN_train_val import CNN_saved_path, window_data, T_in, T_out, split_dataset, Preproc_datasets, extract_machine_type
import os
import pickle
import tensorflow as tf
from tensorflow import keras

base_save_path = CNN_saved_path

# Dictionary to store split information for each machine
split_info = {}

for csv_path in Preproc_datasets:
    machine_type = extract_machine_type(csv_path)
    train_df, val_df, test_df = split_dataset(csv_path)
    
    split_info[machine_type] = {
        'train': train_df,
        'val': val_df,
        'test': test_df,
        'train_range': (train_df['timestamp'].min(), train_df['timestamp'].max()),
        'val_range': (val_df['timestamp'].min(), val_df['timestamp'].max()),
        'test_range': (test_df['timestamp'].min(), test_df['timestamp'].max())
    }
    
    print(f"\n{machine_type}:")
    print(f"  Train: {train_df['timestamp'].min()} → {train_df['timestamp'].max()}")
    print(f"  Val:   {val_df['timestamp'].min()} → {val_df['timestamp'].max()}")
    print(f"  Test:  {test_df['timestamp'].min()} → {test_df['timestamp'].max()}")

# Check if splits are contiguous (no gaps or overlaps)
for machine_type, info in split_info.items():
    print(f"\n{machine_type}:")
    
    # Check train-val boundary
    train_end = info['train_range'][1]
    val_start = info['val_range'][0]
    print(f"  Train ends at: {train_end}")
    print(f"  Val starts at: {val_start}")
    print(f"  Gap between train and val: {(val_start - train_end).total_seconds() / 60} minutes")
    
    # Check val-test boundary
    val_end = info['val_range'][1]
    test_start = info['test_range'][0]
    print(f"  Val ends at: {val_end}")
    print(f"  Test starts at: {test_start}")
    print(f"  Gap between val and test: {(test_start - val_end).total_seconds() / 60} minutes")

# Define target columns
target_columns = ['error_rate', 'downtime', 'maintenance_flag', 'efficiency_score', 'production_status']

for machine_type, info in split_info.items():
    print(f"\n{'='*60}")
    print(f"Target Distribution - {machine_type}")
    print(f"{'='*60}")
    
    for target in target_columns:
        train_mean = info['train'][target].mean()
        val_mean = info['val'][target].mean()
        test_mean = info['test'][target].mean()
        
        train_std = info['train'][target].std()
        val_std = info['val'][target].std()
        test_std = info['test'][target].std()
        
        print(f"\n{target}:")
        print(f"  Train: mean={train_mean:.4f}, std={train_std:.4f}")
        print(f"  Val:   mean={val_mean:.4f}, std={val_std:.4f}")
        print(f"  Test:  mean={test_mean:.4f}, std={test_std:.4f}")
        
        # Highlight large differences
        if abs(test_mean - train_mean) / (train_mean + 1e-8) > 0.5:
            print(f"  ⚠️  WARNING: Test mean is >50% different from Train!")


# Detailed downtime analysis
for machine_type, info in split_info.items():
    print(f"\n{'='*60}")
    print(f"Downtime Analysis - {machine_type}")
    print(f"{'='*60}")
    
    for split_name, df in [('Train', info['train']), ('Val', info['val']), ('Test', info['test'])]:
        downtime = df['downtime']
        non_zero = downtime[downtime > 0]
        
        print(f"\n{split_name}:")
        print(f"  Total rows: {len(downtime)}")
        print(f"  Zero downtime rows: {(downtime == 0).sum()} ({(downtime == 0).mean()*100:.1f}%)")
        print(f"  Non-zero rows: {len(non_zero)} ({len(non_zero)/len(downtime)*100:.1f}%)")
        
        if len(non_zero) > 0:
            print(f"  Non-zero downtime - min: {non_zero.min():.2f}")
            print(f"  Non-zero downtime - max: {non_zero.max():.2f}")
            print(f"  Non-zero downtime - mean: {non_zero.mean():.2f}")
            print(f"  Non-zero downtime - median: {non_zero.median():.2f}")
            print(f"  Non-zero downtime - 95th percentile: {non_zero.quantile(0.95):.2f}")


# Check for outliers in test set
for machine_type, info in split_info.items():
    print(f"\n{'='*60}")
    print(f"Extreme Value Analysis - {machine_type}")
    print(f"{'='*60}")
    
    for target in target_columns:
        train_max = info['train'][target].max()
        test_max = info['test'][target].max()
        train_99th = info['train'][target].quantile(0.99)
        test_99th = info['test'][target].quantile(0.99)
        
        print(f"\n{target}:")
        print(f"  Train max: {train_max:.4f}")
        print(f"  Test max:  {test_max:.4f}")
        print(f"  Train 99th percentile: {train_99th:.4f}")
        print(f"  Test 99th percentile:  {test_99th:.4f}")
        
        if test_max > train_max * 2:
            print(f"  ⚠️  Test max is >2x Train max!")

fig, axes = plt.subplots(4, 1, figsize=(14, 16))
fig.suptitle('Downtime Distribution: Train vs Val vs Test', fontsize=16)

for idx, (machine_type, info) in enumerate(split_info.items()):
    ax = axes[idx]
    
    # Plot distributions (log scale due to extreme values)
    ax.hist(info['train']['downtime'], bins=50, alpha=0.5, label='Train', density=True)
    ax.hist(info['val']['downtime'], bins=50, alpha=0.5, label='Validation', density=True)
    ax.hist(info['test']['downtime'], bins=50, alpha=0.5, label='Test', density=True)
    
    ax.set_yscale('log')
    ax.set_xlabel('Downtime')
    ax.set_ylabel('Density (log scale)')
    ax.set_title(f'{machine_type}')
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# Check if downtime increases over time (potential concept drift)
for machine_type, info in split_info.items():
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f'{machine_type} - Temporal Trends', fontsize=14)
    
    # Combine all data with split labels
    train_df = info['train'].copy()
    train_df['split'] = 'Train'
    val_df = info['val'].copy()
    val_df['split'] = 'Validation'
    test_df = info['test'].copy()
    test_df['split'] = 'Test'
    
    combined = pd.concat([train_df, val_df, test_df])
    combined = combined.sort_values('timestamp')
    
    # Plot downtime over time
    ax1 = axes[0]
    ax1.plot(combined['timestamp'], combined['downtime'], alpha=0.5, linewidth=0.5)
    
    # Add split boundaries
    train_end = info['train']['timestamp'].max()
    val_end = info['val']['timestamp'].max()
    ax1.axvline(x=train_end, color='red', linestyle='--', label='Train/Val Split')
    ax1.axvline(x=val_end, color='orange', linestyle='--', label='Val/Test Split')
    
    ax1.set_xlabel('Timestamp')
    ax1.set_ylabel('Downtime')
    ax1.set_title('Downtime Over Time')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Rolling mean of downtime
    ax2 = axes[1]
    rolling_window = 1000  # Adjust based on data size
    rolling_mean = combined['downtime'].rolling(window=rolling_window, min_periods=50).mean()
    ax2.plot(combined['timestamp'], rolling_mean, color='blue', linewidth=1)
    ax2.axvline(x=train_end, color='red', linestyle='--', label='Train/Val Split')
    ax2.axvline(x=val_end, color='orange', linestyle='--', label='Val/Test Split')
    
    ax2.set_xlabel('Timestamp')
    ax2.set_ylabel(f'Downtime ({rolling_window}-point rolling mean)')
    ax2.set_title('Downtime Trend (Rolling Mean)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()

for machine_type, info in split_info.items():
    print(f"\n{'='*60}")
    print(f"Window Analysis - {machine_type}")
    print(f"{'='*60}")
    
    # Get windows
    (X_train, y_seq_train, y_agg_train,
     X_val, y_seq_val, y_agg_val,
     X_test, y_seq_test, y_agg_test) = window_data(
        info['train'], info['val'], info['test'], T_in, T_out
    )
    
    print(f"\nNumber of windows:")
    print(f"  Train windows: {len(X_train)}")
    print(f"  Val windows: {len(X_val)}")
    print(f"  Test windows: {len(X_test)}")
    
    # Check aggregated target distributions
    print(f"\nAggregated sum_downtime distribution:")
    print(f"  Train: mean={y_agg_train[:, 1].mean():.2f}, max={y_agg_train[:, 1].max():.2f}")
    print(f"  Val:   mean={y_agg_val[:, 1].mean():.2f}, max={y_agg_val[:, 1].max():.2f}")
    print(f"  Test:  mean={y_agg_test[:, 1].mean():.2f}, max={y_agg_test[:, 1].max():.2f}")

# ==================== PRIORITY 3: Inverse Transform Test ====================

# Pick CNC for testing (or any machine type)
machine_type = "CNC"
agg_model_dir = os.path.join(base_save_path, machine_type, 'aggregated')

# Load scaler
with open(os.path.join(agg_model_dir, 'scaler_y_agg.pkl'), 'rb') as f:
    scaler_y_agg = pickle.load(f)

# Get a sample of actual y_agg_test values (all 5 features)
sample_actual_full = y_agg_test[:5, :]  # Take all 5 columns for first 5 samples
print(f"Actual full targets (first 5 samples):\n{sample_actual_full}")

# Extract just sum_downtime (index 1) for display
sample_actual_downtime = sample_actual_full[:, 1]
print(f"\nActual sum_downtime (before scaling): {sample_actual_downtime}")

# Transform ALL 5 features together
sample_scaled_full = scaler_y_agg.transform(sample_actual_full)
print(f"\nScaled values (all 5 features):\n{sample_scaled_full}")

# Extract just the scaled sum_downtime (column 1)
sample_scaled_downtime = sample_scaled_full[:, 1]
print(f"\nScaled sum_downtime: {sample_scaled_downtime}")

# Inverse transform back (all 5 features)
sample_inv_full = scaler_y_agg.inverse_transform(sample_scaled_full)
print(f"\nInverse transformed (all 5 features):\n{sample_inv_full}")

# Extract just the inverse sum_downtime (column 1)
sample_inv_downtime = sample_inv_full[:, 1]
print(f"\nInverse transformed sum_downtime: {sample_inv_downtime}")

# Check if inverse matches original
print(f"\nMatch: {np.allclose(sample_actual_full, sample_inv_full)}")


print(f"\n{'='*60}")
print(f"\nPriority 4")
print(f"\n{'='*60}")

# ==================== PRIORITY 4: Examine Model Predictions ====================

import tensorflow as tf
from tensorflow import keras

machine_type = "CNC"
agg_model_dir = os.path.join(base_save_path, machine_type, 'aggregated')

# Load the model
model_path = os.path.join(agg_model_dir, 'best_model.h5')
model = keras.models.load_model(model_path, compile=False)
print(f"Model loaded from: {model_path}")

# Load scalers
with open(os.path.join(agg_model_dir, 'scaler_X.pkl'), 'rb') as f:
    scaler_X = pickle.load(f)
with open(os.path.join(agg_model_dir, 'scaler_y_agg.pkl'), 'rb') as f:
    scaler_y = pickle.load(f)

# Get test data for CNC from the window analysis
# Re-run window_data for CNC to get test data
for machine_type_temp, info in split_info.items():
    if machine_type_temp == "CNC":
        (X_train, y_seq_train, y_agg_train,
         X_val, y_seq_val, y_agg_val,
         X_test, y_seq_test, y_agg_test) = window_data(
            info['train'], info['val'], info['test'], T_in, T_out
        )
        break

print(f"\nTest data shape:")
print(f"  X_test: {X_test.shape}")
print(f"  y_agg_test: {y_agg_test.shape}")

# Scale test inputs
X_test_scaled = scaler_X.transform(X_test.reshape(-1, X_test.shape[-1]))
X_test_scaled = X_test_scaled.reshape(X_test.shape)

# Get model predictions (scaled)
y_pred_scaled = model.predict(X_test_scaled, verbose=0)
print(f"\nPredictions (scaled) shape: {y_pred_scaled.shape}")

# Inverse transform predictions
y_pred_inv = scaler_y.inverse_transform(y_pred_scaled)
print(f"\nPredictions (inverse transformed) shape: {y_pred_inv.shape}")

# Compare predictions vs actual for first 10 test samples
print("\n" + "="*80)
print("COMPARISON: Model Predictions vs Actual Targets (First 10 Test Samples)")
print("="*80)
print(f"{'Sample':<8} {'Pred_sum_downtime':<20} {'Actual_sum_downtime':<20} {'Error':<15} {'Error_Ratio':<12}")
print("-"*80)

for i in range(min(10, len(y_pred_inv))):
    pred_downtime = y_pred_inv[i, 1]  # sum_downtime is index 1
    actual_downtime = y_agg_test[i, 1]
    error = pred_downtime - actual_downtime
    error_ratio = pred_downtime / actual_downtime if actual_downtime > 0 else float('inf')
    
    print(f"{i:<8} {pred_downtime:<20.2f} {actual_downtime:<20.2f} {error:<15.2f} {error_ratio:<12.2f}")

# Summary statistics
print("\n" + "="*80)
print("SUMMARY STATISTICS - sum_downtime")
print("="*80)

pred_downtime_all = y_pred_inv[:, 1]
actual_downtime_all = y_agg_test[:, 1]

print(f"\nPredictions:")
print(f"  Mean: {pred_downtime_all.mean():.2f}")
print(f"  Std:  {pred_downtime_all.std():.2f}")
print(f"  Min:  {pred_downtime_all.min():.2f}")
print(f"  Max:  {pred_downtime_all.max():.2f}")

print(f"\nActual:")
print(f"  Mean: {actual_downtime_all.mean():.2f}")
print(f"  Std:  {actual_downtime_all.std():.2f}")
print(f"  Min:  {actual_downtime_all.min():.2f}")
print(f"  Max:  {actual_downtime_all.max():.2f}")

print(f"\nPrediction vs Actual:")
print(f"  MAE: {np.mean(np.abs(pred_downtime_all - actual_downtime_all)):.2f}")
print(f"  RMSE: {np.sqrt(np.mean((pred_downtime_all - actual_downtime_all)**2)):.2f}")
print(f"  Correlation: {np.corrcoef(pred_downtime_all, actual_downtime_all)[0,1]:.4f}")

# Check if predictions are ~100x larger than actual
ratio = pred_downtime_all / actual_downtime_all
ratio_filtered = ratio[~np.isinf(ratio) & ~np.isnan(ratio)]
if len(ratio_filtered) > 0:
    print(f"\nAverage prediction/actual ratio: {ratio_filtered.mean():.2f}")
    if ratio_filtered.mean() > 10:
        print(f"  ⚠️  WARNING: Predictions are {ratio_filtered.mean():.1f}x larger than actual!")

# Also check other targets
print("\n" + "="*80)
print("OTHER TARGETS - First 5 Test Samples")
print("="*80)

for i in range(min(5, len(y_pred_inv))):
    print(f"\nSample {i}:")
    print(f"  max_error_rate:      Pred={y_pred_inv[i,0]:.4f}, Actual={y_agg_test[i,0]:.4f}")
    print(f"  sum_downtime:        Pred={y_pred_inv[i,1]:.2f}, Actual={y_agg_test[i,1]:.2f}")
    print(f"  maintenance_present: Pred={y_pred_inv[i,2]:.4f}, Actual={y_agg_test[i,2]:.0f}")
    print(f"  min_efficiency:      Pred={y_pred_inv[i,3]:.4f}, Actual={y_agg_test[i,3]:.4f}")
    print(f"  last_production_status: Pred={y_pred_inv[i,4]:.4f}, Actual={y_agg_test[i,4]:.0f}")