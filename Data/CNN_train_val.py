import os
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow import keras 
from tensorflow.keras import layers
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau, Callback
from sklearn.preprocessing import StandardScaler, RobustScaler
import pickle
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_score, recall_score, f1_score, roc_auc_score
import json

load_dotenv()
CNN_saved_path = os.getenv('CNN_MODEL') # overall folder

PREPROC_CNC = os.getenv('PREPROC_CNC')
PREPROC_CON = os.getenv('PREPROC_CON')
PREPROC_DRI = os.getenv('PREPROC_DRI')
PREPROC_WEL = os.getenv('PREPROC_WEL')
Preproc_datasets = [PREPROC_CNC, PREPROC_CON, PREPROC_DRI, PREPROC_WEL]

T_in = 30 # number of past rows for input
T_out = 15 # number of future rows to predict

MACHINE_CONFIG = {
    'CNC': {
        'use_weighted_loss': False,   # Test: weighted loss helps with extreme downtime?
        'use_class_weights': True    # Test: class weights help with maintenance?
    },
    'Conveyor': {
        'use_weighted_loss': False,  # Conveyor already performs well with standard
        'use_class_weights': True    # Keep class weights (helped in Option D)
    },
    'Drill': {
        'use_weighted_loss': False,   # Test if weighted loss helps Drill
        'use_class_weights': False   # Class weights hurt Drill in Option D
    },
    'Welder': {
        'use_weighted_loss': False,  # Weighted loss hurt Welder in previous test
        'use_class_weights': False    # Keep class weights (Welder needs maintenance help)
    }
}

def split_dataset(csv_path, train_ratio=0.7, val_ratio=0.15, test_ratio=0.15):
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    n = len(df)
    train_end = int(n*train_ratio)
    val_end = train_end + int(n * val_ratio)

    train_df = df.iloc[:train_end].copy()
    val_df = df.iloc[train_end:val_end].copy()
    test_df = df.iloc[val_end:].copy()

    print(f"\n{split_dataset.__name__} - {os.path.basename(csv_path)}:")
    print(f"  Total rows: {n}")
    print(f"  Train: {len(train_df)} rows ({len(train_df)/n*100:.1f}%)")
    print(f"  Val:   {len(val_df)} rows ({len(val_df)/n*100:.1f}%)")
    print(f"  Test:  {len(test_df)} rows ({len(test_df)/n*100:.1f}%)")
    print(f"  Train period: {train_df['timestamp'].min()} to {train_df['timestamp'].max()}")
    print(f"  Val period:   {val_df['timestamp'].min()} to {val_df['timestamp'].max()}")
    print(f"  Test period:  {test_df['timestamp'].min()} to {test_df['timestamp'].max()}")
    
    return train_df, val_df, test_df

def calculate_aggregates(window_df):
    aggregates = []
    
    for col in window_df.columns:
        if col == 'error_rate':
            agg = window_df[col].max()
        elif col == 'downtime':
            agg = window_df[col].sum()
        elif col == 'maintenance_flag':
            agg = 1 if window_df[col].sum() > 0 else 0
        elif col == 'efficiency_score':
            agg = window_df[col].min()
        elif col == 'production_status':
            agg = window_df[col].iloc[-1]
        else:
            agg = window_df[col].mean()
        
        aggregates.append(agg)
    
    return np.array(aggregates)

def create_windows(df, feature_columns, target_columns,T_in, T_out):
    X_windows = []
    y_seq_windows = []
    y_agg_windows = []
    
    total_needed = T_in + T_out
    
    for i in range(len(df) - total_needed + 1):
        X_window = df[feature_columns].iloc[i:i+T_in].values.astype(np.float32)
        
        y_seq_window = df[target_columns].iloc[i+T_in:i+T_in+T_out].values.astype(np.float32)
        
        y_seq_df = df[target_columns].iloc[i+T_in:i+T_in+T_out]
        y_agg_window = calculate_aggregates(y_seq_df).astype(np.float32)
        
        X_windows.append(X_window)
        y_seq_windows.append(y_seq_window)
        y_agg_windows.append(y_agg_window)
    
    return np.array(X_windows), np.array(y_seq_windows), np.array(y_agg_windows)

