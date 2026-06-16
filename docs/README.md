# EDD demo — static site (GitHub Pages)

Two zero-backend pages that tell the same story as the live harness —
**one job · one verdict · one record** — but run entirely in the browser so
they can be hosted on GitHub Pages.

- **`index.html`** — the polished **Release Gate Audit Record**: a compliance
  view with a Before/After-hardening toggle that flips the verdict red→green.
  Self-contained, offline, presentation-ready.
- **`console.html`** — the interactive **EDD Eval Console** (a client-side port
  of [`app.py`](../app.py)):
  - **Release gate** replays the real recorded EvalHub job records in
    [`specs/`](specs/) (`results-before/after-hardening.json`), selected by the
    rc1/rc2 candidate toggle — identical to `run_gate("offline")`.
  - **OWASP probe** ports the agent's canned leak path + the rc2 output guardrail
    (`agent/credit_agent.py`, `agent/guardrail.py`).

The two pages link to each other.

Two parts of the full console can't exist in a static page and are intentionally
absent: the **live Red Hat MaaS** path (needs a server + secret key) and the
**make harden/unharden** buttons (no shell) — the rc1/rc2 toggle stands in for
the candidate-tag switch those flip.

## Run locally

```bash
make pages          # serve docs/ at http://localhost:8000
```

(Open over HTTP, not `file://` — browsers block `fetch()` of local files.)

## Publish on GitHub Pages

Settings → Pages → **Deploy from a branch** → branch `main`, folder `/docs`.
No Actions workflow needed.

## Keeping fixtures in sync

`docs/specs/` is a copy of the repo's `./specs` (GitHub Pages only serves the
published folder). After changing a fixture or the system prompt, run from an
**unhardened (rc1)** working tree:

```bash
make pages-sync     # refresh docs/specs, then commit + push
```
