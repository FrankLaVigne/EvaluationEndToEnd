# EDD Demo Runbook — Data + AI Summit 2026

**Session:** Why AI Evaluation Breaks at Scale, and How to Fix It End to End
**Presenters:** Carlos Condado · Frank La Vigne (Red Hat AI)
**Slot:** 25 min. Plan to ~22 min of content, leave room for Q&A.
**Two messages to land:** (1) Evaluation-Driven Development matters — here's why. (2) Red Hat is the best place to do it.

The spine: **one** EvalHub job spans behavioral + safety + adversarial and rolls up to **one** verdict in **one** MLflow record. That single artifact is the whole argument. Every demo beat is a view into that one run, never a separate tool.

---

## Preflight (do this before you walk on)

- [ ] EvalHub server reachable. `curl -s $EVALHUB/api/v1/health` returns 200.
- [ ] `export EVALHUB=https://<your-evalhub-host>` set in the demo shell.
- [ ] Collection loaded: `PUT /api/v1/evaluations/collections/edd-release-suite` with `collection-edd-release-suite.json`.
- [ ] **Confirm every `id`/`provider_id` against `GET /api/v1/evaluations/providers` in your cluster.** The `custom_agent_judge` provider id is a placeholder — swap it for your registered contrib adapter, or drop that benchmark and run the agent-trace view from the mock dashboard.
- [ ] Databricks serving endpoint live; `databricks-serving-token` secret created.
- [ ] MLflow experiment `edd-release-gate` exists and is open in a browser tab.
- [ ] `mock-mlflow-compliance-view.html` open in a second tab, set to the **BEFORE** state. This is your fallback for any live step and your compliance-officer view.
- [ ] Terminal font scaled up. `jq` installed for pretty output.
- [ ] Two prebaked job ids handy (a fresh fail run and a hardened pass run) in case live submission is slow.

**Kill switch:** if you are short on time, drop the Layer 3 bonus and the second drill-down. That buys ~4 min (one demo + one slide), exactly the buffer you and Carlos sized on the 5/29 call.

---

## Timeline

### 0:00–2:00 — Cold open: the mirror shows green (slide 7)
Tell the eligibility-date story straight off the "A Familiar Scenario" slide: tests pass, pilot is smooth, stakeholders approve, and three weeks in a user gets the wrong answer. No error. No alert. CI still green.
> "The mirror shows green. Nobody tested whether it was *right*. That gap is not a missing tool — it's a missing discipline."
**Lands:** why EDD. No live action — pure setup.

### 2:00–4:30 — Frame the three layers as one pipeline (slides 8, 11, 12, 16)
Three things get evaluated by three teams with no shared record (slide 8). EDD is TDD for models: define the eval before you ship; the eval suite gates the release (slide 11). These are not three programs — one pipeline, one record (slide 12). Databricks is the engine; EvalHub is the impartial judge; MLflow is the queryable audit trail (slide 16).
**Lands:** both messages. Set up the "impartial judge outside the system" line — you'll pay it off live at the end.

### 4:30–9:00 — DEMO 1 (lead): Behavioral — did the agent do the right things? (slide 14)
This is the flipped lead you and Carlos agreed on; behavioral is the most relatable failure.
- Show the agent run that **looks** fine (order confirmed).
- Show the trace evaluated step by step: retrieve docs ✓, call pricing API ✓, **apply discount → off task**, **confirm order → skipped**. Verdict: behavioral failure at step 3.
- Point out the output was plausible; only the trace caught it.

**Live command (if showing the trace benchmark in isolation):**
```bash
curl -s -X POST "$EVALHUB/api/v1/evaluations/jobs" \
  -H "Content-Type: application/json" \
  -d @specs/job-edd-release-gate.json | jq '.resource.id, .status.state'
```
**Fallback:** flip to the mock dashboard (BEFORE) and read `agent_trace_judge` → step_accuracy 0.72, off-task 1, skipped 1, **FAIL**. Same story, zero network risk.
**Lands:** why EDD (output-only evaluation is a trap).

### 9:00–15:00 — DEMO 2: One job → one verdict → one audit trail
The hero beat. Show the single job spec on screen and narrate the weights: one spec carries behavioral (0.30), truthfulness (0.20), quality/bias (0.15), OWASP adversarial (0.25), capability (0.10).

```bash
# Submit the gate (or reuse the prebaked id if the room wifi is shaky)
JOB=$(curl -s -X POST "$EVALHUB/api/v1/evaluations/jobs" \
  -H "Content-Type: application/json" \
  -d @specs/job-edd-release-gate.json | jq -r '.resource.id')

# Poll for the verdict
curl -s "$EVALHUB/api/v1/evaluations/jobs/$JOB" \
  | jq '{state: .status.state, verdict: .results.test, layers: [.results.benchmarks[] | {id, score: .test.primary_score, pass: .test.pass}]}'
```
Expected verdict: **score 0.66, threshold 0.75, pass false → release BLOCKED.** Two findings: stereotype bias in review range, and an OWASP system-prompt-leak — the critical one.

Then the gate moment: this is `exit 1` in your release pipeline, the same way a red unit test blocks a merge.
- Harden (toughen the system prompt / add the guardrail), re-run the **same** spec.
- Verdict flips: **score 0.88, pass true → promote.**

**Fallback:** the mock dashboard toggle BEFORE → AFTER does this exact red→green flip on a click.
**Lands:** EDD as a methodology, and "the eval suite gates every release."

### 15:00–18:00 — The compliance query (slide 16 payoff)
Switch personas: now you're not the ML engineer, you're compliance. Open MLflow, filter by `pipeline=release-gate` and `candidate=...`, open the run. Same numbers, immutable, timestamped, with the model that was tested and the suite that judged it.
> "Engineering and compliance are reading the same record. Databricks ran the workload; the verdict came from a judge outside it."
**Fallback:** the mock dashboard *is* the compliance view — it shows run id, MLflow run ids per benchmark, owner, timestamps, and artifact paths.
**Lands:** Red Hat differentiation (impartial judge + one shared audit trail).

### 18:00–21:00 — BONUS: Adversarial robustness (slide 15) — only if time
Zoom into `owasp_llm_top10`: prompt injection blocked, jailbreak blocked, **system prompt leak exposed**, data exfiltration blocked. One critical finding to fix — and it was already part of the one run, not a separate red-team project bolted on later.
**Lands:** reinforces "one pipeline." Drop this first if you're tight.

### 21:00–22:00 — Close (slides 16 → Questions)
Restate the two messages in one breath: EDD is the discipline; Red Hat — open source, runs in your cluster, sovereign and disconnected-capable, impartial by design — is where you do it. Find us at the Databricks booth.

---

## The two takeaways, mapped to beats
| Beat | EDD matters | Red Hat is the place |
|------|:-----------:|:--------------------:|
| Cold open (mirror) | ● | |
| Three-layers framing | ● | ● |
| Demo 1 behavioral | ● | |
| Demo 2 one job → gate | ● | ● |
| Compliance query | | ● |
| Bonus adversarial | ● | |
| Close | ● | ● |

## If something breaks
- **Wifi dies:** everything has a mock-dashboard fallback. Narrate from it; the story is identical.
- **Live run is slow:** submit at the top of Demo 2, keep talking through the framing, come back to poll. Or use the prebaked job id.
- **A provider id is wrong:** you confirmed against `GET /providers` in preflight — but if it still errors, drop that one benchmark and lean on the dashboard. The verdict story holds with four benchmarks instead of five.
- **Never debug live for more than ~20 seconds.** Cut to the dashboard and move on.
