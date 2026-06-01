# Run the EDD demo against OpenShift AI (RHOAI)

In this path **EvalHub runs in the cluster** — it's the "impartial judge running in our own
cluster" line from the runbook, made literal. The laptop keeps the agent, the gate, and the
local MLflow view; the cluster does the judging.

This is the most on-message setup for the talk ("Red Hat is the place to do EDD"), and the
most moving parts. Do the preflight days early, not the night before.

```
┌────────── laptop ──────────┐          ┌──────── OpenShift AI ────────┐
│ agent → MLflow trace       │          │  EvalHub (TrustyAI stack)    │
│ release-gate.sh ───────────┼──HTTPS──▶│   ├─ lm-eval jobs            │
│ local MLflow (compliance)  │          │   ├─ garak jobs              │
│ ./specs fixtures (fallback)│          │   └─ verdict record          │
└────────────────────────────┘          └───────────┬──────────────────┘
                                                     ▼
                                         Databricks serving endpoint
                                              (the model under test)
```

## Prerequisites

- **Red Hat OpenShift AI 3.x** with the evaluation hub component (ships with the TrustyAI
  stack from RHOAI 3.4 / Red Hat AI 3.4 onward). Check with your cluster admin or:
  `oc get datasciencecluster -o yaml | grep -A5 trustyai`
- `oc` CLI logged into the cluster (`oc login ...`)
- Cluster permissions to create secrets in the EvalHub namespace (or an admin who will)
- On the laptop: Python 3.11, jq, and this repo (`make setup`)

## Cluster-side setup (once, with your admin)

### 1. Enable the evaluation component

In the `DataScienceCluster` resource, the TrustyAI/eval-hub component must be **Managed**.
Evaluation jobs that download benchmark datasets or probe code (lm-eval, garak) also need
the online-access and code-execution permissions, which default to **deny**:

```bash
oc get datasciencecluster default-dsc -o yaml
# look for (exact field names vary by RHOAI version -- check your version's
# "Evaluating AI systems" doc):
#   trustyai:        managementState: Managed
#   permitOnline:         allow
#   permitCodeExecution:  allow
```

> Reference: Red Hat OpenShift AI → *Evaluating AI systems* documentation for your version.

### 2. Create the Databricks serving-endpoint secret

The job spec (`specs/job-edd-release-gate.json`) references `secret_ref:
databricks-serving-token`. That secret must exist in the namespace EvalHub runs in:

```bash
EVALHUB_NS=$(oc get pods -A -l app.kubernetes.io/part-of=trustyai -o jsonpath='{.items[0].metadata.namespace}')
oc create secret generic databricks-serving-token \
  -n "$EVALHUB_NS" \
  --from-literal=token=<your-databricks-pat>
```

### 3. Find the EvalHub route and confirm MLflow

```bash
oc get routes -n "$EVALHUB_NS"
# note where EvalHub's MLFLOW_TRACKING_URI points (ask the admin or check the deployment env):
oc get deploy -n "$EVALHUB_NS" -o yaml | grep -A1 MLFLOW_TRACKING_URI
```

## Laptop-side setup

```bash
git clone <this-repo> && cd EvaluationEndToEnd
make setup

# point the harness at the cluster
export EVALHUB=https://$(oc get route <evalhub-route-name> -n "$EVALHUB_NS" -o jsonpath='{.spec.host}')
export EVALHUB_TOKEN=$(oc whoami -t)        # sent as Authorization: Bearer <token>

python3 -m harness.evalhub_client health     # should print: EvalHub OK at https://...
```

Two notes on auth:

- `EVALHUB_TOKEN` is read by every harness call (`harness/results_provider.py`). `oc whoami -t`
  tokens expire — re-export it the day of the talk.
- If the route turns out to be unauthenticated inside your network, just skip `EVALHUB_TOKEN`.
- **Fallback that always works:** skip the route entirely and port-forward; then the harness
  default URL works unchanged, no token needed:
  ```bash
  oc port-forward -n "$EVALHUB_NS" svc/<evalhub-service> 8080:8080 &
  unset EVALHUB EVALHUB_TOKEN
  ```

## Preflight (days before — this is where surprises live)

```bash
make preflight
```

This does two things against the **cluster**:

1. `GET /api/v1/evaluations/providers` — confirms `lm_evaluation_harness` and `garak` are
   registered, and looks for a contrib agent/judge adapter to replace the
   **`custom_agent_judge` placeholder**. If your cluster has one registered, the swap is
   written to `.provider-map.json` automatically. If not, your options (per the runbook):
   - register the contrib adapter (eval-hub-sdk `FrameworkAdapter`) with your admin, or
   - drop that benchmark and present the 4-benchmark story (the verdict math still works).
2. `PUT /api/v1/evaluations/collections/edd-release-suite` — loads the suite, with the swap
   applied. It refuses to load while the placeholder is unresolved.

Then bake the two real runs (these run **in the cluster**, hitting Databricks — can take a while):

```bash
make prebake                                # rc1 → BLOCKED record
git checkout hardened && make prebake       # rc2 → PROMOTE record
git checkout -
```

## The 4-command demo (on stage)

```bash
docker compose up -d mlflow            # 1. local MLflow only (the cluster is the judge)
make agent-buggy                       # 2. the agent that "looks fine"
./release-gate.sh                      # 3. ✕ RELEASE BLOCKED, exit 1  (replays cluster job)
git checkout hardened && ./release-gate.sh    # 4. ✓ PROMOTE, exit 0
```

The gate polls the cluster's prebaked jobs over HTTPS, then **syncs the verdict record into
your local MLflow** (`harness/mlflow_sync.py`), so the compliance-query beat works on
http://localhost:5000 even though the judging happened in the cluster. If the cluster's own
MLflow is reachable from the venue, opening *that* UI is an even stronger payoff — same
record, owned by the platform, not the laptop.

## Conference-wifi reality check

The cluster path has a network dependency the laptop paths don't: the venue must reach your
cluster's route. The harness treats that exactly like any other failure:

| Failure | What happens |
|---|---|
| Route unreachable / token expired | Health check fails → gate uses `./specs` fixtures, same BLOCKED→PROMOTE story |
| Route reachable, job polling hangs | Per-call timeout → degrade to fixtures mid-flight |
| Provider id missing on the day | Runbook's 4-benchmark story; the dashboard fallback narrates the 5th |

Belt-and-suspenders for the talk: run the Mac path (`docs/run-on-mac-apple-silicon.md`) as the
default demo, and keep this cluster setup as the *"and this same gate is pointing at our
OpenShift AI cluster right now"* flourish — flip to it only if the venue network is good.
