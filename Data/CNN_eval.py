import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_score, recall_score, f1_score, roc_auc_score
import json
import os
import pickle
import pandas as pd
from dotenv import load_dotenv
from tensorflow import keras

from CNN_train_val import T_in, T_out, Preproc_datasets, split_dataset,  window_data, extract_machine_type

load_dotenv()
CNN_saved_path = os.getenv('CNN_MODEL') # overall folder

def inverse_transform_sequence(predictions, targets, scaler_y, is_sequence=True):
    if is_sequence:
        original_shape = predictions.shape
        predictions_reshaped = predictions.reshape(-1, predictions.shape[-1])
        targets_reshaped = targets.reshape(-1, targets.shape[-1])
        
        predictions_inv = scaler_y.inverse_transform(predictions_reshaped)
        targets_inv = scaler_y.inverse_transform(targets_reshaped)
       
        predictions_inv = predictions_inv.reshape(original_shape)
        targets_inv = targets_inv.reshape(original_shape)
    else:
        predictions_inv = scaler_y.inverse_transform(predictions)
        targets_inv = scaler_y.inverse_transform(targets)
    
    return predictions_inv, targets_inv

def calculate_regression_metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))

    epsilon = 1e-10
    mape = np.mean(np.abs((y_true - y_pred) / (y_true + epsilon))) * 100
    
    return {'mae': mae, 'rmse': rmse, 'mape': mape}

def calculate_binary_metrics(y_true, y_pred_proba, threshold=0.5):
    y_pred_binary = (y_pred_proba >= threshold).astype(int)
    
    precision = precision_score(y_true, y_pred_binary, zero_division=0)
    recall = recall_score(y_true, y_pred_binary, zero_division=0)
    f1 = f1_score(y_true, y_pred_binary, zero_division=0)
    
    try:
        auc = roc_auc_score(y_true, y_pred_proba)
    except:
        auc = 0.0
    
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'auc': auc,
        'threshold': threshold
    }

def evaluate_multi_step_model(model_dir, X_test, y_test, scaler_X, scaler_y, machine_type):
    print(f"\n{'='*60}")
    print(f"Evaluating MULTI-STEP model for {machine_type}")
    print(f"{'='*60}")
    
    model_path = os.path.join(model_dir, 'best_model.h5')
    model = keras.models.load_model(model_path, compile = False)
    # print(f"Loaded model from {model_path}")
    
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss='mse',
        metrics=['mae', 'mse']
    )
    # print(f"Loaded and recompiled model from {model_path}")

    y_pred_scaled = model.predict(X_test, verbose=0)
    
    y_pred, y_test_inv = inverse_transform_sequence(y_pred_scaled, y_test, scaler_y, is_sequence=True)
    
    target_names = ['error_rate', 'downtime', 'maintenance_flag', 'efficiency_score', 'production_status']
    binary_targets = ['maintenance_flag', 'production_status']
    
    metrics = {}
    
    for i, target_name in enumerate(target_names):
        y_pred_target = y_pred[:, :, i].flatten()
        y_true_continuous = y_test_inv[:, :, i].flatten()
        
        if target_name in binary_targets:
            y_true_binary = (y_true_continuous >= 0.5).astype(int)
            binary_metrics = calculate_binary_metrics(y_true_binary, y_pred_target, threshold=0.5)
            metrics[target_name] = binary_metrics
        else:
            regression_metrics = calculate_regression_metrics(y_true_continuous, y_pred_target)
            metrics[target_name] = regression_metrics
    
    timestep_metrics = {}
    for t in range(y_pred.shape[1]):
        timestep_metrics[f'timestep_{t+1}'] = {}
        for i, target_name in enumerate(target_names):
            y_pred_t = y_pred[:, t, i]
            y_true_continuous_t = y_test_inv[:, t, i]
            
            if target_name in binary_targets:
                y_true_binary_t = (y_true_continuous_t >= 0.5).astype(int)
                timestep_metrics[f'timestep_{t+1}'][target_name] = calculate_binary_metrics(y_true_binary_t, y_pred_t, threshold=0.5)
            else:
                timestep_metrics[f'timestep_{t+1}'][target_name] = calculate_regression_metrics(y_true_continuous_t, y_pred_t)
        
    results = {
        'per_target_metrics': metrics,
        'per_timestep_metrics': timestep_metrics,
        'model_path': model_path
    }
    
    results_path = os.path.join(model_dir, 'test_evaluation_metrics.json')
    with open(results_path, 'w') as f:
        def convert_to_serializable(obj):
            if isinstance(obj, np.float32) or isinstance(obj, np.float64):
                return float(obj)
            return obj
        
        json.dump(results, f, indent=2, default=convert_to_serializable)
    
    print(f"✅ Multi-step evaluation completed for {machine_type}")
    print(f"   Results saved to: {results_path}")
    
    return results

