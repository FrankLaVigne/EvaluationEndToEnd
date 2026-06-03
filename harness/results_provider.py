"""The one seam every demo component shares.

A results provider answers two questions, in the exact JSON shapes EvalHub
uses (see ./specs/results-*.json):

    submit()        -> job id
    fetch(job_id)   -> the full job record

Two implementations:

    LiveProvider     real HTTP against an EvalHub server (local mode or cluster)
    FixtureProvider  the recorded JSON in ./specs -- needs no network at all

Mode selection (GATE_MODE env var or --mode flag):

    auto     health-check EvalHub: replay/live if up, fixtures if not  [default]
    live     real submit, poll the new job to completion
    replay   real submit (best effort), poll a PREBAKED completed job id
             (created earlier with `make prebake`) -- returns in seconds
    offline  fixtures only; zero network calls

Every live call additionally degrades to fixtures on any error or timeout,
so the gate ALWAYS produces a verdict. The provenance string says which path
actually answered -- the presenter sees it, the audience doesn't need to.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"
PREBAKED_PATH = ROOT / ".prebaked-jobs.json"
PROVIDER_MAP_PATH = ROOT / ".provider-map.json"

DEFAULT_EVALHUB = "http://localhost:8080"
JOBS_PATH = "/api/v1/evaluations/jobs"
COLLECTIONS_PATH = "/api/v1/evaluations/collections"
PROVIDERS_PATH = "/api/v1/evaluations/providers"
HEALTH_PATHS = ("/api/v1/health", "/health")  # runbook says the former, repo docs the latter

TERMINAL_STATES = {"completed", "failed", "error", "cancelled"}


def log(msg: str) -> None:
    """Status lines go to stderr so stdout stays pure JSON for jq."""
    print(msg, file=sys.stderr)


def evalhub_url() -> str:
    return os.environ.get("EVALHUB", DEFAULT_EVALHUB).rstrip("/")


def auth_headers() -> dict:
    """Bearer token for an EvalHub behind an authenticated route (e.g. an
    OpenShift Route). Empty when EVALHUB_TOKEN is unset (local mode)."""
    token = os.environ.get("EVALHUB_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def load_job_spec(path: Path | None = None) -> dict:
    return json.loads((path or SPECS / "job-edd-release-gate.json").read_text())


def apply_maas_override(job_spec: dict) -> dict:
    """If a Red Hat MaaS endpoint is configured (.env / MAAS_*), point the job's
    model at it instead of the placeholder Databricks endpoint in the spec. The
    committed spec stays secret-free; the live target is supplied at runtime.

    EvalHub resolves the key from the `maas-api-key` secret_ref -- pass
    MAAS_API_KEY into the EvalHub container (see docker-compose.yaml). Offline
    and replay modes never read .model, so this is a no-op there."""
    from harness import maas
    cfg = maas.maas_config()
    if not cfg:
        return job_spec
    model = job_spec.setdefault("model", {})
    model["url"] = cfg["endpoint"]
    model["name"] = cfg["model"]
    model.setdefault("auth", {})["secret_ref"] = "maas-api-key"
    log(f"[model -> Red Hat MaaS: {cfg['model']} @ {cfg['endpoint']} key={maas.masked_key()}]")
    return job_spec


def candidate_of(job_spec: dict) -> str:
    for tag in job_spec.get("experiment", {}).get("tags", []):
        if tag.get("key") == "candidate":
            return tag["value"]
    return "unknown"


def fixture_path_for(candidate: str) -> Path:
    """rc1 -> the failing 'before' record; rc2 (hardened) -> the passing 'after' one."""
    name = "results-after-hardening.json" if "rc2" in candidate else "results-before-hardening.json"
    return SPECS / name


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class FixtureProvider:
    """Replays the recorded EvalHub job records in ./specs. No network."""

    def __init__(self, job_spec: dict):
        self.job_spec = job_spec
        self.name = "offline fixtures (./specs)"

    def submit(self) -> str:
        return self._record()["resource"]["id"]

    def fetch(self, job_id: str) -> dict:
        return self._record()

    def poll(self, job_id: str, timeout: float = 0, interval: float = 0) -> dict:
        return self._record()

    def _record(self) -> dict:
        return json.loads(fixture_path_for(candidate_of(self.job_spec)).read_text())


class LiveProvider:
    """Real HTTP against an EvalHub server."""

    def __init__(self, job_spec: dict, base_url: str | None = None):
        self.job_spec = apply_maas_override(job_spec)
        self.base_url = (base_url or evalhub_url()).rstrip("/")
        self.name = f"live EvalHub ({self.base_url})"

    def health(self, timeout: float = 2.0) -> bool:
        for path in HEALTH_PATHS:
            try:
                r = requests.get(f"{self.base_url}{path}", headers=auth_headers(), timeout=timeout)
                if r.ok:
                    return True
            except requests.RequestException:
                continue
        return False

    def providers(self) -> list[dict]:
        r = requests.get(f"{self.base_url}{PROVIDERS_PATH}", headers=auth_headers(), timeout=10)
        r.raise_for_status()
        body = r.json()
        # the list may be the body itself or nested under a key
        if isinstance(body, dict):
            for key in ("providers", "items", "resources"):
                if key in body:
                    return body[key]
        return body

    def put_collection(self, collection: dict) -> dict:
        cid = collection["name"]
        r = requests.put(f"{self.base_url}{COLLECTIONS_PATH}/{cid}", json=collection,
                         headers=auth_headers(), timeout=30)
        r.raise_for_status()
        return r.json() if r.text else {}

    def submit(self) -> str:
        r = requests.post(f"{self.base_url}{JOBS_PATH}", json=self.job_spec,
                          headers=auth_headers(), timeout=30)
        r.raise_for_status()
        return r.json()["resource"]["id"]

    def fetch(self, job_id: str) -> dict:
        r = requests.get(f"{self.base_url}{JOBS_PATH}/{job_id}", headers=auth_headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def poll(self, job_id: str, timeout: float = 360, interval: float = 5) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            record = self.fetch(job_id)
            state = record.get("status", {}).get("state", "")
            if state in TERMINAL_STATES:
                return record
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"job {job_id} still '{state}' after {timeout:.0f}s"
                )
            time.sleep(interval)


# --------------------------------------------------------------------------
# Prebaked job ids (created by `make prebake`, used by replay mode)
# --------------------------------------------------------------------------

def load_prebaked() -> dict:
    if PREBAKED_PATH.exists():
        return json.loads(PREBAKED_PATH.read_text())
    return {}


def save_prebaked(candidate: str, job_id: str) -> None:
    data = load_prebaked()
    data[candidate] = job_id
    PREBAKED_PATH.write_text(json.dumps(data, indent=2) + "\n")


# --------------------------------------------------------------------------
# The orchestrator: never raises, always returns a verdict record
# --------------------------------------------------------------------------

def run_gate(job_spec: dict, mode: str = "auto", timeout: float = 360) -> tuple[dict, str]:
    """Submit + poll under the requested mode, degrading to fixtures on any
    failure. Returns (job_record, provenance) -- provenance describes which
    path actually produced the record."""
    candidate = candidate_of(job_spec)
    fixtures = FixtureProvider(job_spec)
    mode = (mode or "auto").lower()

    if mode == "offline":
        log(f"[provider: {fixtures.name}] candidate={candidate}")
        return fixtures.fetch(""), "offline fixtures (requested)"

    live = LiveProvider(job_spec)

    if not live.health():
        log(f"[EvalHub unreachable at {live.base_url} -> {fixtures.name}] candidate={candidate}")
        return fixtures.fetch(""), "offline fixtures (EvalHub unreachable)"

    if mode == "auto":
        # EvalHub is up: prefer replay if we have a prebaked id, else live.
        mode = "replay" if candidate in load_prebaked() else "live"

    if mode == "replay":
        prebaked = load_prebaked().get(candidate)
        if prebaked:
            try:
                # the submission still happens live -- it is fast and it is real --
                # but the verdict comes from the prebaked completed job
                try:
                    submitted = live.submit()
                    log(f"[submitted job {submitted} live; verdict from prebaked {prebaked}]")
                except requests.RequestException:
                    log(f"[live submit failed; verdict from prebaked {prebaked}]")
                record = live.fetch(prebaked)
                log(f"[provider: {live.name}, replay] candidate={candidate}")
                return record, f"live EvalHub, prebaked job {prebaked}"
            except (requests.RequestException, KeyError, TimeoutError) as exc:
                log(f"[replay failed ({exc}) -> {fixtures.name}]")
                return fixtures.fetch(""), f"offline fixtures (replay failed: {exc})"
        log(f"[no prebaked job for {candidate}; falling through to live run]")
        mode = "live"

    # mode == "live"
    try:
        job_id = live.submit()
        log(f"[submitted job {job_id}; polling up to {timeout:.0f}s]")
        record = live.poll(job_id, timeout=timeout)
        log(f"[provider: {live.name}, live run] candidate={candidate}")
        return record, f"live EvalHub, job {job_id}"
    except (requests.RequestException, KeyError, TimeoutError) as exc:
        log(f"[live run failed ({exc}) -> {fixtures.name}]")
        return fixtures.fetch(""), f"offline fixtures (live run failed: {exc})"
