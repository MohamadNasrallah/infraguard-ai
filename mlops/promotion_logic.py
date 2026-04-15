"""
Model promotion logic for InfraGuard AI.
Reads the latest model version from MLflow registry and promotes it
to Production if it meets the defined performance thresholds.
"""
import os
import mlflow
from mlflow.tracking import MlflowClient

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = os.getenv("MLFLOW_MODEL_NAME", "infraguard-iep1")
MAP_THRESHOLD = float(os.getenv("MAP_THRESHOLD", "0.50"))
F1_THRESHOLD = float(os.getenv("F1_THRESHOLD", "0.60"))

def promote_if_ready() -> dict:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    versions = client.get_latest_versions(MODEL_NAME, stages=["Staging"])
    if not versions:
        return {"promoted": False, "reason": "No model in Staging"}

    version = versions[0]
    run = client.get_run(version.run_id)
    metrics = run.data.metrics

    map_score = metrics.get("map50", 0.0)
    f1_score = metrics.get("f1", 0.0)

    if map_score >= MAP_THRESHOLD and f1_score >= F1_THRESHOLD:
        client.transition_model_version_stage(
            name=MODEL_NAME,
            version=version.version,
            stage="Production",
            archive_existing_versions=True,
        )
        return {
            "promoted": True,
            "version": version.version,
            "map50": map_score,
            "f1": f1_score,
        }
    else:
        return {
            "promoted": False,
            "reason": f"Metrics below threshold: map50={map_score:.3f} (need {MAP_THRESHOLD}), f1={f1_score:.3f} (need {F1_THRESHOLD})",
        }

if __name__ == "__main__":
    result = promote_if_ready()
    print(result)