def evaluate_aggregated_model(model_dir, X_test, y_test, scaler_X, scaler_y, machine_type):
    print(f"\n{'='*60}")
    print(f"Evaluating AGGREGATED model for {machine_type}")
    print(f"{'='*60}")
    
    model_path = os.path.join(model_dir, 'best_model.h5')
    model = keras.models.load_model(model_path, compile = False)
    # print(f"Loaded model from {model_path}")
    
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss='mse',
        metrics=['mae', 'mse']
    )
    # print(f"Loaded and recompiled model from {model_path}")

    y_pred_scaled = model.predict(X_test, verbose=0)
    
    # Only inverse transform predictions, targets are already in original scale
    y_pred_inv = scaler_y.inverse_transform(y_pred_scaled)
    y_test_inv = y_test  # y_test is already in original scale from window_data

    # DEBUG: Check model predictions vs actual
    print(f"\nDEBUG - {machine_type} predictions (first 5 samples, inverse transformed):")
    for i in range(min(5, len(y_pred_inv))):
        print(f"  Sample {i}: sum_downtime pred={y_pred_inv[i, 1]:.2f}, actual={y_test_inv[i, 1]:.2f}")
    
    target_names = [
        'max_error_rate',
        'sum_downtime', 
        'maintenance_present',
        'min_efficiency',
        'last_production_status'
    ]

    num_other_features = y_test.shape[1] - 5
    for i in range(num_other_features):
        target_names.append(f'mean_feature_{i+1}')
    
    binary_targets = ['maintenance_present', 'last_production_status']
    
    metrics = {}
    
    for i, target_name in enumerate(target_names):
        y_pred_target = y_pred_inv[:, i]
        y_true_continuous = y_test_inv[:, i]
        
        if target_name in binary_targets:
            # Convert actual continuous values to binary using threshold
            y_true_binary = (y_true_continuous >= 0.5).astype(int)
            binary_metrics = calculate_binary_metrics(y_true_binary, y_pred_target, threshold=0.5)
            metrics[target_name] = binary_metrics
        else:
            regression_metrics = calculate_regression_metrics(y_true_continuous, y_pred_target)
            metrics[target_name] = regression_metrics
    
    results = {
        'per_target_metrics': metrics,
        'model_path': model_path,
        'num_samples': len(y_test),
        'target_names': target_names
    }
    
    results_path = os.path.join(model_dir, 'test_evaluation_metrics.json')
    with open(results_path, 'w') as f:
        def convert_to_serializable(obj):
            if isinstance(obj, np.float32) or isinstance(obj, np.float64):
                return float(obj)
            return obj
        
        json.dump(results, f, indent=2, default=convert_to_serializable)
    
    print(f"✅ Aggregated evaluation completed for {machine_type}")
    print(f"   Results saved to: {results_path}")
    
    return results

