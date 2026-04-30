import os
from dotenv import load_dotenv
from tensorflow import keras
import numpy as np

load_dotenv()
CNN_saved_path = os.getenv('CNN_MODEL') # overall folder

def predict(mach_type:str, preproc_params: list):
    try:
        params_array = np.array(preproc_params)

        if params_array.ndim == 1:
            if params_array.shape[0] == 300:  # Flattened 30x10
                params_array = params_array.reshape(1, 30, 10)
            else:
                raise ValueError(f"Expected 300 features (30x10), but got {params_array.shape[0]} features")
        elif params_array.ndim == 2 and params_array.shape == (30, 10):
            params_array = params_array.reshape(1, 30, 10)

        mach_type_models = os.path.join(CNN_saved_path, mach_type)
        best_model = 'best_model.h5'

        agg_model_path = os.path.join(mach_type_models, 'aggregated', best_model)
        multi_step_model_path = os.path.join(mach_type_models, 'multi_step', best_model)
        
        agg_model = keras.models.load_model(agg_model_path, compile=False)
        multi_step_model = keras.models.load_model(multi_step_model_path, compile=False)

        agg_pred = agg_model.predict(params_array, verbose=0)
        multi_pred = multi_step_model.predict(params_array, verbose=0)

        results = {
            "status": "success", 
            "multi-step": agg_pred.tolist(),
            "aggregated": multi_pred.tolist()
        }

        return results
    
    except Exception as e:
        return {
                    "status": "error",
                    "message": f"Got issue..: {str(e)}"
        }