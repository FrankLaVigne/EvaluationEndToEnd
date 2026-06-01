# Run the EDD demo on a Mac (Apple Silicon)

This is the **primary stage path**: everything runs on the laptop, the wifi never matters.

## Prerequisites

| Tool | Install | Notes |
|---|---|---|
| Docker Desktop ≥ 4.25 | https://docker.com/products/docker-desktop | Podman Desktop or Colima also work |
| Python 3.11+ | `brew install python@3.11` | |
| jq | `brew install jq` | the gate parses verdicts with it |
| git | ships with Xcode CLT | |

## Two Apple Silicon gotchas (handle these first)

### 1. Port 5000 is taken by AirPlay

macOS runs AirPlay Receiver on port 5000, which collides with MLflow. Pick one:

```bash
# Option A (recommended): turn AirPlay Receiver off
#   System Settings → General → AirDrop & Handoff → AirPlay Receiver → Off

# Option B: move MLflow to 5001 — set BOTH of these in the demo shell
export MLFLOW_PORT=5001
export MLFLOW_TRACKING_URI=http://localhost:5001
```

### 2. The EvalHub image is amd64; your Mac is arm64

Docker Desktop runs amd64 images through Rosetta. Enable it once:

> Docker Desktop → **Settings → General** → check
> **"Use Rosetta for x86_64/amd64 emulation on Apple Silicon"** → Apply & Restart

Then tell compose to accept the non-native image:

```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64
```

The MLflow image (`ghcr.io/mlflow/mlflow`) publishes multi-arch builds, so it runs natively
either way. If any container refuses to start because of architecture, see
"Plan B: no containers at all" below.

## One-time setup (at home, on good wifi)

```bash
git clone <this-repo> && cd EvaluationEndToEnd
make setup                          # installs mlflow + requests
docker login registry.redhat.io    # for the default EVALHUB_IMAGE
docker compose pull                 # pre-pull every image NOW, not at the venue
```

## Preflight (the night before — mirrors demo-runbook.md)

```bash
docker compose up -d --wait
make preflight        # confirms provider ids against GET /providers,
                      #   swaps the custom_agent_judge placeholder, loads the collection
export DATABRICKS_TOKEN=<your-serving-endpoint-token>

make prebake                                   # real rc1 run → saves the job id
git checkout hardened && make prebake          # real rc2 run → saves the job id
git checkout -                                 # back to rc1
```

`make prebake` runs the FULL suite (garak + lm-eval) — expect tens of minutes per run.
The two saved job ids are what makes the on-stage gate return in seconds (replay mode).

## The 4-command demo (on stage)

```bash
docker compose up -d --wait      # 1. judge + audit trail
make agent-buggy                 # 2. the agent that "looks fine"
./release-gate.sh                # 3. ✕ RELEASE BLOCKED, exit 1
git checkout hardened && ./release-gate.sh     # 4. ✓ PROMOTE, exit 0
```

Open http://localhost:5000 (or :5001) → experiment **edd-release-gate** for the
compliance-query beat.

## If anything breaks on stage

| Problem | Action |
|---|---|
| Docker won't start / images won't run | Skip command 1. Commands 2–4 are unchanged; verdicts come from `./specs`, traces go to `sqlite:///mlruns.db` |
| Gate hangs | `Ctrl-C`, then `./release-gate.sh --offline` |
| MLflow UI unreachable | `mlflow ui --backend-store-uri sqlite:///mlruns.db --port 5050`, or open `mock-mlflow-compliance-view.html` |
| Anything else > 20 seconds | `mock-mlflow-compliance-view.html` is the demo. Narrate from it. |

## Plan B: no containers at all

If Docker Desktop is unusable (corporate policy, broken install, Rosetta issues), the demo
still works with **zero containers**:

```bash
# MLflow as a plain process (native arm64, installed by `make setup`)
mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri sqlite:///mlflow-server.db &

make agent-buggy                    # trace lands in the local MLflow above
./release-gate.sh --offline         # BLOCKED from fixtures, exit 1
git checkout hardened && ./release-gate.sh --offline    # PROMOTE, exit 0
```

The only thing you lose is a live EvalHub — and replay/offline mode tells the identical story.