def compare_validation_vs_test(val_metrics_path, test_metrics_path):
    with open(val_metrics_path, 'r') as f:
        val_metrics = json.load(f)
    
    with open(test_metrics_path, 'r') as f:
        test_metrics = json.load(f)
    
    comparison = {}
    
    val_final = {
        'mae': val_metrics['mae'][-1] if val_metrics['mae'] else {},
        'mse': val_metrics['mse'][-1] if val_metrics['mse'] else {}
    }
    
    test_per_target = test_metrics['per_target_metrics']
    
    for target in test_per_target.keys():
        comparison[target] = {}
        
        if 'mae' in test_per_target[target]:
            val_mae = val_final['mae'].get(target, None)
            test_mae = test_per_target[target]['mae']
            comparison[target]['val_mae'] = val_mae
            comparison[target]['test_mae'] = test_mae
            comparison[target]['mae_gap'] = test_mae - val_mae if val_mae else None
            
            test_rmse = test_per_target[target].get('rmse', None)
            if test_rmse:
                comparison[target]['test_rmse'] = test_rmse
        else:
            val_f1 = None
            for epoch_metrics in val_metrics.get('f1', []):
                if target in epoch_metrics:
                    val_f1 = epoch_metrics[target]
                    break
            
            test_f1 = test_per_target[target]['f1']
            comparison[target]['val_f1'] = val_f1
            comparison[target]['test_f1'] = test_f1
            comparison[target]['f1_gap'] = test_f1 - val_f1 if val_f1 else None
    
    return comparison

def generate_cross_machine_comparison(machines_data, save_path):
    comparison = {
        'regression_targets': {},
        'binary_targets': {}
    }
    first_machine = list(machines_data.keys())[0]
    for target, metrics in machines_data[first_machine]['aggregated']['per_target_metrics'].items():
        if 'precision' in metrics:
            comparison['binary_targets'][target] = {}
        else:
            comparison['regression_targets'][target] = {}

    for target in comparison['regression_targets'].keys():
        for machine_type, data in machines_data.items():
            metrics = data['aggregated']['per_target_metrics'].get(target, {})
            comparison['regression_targets'][target][machine_type] = {
                'mae': metrics.get('mae', None),
                'rmse': metrics.get('rmse', None),
                'mape': metrics.get('mape', None)
            }
    
    for target in comparison['binary_targets'].keys():
        for machine_type, data in machines_data.items():
            metrics = data['aggregated']['per_target_metrics'].get(target, {})
            comparison['binary_targets'][target][machine_type] = {
                'precision': metrics.get('precision', None),
                'recall': metrics.get('recall', None),
                'f1': metrics.get('f1', None),
                'auc': metrics.get('auc', None)
            }
    
    rankings = {}
    for target in comparison['regression_targets'].keys():
        mae_values = []
        for machine_type, machine_metrics in comparison['regression_targets'].items():
            target_metrics = machine_metrics.get(target, {})
            mae_value = target_metrics.get('mae')
            if mae_value is not None:
                mae_values.append((machine_type, mae_value))
        
        sorted_mae = sorted(mae_values, key=lambda x: x[1])
        rankings[target] = {
            'best': sorted_mae[0][0] if sorted_mae else None,
            'worst': sorted_mae[-1][0] if sorted_mae else None,
            'ranking': [m[0] for m in sorted_mae]
        }
    
    for target in comparison['binary_targets'].keys():
        f1_values = []
        for machine_type, machine_metrics in comparison['binary_targets'].items():
            target_metrics = machine_metrics.get(target, {})
            f1_value = target_metrics.get('f1')
            if f1_value is not None:
                f1_values.append((machine_type, f1_value))
        
        sorted_f1 = sorted(f1_values, key=lambda x: x[1], reverse=True)
        rankings[target] = {
            'best': sorted_f1[0][0] if sorted_f1 else None,
            'worst': sorted_f1[-1][0] if sorted_f1 else None,
            'ranking': [m[0] for m in sorted_f1]
        }
    
    comparison['rankings'] = rankings
    
    with open(save_path, 'w') as f:
        def convert_to_serializable(obj):
            if isinstance(obj, np.float32) or isinstance(obj, np.float64):
                return float(obj)
            return obj
        
        json.dump(comparison, f, indent=2, default=convert_to_serializable)
    
    print(f"\n✅ Cross-machine comparison saved to: {save_path}")
    
    print("\n" + "="*60)
    print("CROSS-MACHINE COMPARISON SUMMARY")
    print("="*60)
    
    for target, ranking in rankings.items():
        print(f"\n{target}:")
        print(f"  Best: {ranking['best']}")
        print(f"  Worst: {ranking['worst']}")
        print(f"  Ranking: {' → '.join(ranking['ranking'])}")
    
    return comparison