def window_data(train_df, val_df, test_df, T_in, T_out):
    feature_columns = ['temperature', 'vibration_level', 'power_consumption', 
                       'pressure', 'material_flow_rate', 'cycle_time',
                       'machine_M001', 'machine_M002', 'machine_M003', 'machine_M004']
    
    target_columns = ['error_rate', 'downtime', 'maintenance_flag', 
                      'efficiency_score', 'production_status']
    
    print("\nCreating windows...")
    
    X_train, y_seq_train, y_agg_train = create_windows(
        train_df, feature_columns, target_columns, T_in, T_out
    )
    
    X_val, y_seq_val, y_agg_val = create_windows(
        val_df, feature_columns, target_columns, T_in, T_out
    )
    
    X_test, y_seq_test, y_agg_test = create_windows(
        test_df, feature_columns, target_columns, T_in, T_out
    )
    
    print(f"  Training:   X={X_train.shape}, y_seq={y_seq_train.shape}, y_agg={y_agg_train.shape}")
    print(f"  Validation: X={X_val.shape}, y_seq={y_seq_val.shape}, y_agg={y_agg_val.shape}")
    print(f"  Test:       X={X_test.shape}, y_seq={y_seq_test.shape}, y_agg={y_agg_test.shape}")
    
    return (X_train, y_seq_train, y_agg_train,
            X_val, y_seq_val, y_agg_val,
            X_test, y_seq_test, y_agg_test)

def extract_machine_type(csv_path):
    filename = os.path.basename(csv_path)
    
    filename_no_ext = filename.replace('.csv', '')
    
    machine_type = filename_no_ext.split('_')[-1]
    
    return machine_type

def calculate_maintenance_class_weights(y_train):
    """
    Calculate class weights for maintenance_present to handle imbalance
    
    Args:
        y_train: Training aggregated targets (shape: n_samples, n_features)
    
    Returns:
        Dictionary with class weights for binary classification
    """
    maintenance_labels = y_train[:, 2]  # maintenance_present is at index 2
    
    neg_count = np.sum(maintenance_labels == 0)
    pos_count = np.sum(maintenance_labels == 1)
    total = neg_count + pos_count
    
    if pos_count == 0:
        print("  Warning: No positive maintenance samples in training data!")
        return {0: 1.0, 1: 1.0}
    
    weight_for_0 = total / (2 * neg_count)
    weight_for_1 = total / (2 * pos_count)
    
    print(f"  Maintenance class distribution: neg={neg_count}, pos={pos_count}")
    print(f"  Class weights: class_0={weight_for_0:.4f}, class_1={weight_for_1:.4f}")
    
    return {0: weight_for_0, 1: weight_for_1}

def weighted_mse(y_true, y_pred):
    """
    Weighted MSE that gives higher weight to larger sum_downtime values
    This helps the model pay more attention to extreme downtime events
    """
    y_true_downtime = y_true[:, 1:2]
    y_pred_downtime = y_pred[:, 1:2]
    
    squared_error = tf.square(y_true_downtime - y_pred_downtime)
    
    max_downtime = tf.reduce_max(y_true_downtime) + 1e-8
    weights = 1.0 + (y_true_downtime / max_downtime)
    
    weighted_loss = tf.reduce_mean(weights * squared_error)
    
    other_targets_mask = tf.constant([1.0, 0.0, 1.0, 1.0, 1.0], dtype=tf.float32)
    other_targets_mask = tf.reshape(other_targets_mask, (1, -1))
    
    other_targets_pred = y_pred * other_targets_mask
    other_targets_true = y_true * other_targets_mask
    
    mse_other = tf.reduce_mean(tf.square(other_targets_true - other_targets_pred))
    
    return weighted_loss + mse_other

