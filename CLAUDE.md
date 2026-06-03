# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **runnable demo harness** for a conference session (Data + AI Summit 2026) on AI evaluation,
not production software. The spine of the demo: one EvalHub job spans behavioral + safety +
adversarial evaluation, rolls up to **one verdict**, and lands as **one MLflow record** that
gates a release (exit 0 = promote, exit 1 = blocked).

Two design constraints shape almost every file and should shape your changes too:

1. **Graceful degradation is the whole point.** Every step must complete even with no network
   (dead conference wifi). Every live call degrades to the recorded fixtures in `./specs` on any
   error or timeout. Never introduce a code path that hard-fails when EvalHub, MLflow, or
   Databricks is unreachable — degrade to fixtures and log the provenance instead.
2. **Deterministic, no live LLM.** `agent/credit_agent.py` is a canned 4-step agent so it can
   never break on stage. Keep new demo logic deterministic.

## Common commands

Everything is wrapped in the Makefile (`make help` shows the menu). Targets call Python modules
and `release-gate.sh`.

```bash
make setup          # install deps (uv if available, else pip install -e .); Python >=3.11
make up / make down # start/stop EvalHub (local mode) + MLflow via docker compose
make agent          # run the agent: correct, all 4 steps
make agent-buggy    # run with the planted bug (Demo 1): off-task at step 3, step 4 skipped
make probe          # OWASP probe: try to make the agent leak its system prompt
make gate           # run the release gate (auto mode)
make gate-offline   # run the gate from ./specs fixtures only, zero network
make prebake        # run a REAL live EvalHub job, save its id for replay mode (good wifi only)
make preflight      # check-providers + load-collection (confirms provider ids)
make harden / unharden   # apply / revert hardening.patch (rc1 -> rc2)
make clean          # remove local mlflow store + .prebaked-jobs.json + .provider-map.json
```

Run the gate directly with flags: `./release-gate.sh --offline | --mode {auto,live,replay} | --timeout N`.
The CLI behind it: `python3 -m harness.evalhub_client {health,check-providers,load-collection,submit,poll,gate,prebake}`.

There is **no test suite**. Verify changes by running the relevant `make` target; `make gate-offline`
exercises the full parse/verdict/MLflow path with no dependencies.

`jq` is required for `release-gate.sh`.

## Architecture

The pieces communicate through one seam and one set of JSON shapes:

- **`harness/results_provider.py`** — the seam everything shares. Defines `FixtureProvider`
  (reads `./specs`, no network) and `LiveProvider` (real HTTP), both with identical output
  shapes, plus `run_gate()`, the orchestrator that selects a provider by mode and **never
  raises** — it always returns `(job_record, provenance)`.
- **`harness/evalhub_client.py`** — CLI wrapping the provider. Each subcommand independently
  degrades to fixtures on failure.
- **`harness/check_providers.py`** — confirms collection `provider_id`s against the live
  `/providers` endpoint. `custom_agent_judge` is a deliberate **placeholder**; the harness
  refuses to ship it silently and writes resolved swaps to `.provider-map.json`.
- **`harness/mlflow_sync.py`** — recreates the EvalHub job record in local MLflow from fixtures
  (so the compliance-view beat works offline). Best-effort; never blocks the verdict.
- **`harness/maas.py`** — optional **online** path: an OpenAI-compatible client for a live Red Hat
  AI MaaS model (config from a gitignored `.env` via `MAAS_*`; uses `requests`, no new deps). The
  key is never printed (`masked_key()` shows last 4). `apply_maas_override()` in
  `results_provider.py` rewrites the job's `.model` to MaaS at submit time when configured; the
  agent's `--live` probe routes through `maas.chat()`. Both degrade to the offline/canned path on
  any failure — keep that invariant.
- **`agent/credit_agent.py`** — the canned agent + MLflow trace logger + the OWASP probe path.
- **`app.py` + `harness/console.py`** — the optional **web console** (Streamlit). `console.py`
  holds the Streamlit-free logic (probe + gate) so it stays importable/testable; `app.py` is the
  thin UI. No new logic — it reuses the agent and `run_gate`; live/cached maps to the existing
  modes and degrades to fixtures. Test the UI with `streamlit.testing.v1.AppTest`, not a browser.
  Installed via the `[ui]` extra (`make setup-ui`); launched with `make ui`.
- **`release-gate.sh`** — calls the `gate` CLI, parses the verdict, prints the banner, exits 0/1
  (or 2 on harness error). This is the CI-gate artifact the demo is about.

### `./specs` is the source of truth for JSON shapes

The request/response shapes are NOT invented in code — they mirror real EvalHub shapes recorded
in `specs/`. **Do not invent or rename fields**; match what the fixtures contain.

- `job-edd-release-gate.json` — the job POST body.
- `collection-edd-release-suite.json` — the weighted benchmark suite.
- `results-before-hardening.json` / `results-after-hardening.json` — the rc1 (BLOCKED) and rc2
  (PROMOTE) recorded verdicts.

### The rc1 → rc2 mechanism (how the verdict flips)

The `candidate` tag inside `job-edd-release-gate.json` (`...rc1` vs `...rc2`) is the switch.
`candidate_of()` reads it; `fixture_path_for()` maps `rc2` → the passing "after" fixture,
anything else → the failing "before" fixture. So in offline/replay mode the candidate tag
selects which recorded verdict you get; in a live run the hardened prompt + guardrail are what
actually flip it. **The same story holds either way — preserve this invariant.**

The hardening change exists in two forms that must stay in sync: the `hardened` git branch and
`hardening.patch` (applied via `make harden`). It adds `agent/guardrail.py` (an output filter),
a prompt-confidentiality block to `system_prompt.md`, and bumps the candidate tag rc1→rc2.
`credit_agent.py` imports the guardrail via try/except so rc1 (no guardrail file) runs unfiltered.

### Conventions

- **stdout vs stderr:** the `gate`/`poll` commands print pure JSON to stdout (so `jq` can parse
  it); all status/log lines go to stderr via `log()`. Keep stdout clean when adding output.
- **Gate modes** (`GATE_MODE` env or `--mode`): `auto` (default; live if EvalHub up + prebaked
  id exists → replay, else live; fixtures if down), `live`, `replay`, `offline`.
- Generated/machine-specific files are gitignored: `mlruns*`, `.prebaked-jobs.json`,
  `.provider-map.json`.

## Out of scope

Kubernetes/Kueue, GPU scheduling, production auth. `demo-runbook.md` is the minute-by-minute
presenter script; `docs/` holds platform-specific run guides (Mac, DGX Spark, OpenShift AI).