if __name__ == '__main__':
    base_save_path = CNN_saved_path
    
    evaluation_summary = {
        'multi_step': {},
        'aggregated': {}
    }
    
    all_machines_data = {}
    
    for csv_path in Preproc_datasets:
        machine_type = extract_machine_type(csv_path)
        print(f"\n{'#'*60}")
        print(f"Evaluating {machine_type}")
        print(f"{'#'*60}")
        
        train_df, val_df, test_df = split_dataset(csv_path)
        
        (X_train, y_seq_train, y_agg_train,
         X_val, y_seq_val, y_agg_val,
         X_test, y_seq_test, y_agg_test) = window_data(train_df, val_df, test_df, T_in, T_out)
        

        print(f"\nDEBUG - {machine_type} y_agg_test column means:")
        for i in range(y_agg_test.shape[1]):
            print(f"  Column {i}: mean={y_agg_test[:, i].mean():.2f}, max={y_agg_test[:, i].max():.2f}")


        multi_model_dir = os.path.join(base_save_path, machine_type, 'multi_step')
        
        with open(os.path.join(multi_model_dir, 'scaler_X.pkl'), 'rb') as f:
            scaler_X_multi = pickle.load(f)
        with open(os.path.join(multi_model_dir, 'scaler_y_seq.pkl'), 'rb') as f:
            scaler_y_seq = pickle.load(f)
        
        X_test_scaled = scaler_X_multi.transform(X_test.reshape(-1, X_test.shape[-1]))
        X_test_scaled = X_test_scaled.reshape(X_test.shape)
        
        multi_results = evaluate_multi_step_model(
            multi_model_dir, X_test_scaled, y_seq_test, scaler_X_multi, scaler_y_seq, machine_type
        )
        evaluation_summary['multi_step'][machine_type] = multi_results
        
        agg_model_dir = os.path.join(base_save_path, machine_type, 'aggregated')
        
        with open(os.path.join(agg_model_dir, 'scaler_X.pkl'), 'rb') as f:
            scaler_X_agg = pickle.load(f)
        with open(os.path.join(agg_model_dir, 'scaler_y_agg.pkl'), 'rb') as f:
            scaler_y_agg = pickle.load(f)
        
        X_test_scaled_agg = scaler_X_agg.transform(X_test.reshape(-1, X_test.shape[-1]))
        X_test_scaled_agg = X_test_scaled_agg.reshape(X_test.shape)
        
        agg_results = evaluate_aggregated_model(
            agg_model_dir, X_test_scaled_agg, y_agg_test, scaler_X_agg, scaler_y_agg, machine_type
        )
        evaluation_summary['aggregated'][machine_type] = agg_results
        
        all_machines_data[machine_type] = {
            'multi_step': multi_results,
            'aggregated': agg_results
        }
        
        val_metrics_path = os.path.join(agg_model_dir, 'per_target_metrics.json')
        test_metrics_path = os.path.join(agg_model_dir, 'test_evaluation_metrics.json')
        
        if os.path.exists(val_metrics_path) and os.path.exists(test_metrics_path):
            comparison = compare_validation_vs_test(val_metrics_path, test_metrics_path)
            
            comparison_path = os.path.join(agg_model_dir, 'validation_vs_test_comparison.json')
            with open(comparison_path, 'w') as f:
                def convert_to_serializable(obj):
                    if isinstance(obj, np.float32) or isinstance(obj, np.float64):
                        return float(obj)
                    return obj
                json.dump(comparison, f, indent=2, default=convert_to_serializable)
            
            print(f"\n📊 Validation vs Test comparison saved to: {comparison_path}")
            
            print("\n" + "-"*40)
            print("VALIDATION VS TEST COMPARISON (Aggregated Model)")
            print("-"*40)
            for target, metrics in comparison.items():
                if 'mae_gap' in metrics and metrics['mae_gap'] is not None:
                    gap = metrics['mae_gap']
                    print(f"  {target}: Test MAE = {metrics['test_mae']:.4f}, Val MAE = {metrics['val_mae']:.4f}, Gap = {gap:+.4f}")
                    if abs(gap) > 0.2 * metrics['val_mae']:
                        print(f"    ⚠️  WARNING: Large gap detected - possible overfitting!")
                elif 'f1_gap' in metrics and metrics['f1_gap'] is not None:
                    gap = metrics['f1_gap']
                    print(f"  {target}: Test F1 = {metrics['test_f1']:.4f}, Val F1 = {metrics['val_f1']:.4f}, Gap = {gap:+.4f}")
                    if abs(gap) > 0.15:
                        print(f"    ⚠️  WARNING: Large gap detected - possible overfitting!")
        
        print(f"\n{'='*60}")
        print(f"✅ EVALUATION COMPLETED for {machine_type}")
        print(f"{'='*60}")
    
    cross_comparison_path = os.path.join(base_save_path, 'cross_machine_comparison.json')
    cross_comparison = generate_cross_machine_comparison(all_machines_data, cross_comparison_path)
    
    summary_path = os.path.join(base_save_path, 'evaluation_summary.json')
    
    clean_summary = {
        'multi_step': {},
        'aggregated': {}
    }
    
    for machine_type, results in evaluation_summary['multi_step'].items():
        clean_summary['multi_step'][machine_type] = {
            'per_target_metrics': {}
        }
        for target, metrics in results.get('per_target_metrics', {}).items():
            if 'mae' in metrics:
                clean_summary['multi_step'][machine_type]['per_target_metrics'][target] = {
                    'mae': metrics['mae'],
                    'rmse': metrics.get('rmse')
                }
            else:
                clean_summary['multi_step'][machine_type]['per_target_metrics'][target] = {
                    'precision': metrics['precision'],
                    'recall': metrics['recall'],
                    'f1': metrics['f1'],
                    'auc': metrics['auc']
                }
    
    for machine_type, results in evaluation_summary['aggregated'].items():
        clean_summary['aggregated'][machine_type] = {
            'per_target_metrics': {}
        }
        for target, metrics in results.get('per_target_metrics', {}).items():
            if 'mae' in metrics:
                clean_summary['aggregated'][machine_type]['per_target_metrics'][target] = {
                    'mae': metrics['mae'],
                    'rmse': metrics.get('rmse')
                }
            else:
                clean_summary['aggregated'][machine_type]['per_target_metrics'][target] = {
                    'precision': metrics['precision'],
                    'recall': metrics['recall'],
                    'f1': metrics['f1'],
                    'auc': metrics['auc']
                }
    
    with open(summary_path, 'w') as f:
        def convert_to_serializable(obj):
            if isinstance(obj, np.float32) or isinstance(obj, np.float64):
                return float(obj)
            return obj
        json.dump(clean_summary, f, indent=2, default=convert_to_serializable)
    
    print(f"\n{'#'*60}")
    print("PHASE 5 EVALUATION COMPLETE")
    print(f"{'#'*60}")
    print(f"\n📁 Results saved to:")
    print(f"   - Cross-machine comparison: {cross_comparison_path}")
    print(f"   - Evaluation summary: {summary_path}")
    print(f"\n   Per-machine results in:")
    for machine_type in evaluation_summary['aggregated'].keys():
        print(f"     - {machine_type}/aggregated/test_evaluation_metrics.json")
        print(f"     - {machine_type}/multi_step/test_evaluation_metrics.json")