def build_multi_step_cnn(input_shape, output_shape):
    model = keras.Sequential([
        layers.Conv1D(filters=64, kernel_size=3, activation='relu', padding='causal', input_shape=input_shape),
        layers.BatchNormalization(),
        layers.MaxPooling1D(pool_size=2),
        layers.Conv1D(filters=128, kernel_size=3, activation='relu', padding='causal'),
        layers.BatchNormalization(),
        layers.MaxPooling1D(pool_size=2),
        layers.Conv1D(filters=256, kernel_size=3, activation='relu', padding='causal'),
        layers.BatchNormalization(),
        layers.GlobalAveragePooling1D(),
        layers.Dense(128, activation='relu'),
        layers.Dropout(0.3),
        layers.Dense(64, activation='relu'),
        layers.Dropout(0.2),
        layers.Dense(output_shape[0] * output_shape[1], activation='linear'),
        layers.Reshape(output_shape)
    ])

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss='mse',
        metrics=['mae', 'mse']
    )
    
    return model

def build_aggregated_cnn(input_shape, num_aggregated_features, use_weighted_loss=False):
    model = keras.Sequential([
        layers.Conv1D(filters=64, kernel_size=3, activation='relu', padding='causal', input_shape=input_shape),
        layers.BatchNormalization(),
        layers.MaxPooling1D(pool_size=2),
        layers.Conv1D(filters=128, kernel_size=3, activation='relu', padding='causal'),
        layers.BatchNormalization(),
        layers.MaxPooling1D(pool_size=2),
        layers.Conv1D(filters=256, kernel_size=3, activation='relu', padding='causal'),
        layers.BatchNormalization(),
        layers.GlobalAveragePooling1D(),
        layers.Dense(128, activation='relu'),
        layers.Dropout(0.3),
        layers.Dense(64, activation='relu'),
        layers.Dropout(0.2),
        layers.Dense(num_aggregated_features, activation='linear')
    ])
    
    if use_weighted_loss:
        loss = weighted_mse
    else:
        loss = 'mse'
    
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss=loss,
        metrics=['mae', 'mse']
    )
    
    return model

class PerTargetMetricCallback(Callback):
    """
    Custom callback to track per-target metrics during validation
    """
    def __init__(self, validation_data, target_names, scaler_y=None, is_sequence=False):
        super().__init__()
        self.validation_data = validation_data
        self.target_names = target_names
        self.scaler_y = scaler_y
        self.is_sequence = is_sequence
        self.val_per_target_metrics = {'mae': [], 'mse': []}
        
    def on_epoch_end(self, epoch, logs=None):
        X_val, y_val = self.validation_data
        
        # Get predictions
        y_pred = self.model.predict(X_val, verbose=0)
        
        # Inverse transform if scaler exists
        if self.scaler_y is not None:
            if self.is_sequence:
                # Reshape for inverse transform
                original_shape = y_pred.shape
                y_pred_reshaped = y_pred.reshape(-1, y_pred.shape[-1])
                y_val_reshaped = y_val.reshape(-1, y_val.shape[-1])
                
                y_pred_inv = self.scaler_y.inverse_transform(y_pred_reshaped)
                y_val_inv = self.scaler_y.inverse_transform(y_val_reshaped)
                
                y_pred = y_pred_inv.reshape(original_shape)
                y_val = y_val_inv.reshape(original_shape)
            else:
                y_pred = self.scaler_y.inverse_transform(y_pred)
                y_val = self.scaler_y.inverse_transform(y_val)
        
        # Calculate per-target metrics
        for i, target_name in enumerate(self.target_names):
            if self.is_sequence:
                # For sequence prediction, aggregate over timesteps
                y_pred_target = y_pred[:, :, i].flatten()
                y_val_target = y_val[:, :, i].flatten()
            else:
                # For aggregated prediction
                y_pred_target = y_pred[:, i]
                y_val_target = y_val[:, i]
            
            mae = mean_absolute_error(y_val_target, y_pred_target)
            mse = mean_squared_error(y_val_target, y_pred_target)
            
            # Store metrics
            if f'val_{target_name}_mae' not in logs:
                logs[f'val_{target_name}_mae'] = mae
                logs[f'val_{target_name}_mse'] = mse
            
            # Track in callback storage
            if target_name not in self.val_per_target_metrics['mae']:
                self.val_per_target_metrics['mae'].append({})
                self.val_per_target_metrics['mse'].append({})
            
            epoch_idx = len(self.val_per_target_metrics['mae']) - 1
            if epoch_idx < 0:
                epoch_idx = 0
                self.val_per_target_metrics['mae'].append({})
                self.val_per_target_metrics['mse'].append({})
            
            self.val_per_target_metrics['mae'][epoch_idx][target_name] = mae
            self.val_per_target_metrics['mse'][epoch_idx][target_name] = mse

