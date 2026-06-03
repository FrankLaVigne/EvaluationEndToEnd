# Notebooks — the EDD demo, one notebook per beat

These walk through the same demo as the top-level README, but interactively. Each cell runs the
**real** demo command (`make` targets, `./release-gate.sh`, the harness modules) — nothing is
faked. Everything runs **fully offline** against the recorded fixtures in `../specs`: no docker,
no tokens, no network.

Run them in order:

| Notebook | Demo |
|---|---|
| [`00-setup.ipynb`](00-setup.ipynb) | environment check + the four gate modes |
| [`01-agent-trace.ipynb`](01-agent-trace.ipynb) | **Demo 1** — the agent that *looks* fine but goes off-task |
| [`02-release-gate-blocked.ipynb`](02-release-gate-blocked.ipynb) | **Demo 2** — the gate blocks rc1 (exit 1) |
| [`03-harden-and-promote.ipynb`](03-harden-and-promote.ipynb) | **Demo 3+4** — harden, then the gate promotes rc2 (exit 0) |
| [`04-compliance-view.ipynb`](04-compliance-view.ipynb) | the MLflow compliance record |

## Running them

```bash
make setup                 # once: installs mlflow + requests (also brings in jupyterlab)
jupyter lab                 # then open notebooks/ and run 00 → 04 in order
```

Each notebook's first cell `cd`s the kernel to the repo root, so the demo commands resolve
exactly as they do from a terminal — you can open the notebooks from anywhere.

## Notes

- `03-harden-and-promote.ipynb` applies `hardening.patch` and **reverts it at the end**, so your
  working tree is left clean (back on rc1) for the next rehearsal.
- `04-compliance-view.ipynb` reads the MLflow runs that 02–03 create in `../mlruns.db`; run those
  first, or it will tell you to.
- Notebooks are committed **without** saved output. The ANSI banners (red BLOCKED / green PROMOTE)
  render in JupyterLab when you run the cells.
