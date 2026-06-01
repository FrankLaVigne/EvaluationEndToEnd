# Run the EDD demo on an NVIDIA DGX Spark

The Spark (GB10 Grace Blackwell, 128 GB unified memory, DGX OS) changes the demo in one big
way: **the model itself can run locally**, next to the judge. That removes the Databricks
serving endpoint — and therefore the wifi — from the *live* path entirely. A fully live,
fully disconnected end-to-end run becomes possible.

Two things to plan around:

1. **The Spark is arm64 (aarch64).** The default `EVALHUB_IMAGE` in `docker-compose.yaml`
   is an x86_64 build, and Linux has no Rosetta. You need an arm64 EvalHub image
   (build-from-source instructions below — it's a Go service, this is easy).
2. **The narrative changes.** The runbook's line is "Databricks is the engine; EvalHub is the
   judge." With local serving, the engine is the Spark. Decide with your co-presenter whether
   that's the story you want, or whether you keep the Databricks framing and use the Spark
   only as a bulletproof live-run box (replay mode works exactly as on the Mac).

## Prerequisites

- DGX Spark with DGX OS (Docker + NVIDIA Container Toolkit are preinstalled)
- Python 3.11+ (`python3 --version`; `sudo apt install python3.11` if needed)
- jq (`sudo apt install jq`)

## One-time setup

### 1. Clone and install

```bash
git clone <this-repo> && cd EvaluationEndToEnd
make setup
sudo apt install -y jq
```

### 2. Build an arm64 EvalHub image

```bash
git clone https://github.com/eval-hub/eval-hub /tmp/eval-hub
docker build -t eval-hub:local-arm64 /tmp/eval-hub      # Go build, native arm64
export EVALHUB_IMAGE=eval-hub:local-arm64               # picked up by docker-compose.yaml
```

Add `export EVALHUB_IMAGE=eval-hub:local-arm64` to your `~/.bashrc` so it survives reboots.

> MLflow's image (`ghcr.io/mlflow/mlflow`) is multi-arch and runs natively. If your tag
> isn't, replace the `mlflow` service with a host process:
> `mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:///mlflow-server.db`

### 3. (Optional, the big win) Serve the model locally

Llama 3.3 70B in NVFP4/FP8 fits in the Spark's 128 GB unified memory. Any
OpenAI-compatible server works; vLLM via NVIDIA's Spark playbooks is the documented path:

```bash
# see https://build.nvidia.com / DGX Spark playbooks for the current vLLM container tag
docker run -d --gpus all --name model-serving -p 8000:8000 \
  <nvcr.io vllm image for DGX Spark> \
  --model meta-llama/Llama-3.3-70B-Instruct --quantization fp8

curl -s localhost:8000/v1/models | jq      # confirm it's serving
```

Then point the job spec at it. **Don't edit the committed spec** — make a Spark-local copy
(same fields, different values; the shapes stay exactly what EvalHub expects):

```bash
jq '.model.url = "http://host.docker.internal:8000/v1"
    | .model.name = "llama-3.3-70b-instruct"
    | del(.model.auth)' \
  specs/job-edd-release-gate.json > specs/job-edd-release-gate.spark.json
```

And add the host-gateway mapping so the EvalHub container can reach the model server,
in `docker-compose.yaml` under the `evalhub` service:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

All harness commands accept the alternate spec:

```bash
./release-gate.sh --job-spec specs/job-edd-release-gate.spark.json
python3 -m harness.evalhub_client --job-spec specs/job-edd-release-gate.spark.json prebake
```

## Preflight (the night before)

```bash
docker compose up -d --wait
make preflight                    # provider ids + collection load

# if serving locally (no Databricks, no wifi needed):
JOB_SPEC=specs/job-edd-release-gate.spark.json
python3 -m harness.evalhub_client --job-spec $JOB_SPEC prebake
git checkout hardened
python3 -m harness.evalhub_client --job-spec $JOB_SPEC prebake
git checkout -

# if keeping the Databricks framing instead:
export DATABRICKS_TOKEN=<token>
make prebake && git checkout hardened && make prebake && git checkout -
```

## The 4-command demo

```bash
docker compose up -d --wait
make agent-buggy
./release-gate.sh                                  # ✕ RELEASE BLOCKED, exit 1
git checkout hardened && ./release-gate.sh         # ✓ PROMOTE, exit 0
```

(Add `--job-spec specs/job-edd-release-gate.spark.json` to the gate calls if you went the
local-serving route — or `export JOB_SPEC=specs/job-edd-release-gate.spark.json` once.)

MLflow UI: `http://<spark-hostname>:5000` — works from the Spark's own browser, or from your
laptop over the booth network/USB-C link if you present from the laptop with the Spark beside it.

## Spark-specific troubleshooting

| Problem | Action |
|---|---|
| `exec format error` starting a container | That image is amd64-only. Rebuild it for arm64 (see setup §2) or replace with a host process. |
| Model server OOM | Drop to a smaller quantization (NVFP4) or a smaller model — the demo story doesn't depend on the model's size, only on the verdict record. |
| EvalHub can't reach `host.docker.internal` | You forgot the `extra_hosts` entry, or use the Spark's LAN IP in `model.url` instead. |
| Anything at all during the talk | Same guarantee as everywhere else: `./release-gate.sh --offline` and `mock-mlflow-compliance-view.html` complete the demo with zero network and zero GPU. |