class BinaryMetricCallback(Callback):
    """
    Custom callback to track binary classification metrics during validation
    """
    def __init__(self, validation_data, binary_target_names, threshold=0.5, scaler_y=None, is_sequence=False):
        super().__init__()
        self.validation_data = validation_data
        self.binary_target_names = binary_target_names
        self.threshold = threshold
        self.scaler_y = scaler_y
        self.is_sequence = is_sequence
        self.val_binary_metrics = {'precision': [], 'recall': [], 'f1': [], 'auc': []}
        
    def on_epoch_end(self, epoch, logs=None):
        X_val, y_val = self.validation_data
        
        # Get predictions
        y_pred = self.model.predict(X_val, verbose=0)
        
        # Inverse transform if scaler exists
        if self.scaler_y is not None:
            if self.is_sequence:
                original_shape = y_pred.shape
                y_pred_reshaped = y_pred.reshape(-1, y_pred.shape[-1])
                y_val_reshaped = y_val.reshape(-1, y_val.shape[-1])
                
                y_pred_inv = self.scaler_y.inverse_transform(y_pred_reshaped)
                y_val_inv = self.scaler_y.inverse_transform(y_val_reshaped)
                
                y_pred = y_pred_inv.reshape(original_shape)
                y_val = y_val_inv.reshape(original_shape)
            else:
                y_pred = self.scaler_y.inverse_transform(y_pred)
                y_val = self.scaler_y.inverse_transform(y_val)
        
        # Calculate per-target binary metrics
        epoch_metrics = {}
        for target_name in self.binary_target_names:
            # Find index of this target
            target_idx = None
            for i, name in enumerate(self.target_names_all):
                if name == target_name:
                    target_idx = i
                    break
            
            if target_idx is None:
                continue
            
            if self.is_sequence:
                # For sequence, take last timestep or aggregate?
                # Using last timestep for production_status, presence for maintenance_flag
                if target_name == 'maintenance_flag':
                    # Any maintenance in sequence
                    y_pred_target = (y_pred[:, :, target_idx] > self.threshold).any(axis=1).astype(int)
                    y_val_target = (y_val[:, :, target_idx] > 0.5).any(axis=1).astype(int)
                else:  # production_status
                    y_pred_target = (y_pred[:, -1, target_idx] > self.threshold).astype(int)
                    y_val_target = (y_val[:, -1, target_idx] > 0.5).astype(int)
            else:
                y_pred_target = (y_pred[:, target_idx] > self.threshold).astype(int)
                y_val_target = (y_val[:, target_idx] > 0.5).astype(int)
            
            # Calculate metrics
            precision = precision_score(y_val_target, y_pred_target, zero_division=0)
            recall = recall_score(y_val_target, y_pred_target, zero_division=0)
            f1 = f1_score(y_val_target, y_pred_target, zero_division=0)
            
            try:
                auc = roc_auc_score(y_val_target, y_pred[:, target_idx] if not self.is_sequence else y_pred[:, -1, target_idx])
            except:
                auc = 0.0
            
            epoch_metrics[f'val_{target_name}_precision'] = precision
            epoch_metrics[f'val_{target_name}_recall'] = recall
            epoch_metrics[f'val_{target_name}_f1'] = f1
            epoch_metrics[f'val_{target_name}_auc'] = auc
            
            # Update logs
            for key, value in epoch_metrics.items():
                logs[key] = value
            
            # Store in callback
            self.val_binary_metrics['precision'].append(epoch_metrics.get(f'val_{target_name}_precision', 0))
            self.val_binary_metrics['recall'].append(epoch_metrics.get(f'val_{target_name}_recall', 0))
            self.val_binary_metrics['f1'].append(epoch_metrics.get(f'val_{target_name}_f1', 0))
            self.val_binary_metrics['auc'].append(epoch_metrics.get(f'val_{target_name}_auc', 0))

