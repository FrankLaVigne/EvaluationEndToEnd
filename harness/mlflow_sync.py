"""Land an EvalHub job record in local MLflow under experiment `edd-release-gate`.

In live/replay mode EvalHub writes its own MLflow records. In offline mode this
module recreates the same record from the ./specs fixtures, so the runbook's
compliance-query beat (filter by pipeline=release-gate, open the run, read the
verdict) works against the REAL local MLflow UI even with the wifi dead.

Usage:  python3 -m harness.mlflow_sync <record.json>
        ... | python3 -m harness.mlflow_sync -      (read record from stdin)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from harness.results_provider import ROOT, load_job_spec, log

EXPERIMENT = "edd-release-gate"


def _setup_mlflow():
    import mlflow
    import requests

    server = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    try:
        requests.get(f"{server.rstrip('/')}/health", timeout=2)
    except requests.RequestException:
        # same local SQLite fallback the agent uses; queryable later with
        #   mlflow ui --backend-store-uri sqlite:///mlruns.db
        server = f"sqlite:///{ROOT / 'mlruns.db'}"
    mlflow.set_tracking_uri(server)
    mlflow.set_experiment(EXPERIMENT)
    return mlflow, server


def sync(record: dict) -> str:
    """Write the job record as one parent MLflow run + one nested run per
    benchmark. Returns the parent run id."""
    mlflow, server = _setup_mlflow()
    job_spec = load_job_spec()

    results = record.get("results", {})
    verdict = results.get("test", {})
    resource = record.get("resource", {})

    tags = {t["key"]: t["value"] for t in job_spec.get("experiment", {}).get("tags", [])}
    tags.update({
        "evalhub.job_id": resource.get("id", "unknown"),
        "evalhub.owner": resource.get("owner", "unknown"),
        "evalhub.state": record.get("status", {}).get("state", "unknown"),
        "model.name": record.get("model", {}).get("name", "unknown"),
        "collection.id": record.get("collection", {}).get("id", "unknown"),
        "verdict": "PROMOTE" if verdict.get("pass") else "BLOCKED",
    })

    with mlflow.start_run(run_name=record.get("name", "edd-release-gate")) as parent:
        mlflow.set_tags(tags)
        mlflow.log_metric("weighted_score", verdict.get("score", 0.0))
        mlflow.log_metric("threshold", verdict.get("threshold", 0.0))
        mlflow.log_metric("gate_pass", 1.0 if verdict.get("pass") else 0.0)
        mlflow.log_dict(record, "evalhub-job-record.json")

        for bench in results.get("benchmarks", []):
            test = bench.get("test", {})
            with mlflow.start_run(run_name=bench["id"], nested=True):
                mlflow.set_tags({
                    **tags,
                    "benchmark.id": bench["id"],
                    "benchmark.provider_id": bench.get("provider_id", ""),
                    "benchmark.pass": str(test.get("pass", False)).lower(),
                    "evalhub.recorded_mlflow_run_id": bench.get("mlflow_run_id", ""),
                    "evalhub.logs_path": bench.get("logs_path", ""),
                })
                mlflow.log_metric("primary_score", test.get("primary_score", 0.0))
                mlflow.log_metric("threshold", test.get("threshold", 0.0))
                for metric, value in bench.get("metrics", {}).items():
                    if isinstance(value, bool):
                        value = 1.0 if value else 0.0
                    if isinstance(value, (int, float)):
                        mlflow.log_metric(metric, float(value))

        log(f"[mlflow: record synced to {server} | experiment {EXPERIMENT} | run {parent.info.run_id}]")
        return parent.info.run_id


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    source = sys.argv[1]
    text = sys.stdin.read() if source == "-" else Path(source).read_text()
    sync(json.loads(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