def save_scaler(scaler, save_path):
    """Save scaler to disk"""
    with open(save_path, 'wb') as f:
        pickle.dump(scaler, f)
    print(f"  Scaler saved to {save_path}")

def train_multi_step_model(X_train, y_train, X_val, y_val, machine_type, save_dir):
    print(f"\n{'='*60}")
    print(f"Training MULTI-STEP model for {machine_type}")
    print(f"{'='*60}")

    model_dir = os.path.join(save_dir, machine_type, 'multi_step')
    os.makedirs(model_dir, exist_ok=True)
    
    print("\nScaling input features...")
    scaler_X = StandardScaler()
    X_train_scaled = scaler_X.fit_transform(X_train.reshape(-1, X_train.shape[-1]))
    X_train_scaled = X_train_scaled.reshape(X_train.shape)
    X_val_scaled = scaler_X.transform(X_val.reshape(-1, X_val.shape[-1]))
    X_val_scaled = X_val_scaled.reshape(X_val.shape)

    print("Scaling output targets...")
    scaler_y = StandardScaler()
    y_train_scaled = scaler_y.fit_transform(y_train.reshape(-1, y_train.shape[-1]))
    y_train_scaled = y_train_scaled.reshape(y_train.shape)
    y_val_scaled = scaler_y.transform(y_val.reshape(-1, y_val.shape[-1]))
    y_val_scaled = y_val_scaled.reshape(y_val.shape)

    save_scaler(scaler_X, os.path.join(model_dir, 'scaler_X.pkl'))
    save_scaler(scaler_y, os.path.join(model_dir, 'scaler_y_seq.pkl'))

    print("\nBuilding multi-step CNN model...")
    input_shape = (X_train.shape[1], X_train.shape[2])
    output_shape = (y_train.shape[1], y_train.shape[2])
    model = build_multi_step_cnn(input_shape, output_shape)
    model.summary()

    # Target names for per-target metrics
    target_names = ['error_rate', 'downtime', 'maintenance_flag', 'efficiency_score', 'production_status']
    binary_targets = ['maintenance_flag', 'production_status']
    
    # Custom callbacks for per-target metrics
    per_target_callback = PerTargetMetricCallback(
        validation_data=(X_val_scaled, y_val_scaled),
        target_names=target_names,
        scaler_y=scaler_y,
        is_sequence=True
    )
    
    binary_callback = BinaryMetricCallback(
        validation_data=(X_val_scaled, y_val_scaled),
        binary_target_names=binary_targets,
        scaler_y=scaler_y,
        is_sequence=True
    )
    binary_callback.target_names_all = target_names

    callbacks = [
        EarlyStopping(
            monitor='val_loss',
            patience=10,
            restore_best_weights=True,
            verbose=1
        ),
        ModelCheckpoint(
            filepath=os.path.join(model_dir, 'best_model.h5'),
            monitor='val_loss',
            save_best_only=True,
            verbose=1
        ),
        ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1
        ),
        per_target_callback,
        binary_callback
    ]

    print("\nTraining model...")
    history = model.fit(
        X_train_scaled, y_train_scaled,
        validation_data=(X_val_scaled, y_val_scaled),
        epochs=100,
        batch_size=32,
        callbacks=callbacks,
        verbose=1
    )

    model.save(os.path.join(model_dir, 'final_model.h5'))
    
    history_dict = {k: [float(v) for v in vals] for k, vals in history.history.items()}
    with open(os.path.join(model_dir, 'training_history.json'), 'w') as f:
        json.dump(history_dict, f, indent=2)
    
    with open(os.path.join(model_dir, 'per_target_metrics.json'), 'w') as f:
        json.dump(per_target_callback.val_per_target_metrics, f, indent=2)
    
    print(f"\n✅ Multi-step model training completed for {machine_type}")
    print(f"   Best validation loss: {min(history.history['val_loss']):.4f}")
    
    return model, history, scaler_X, scaler_y

def train_aggregated_model(X_train, y_train, X_val, y_val, machine_type, save_dir):
    print(f"\n{'='*60}")
    print(f"Training AGGREGATED model for {machine_type}")
    print(f"{'='*60}")
    
    # Get configuration for this machine type
    config = MACHINE_CONFIG.get(machine_type, {'use_weighted_loss': False, 'use_class_weights': False})
    use_weighted_loss = config['use_weighted_loss']
    use_class_weights = config['use_class_weights']
    
    print(f"  Configuration: weighted_loss={use_weighted_loss}, class_weights={use_class_weights}")
    
    model_dir = os.path.join(save_dir, machine_type, 'aggregated')
    os.makedirs(model_dir, exist_ok=True)
    
    print("\nScaling input features with RobustScaler...")
    scaler_X = RobustScaler()
    X_train_scaled = scaler_X.fit_transform(X_train.reshape(-1, X_train.shape[-1]))
    X_train_scaled = X_train_scaled.reshape(X_train.shape)
    X_val_scaled = scaler_X.transform(X_val.reshape(-1, X_val.shape[-1]))
    X_val_scaled = X_val_scaled.reshape(X_val.shape)

    print("Scaling output targets with RobustScaler...")
    scaler_y = RobustScaler()
    y_train_scaled = scaler_y.fit_transform(y_train)
    y_val_scaled = scaler_y.transform(y_val)
    
    save_scaler(scaler_X, os.path.join(model_dir, 'scaler_X.pkl'))
    save_scaler(scaler_y, os.path.join(model_dir, 'scaler_y_agg.pkl'))
    
    print("\nBuilding aggregated CNN model...")
    input_shape = (X_train.shape[1], X_train.shape[2])
    num_features = y_train.shape[1]
    model = build_aggregated_cnn(input_shape, num_features, use_weighted_loss=use_weighted_loss)
    model.summary()
    
    # Calculate class weights only if enabled
    class_weights = None
    if use_class_weights:
        class_weights = calculate_maintenance_class_weights(y_train)
    else:
        print("  Class weights: DISABLED")
    
    target_names = ['max_error_rate', 'sum_downtime', 'maintenance_present', 'min_efficiency', 'last_production_status']
    binary_targets = ['maintenance_present', 'last_production_status']
    
    per_target_callback = PerTargetMetricCallback(
        validation_data=(X_val_scaled, y_val_scaled),
        target_names=target_names,
        scaler_y=scaler_y,
        is_sequence=False
    )
    
    binary_callback = BinaryMetricCallback(
        validation_data=(X_val_scaled, y_val_scaled),
        binary_target_names=binary_targets,
        scaler_y=scaler_y,
        is_sequence=False
    )
    binary_callback.target_names_all = target_names
    
    callbacks = [
        EarlyStopping(
            monitor='val_loss',
            patience=10,
            restore_best_weights=True,
            verbose=1
        ),
        ModelCheckpoint(
            filepath=os.path.join(model_dir, 'best_model.h5'),
            monitor='val_loss',
            save_best_only=True,
            verbose=1
        ),
        ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1
        ),
        per_target_callback,
        binary_callback
    ]
    
    print("\nTraining model...")
    history = model.fit(
        X_train_scaled, y_train_scaled,
        validation_data=(X_val_scaled, y_val_scaled),
        epochs=100,
        batch_size=32,
        callbacks=callbacks,
        class_weight=class_weights,
        verbose=1
    )
    
    model.save(os.path.join(model_dir, 'final_model.h5'))
    
    history_dict = {k: [float(v) for v in vals] for k, vals in history.history.items()}
    with open(os.path.join(model_dir, 'training_history.json'), 'w') as f:
        json.dump(history_dict, f, indent=2)
    
    with open(os.path.join(model_dir, 'per_target_metrics.json'), 'w') as f:
        json.dump(per_target_callback.val_per_target_metrics, f, indent=2)
    
    # Save configuration used for this model
    config_path = os.path.join(model_dir, 'training_config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    if class_weights:
        class_weights_path = os.path.join(model_dir, 'class_weights.json')
        with open(class_weights_path, 'w') as f:
            json.dump(class_weights, f, indent=2)
    
    print(f"\n✅ Aggregated model training completed for {machine_type}")
    print(f"   Best validation loss: {min(history.history['val_loss']):.4f}")
    
    return model, history, scaler_X, scaler_y

if __name__ == '__main__':
    base_save_path = CNN_saved_path
    training_summary = {}
    
    for csv_path in Preproc_datasets:
        machine_type = extract_machine_type(csv_path)
        print(f"\n{'#'*60}")
        print(f"Processing {machine_type}")
        print(f"{'#'*60}")
        
        train_df, val_df, test_df = split_dataset(csv_path)
        
        (X_train, y_seq_train, y_agg_train,
         X_val, y_seq_val, y_agg_val,
         X_test, y_seq_test, y_agg_test) = window_data(train_df, val_df, test_df, T_in, T_out)
        
        multi_model, multi_history, multi_scaler_X, multi_scaler_y = train_multi_step_model(
            X_train, y_seq_train, X_val, y_seq_val, machine_type, base_save_path
        )
        
        agg_model, agg_history, agg_scaler_X, agg_scaler_y = train_aggregated_model(
            X_train, y_agg_train, X_val, y_agg_val, machine_type, base_save_path
        )
        
        training_summary[machine_type] = {
            'multi_step': {
                'best_val_loss': min(multi_history.history['val_loss']),
                'best_val_mae': min(multi_history.history['val_mae']),
                'total_epochs': len(multi_history.history['loss']),
                'scaler': 'standard'
            },
            'aggregated': {
                'best_val_loss': min(agg_history.history['val_loss']),
                'best_val_mae': min(agg_history.history['val_mae']),
                'total_epochs': len(agg_history.history['loss']),
                'scaler': 'robust'
            }
        }
        
        print(f"\n{'='*60}")
        print(f"✅ COMPLETED all training for {machine_type}")
        print(f"{'='*60}")
    
    summary_path = os.path.join(base_save_path, 'training_summary.json')
    with open(summary_path, 'w') as f:
        json.dump(training_summary, f, indent=2)
    
    print(f"\n{'#'*60}")
    print("TRAINING COMPLETE FOR ALL MACHINE TYPES")
    print(f"Summary saved to: {summary_path}")
    print(f"{'#'*60}")
    print("\nTraining Summary:")
    for machine, results in training_summary.items():
        print(f"\n{machine}:")
        print(f"  Multi-step - Best val loss: {results['multi_step']['best_val_loss']:.4f}, MAE: {results['multi_step']['best_val_mae']:.4f}")
        print(f"  Aggregated - Best val loss: {results['aggregated']['best_val_loss']:.4f}, MAE: {results['aggregated']['best_val_mae']:.4f}")