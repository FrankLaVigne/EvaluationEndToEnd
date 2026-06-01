"""Confirm benchmark/provider ids against GET /api/v1/evaluations/providers.

The collection spec ships with a PLACEHOLDER provider id, `custom_agent_judge`,
for the behavioral agent-trace benchmark. This module refuses to let it through
silently:

  * if a registered provider looks like an agent/judge contrib adapter, it
    writes the swap into .provider-map.json (which load-collection applies);
  * otherwise it tells you to either register the contrib adapter or drop the
    benchmark (the runbook covers the 4-benchmark story).

Run it as the first preflight step:  python3 -m harness.check_providers
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

from harness.results_provider import (
    PROVIDER_MAP_PATH,
    SPECS,
    LiveProvider,
    load_job_spec,
    log,
)

COLLECTION_PATH = SPECS / "collection-edd-release-suite.json"
PLACEHOLDER_IDS = {"custom_agent_judge"}

# substrings that suggest a registered provider is the contrib agent-judge adapter
JUDGE_HINTS = ("judge", "agent_eval", "agent-eval", "trace")


def provider_id_of(p: dict) -> str:
    """Provider records may carry their id at .id, .resource.id, or .name."""
    return p.get("id") or p.get("resource", {}).get("id") or p.get("name", "")


def check(base_url: str | None = None) -> int:
    collection = json.loads(COLLECTION_PATH.read_text())
    needed = {b["provider_id"] for b in collection["benchmarks"]}

    live = LiveProvider(load_job_spec(), base_url)
    if not live.health():
        log(f"EvalHub unreachable at {live.base_url} -- provider check deferred.")
        log("Offline fixtures do not need provider ids; the demo still completes.")
        return 0

    try:
        registered = {provider_id_of(p) for p in live.providers()}
    except (requests.RequestException, ValueError) as exc:
        log(f"GET {live.base_url}/api/v1/evaluations/providers failed: {exc}")
        log("Provider check deferred; offline fixtures remain available.")
        return 0

    registered.discard("")
    log(f"Registered providers in {live.base_url}:")
    for r in sorted(registered):
        log(f"  - {r}")
    log("")

    mapping: dict[str, str] = {}
    missing: list[str] = []
    log(f"{'spec provider_id':<28} {'status':<12} resolution")
    log("-" * 72)
    for pid in sorted(needed):
        if pid in registered:
            log(f"{pid:<28} {'OK':<12} registered as-is")
            continue
        if pid in PLACEHOLDER_IDS:
            # look for a contrib adapter that can take its place
            candidates = [r for r in registered if any(h in r.lower() for h in JUDGE_HINTS)]
            if candidates:
                mapping[pid] = candidates[0]
                log(f"{pid:<28} {'PLACEHOLDER':<12} swapping -> {candidates[0]}")
            else:
                missing.append(pid)
                log(f"{pid:<28} {'PLACEHOLDER':<12} NO contrib judge adapter registered")
        else:
            missing.append(pid)
            log(f"{pid:<28} {'MISSING':<12} not registered in this EvalHub")

    if mapping:
        PROVIDER_MAP_PATH.write_text(json.dumps(mapping, indent=2) + "\n")
        log(f"\nWrote {PROVIDER_MAP_PATH.name}; `load-collection` will apply the swap.")

    if missing:
        log("\nUNRESOLVED provider ids: " + ", ".join(missing))
        log("Options (per demo-runbook.md preflight):")
        log("  1. Register the contrib agent-judge adapter (eval-hub-sdk FrameworkAdapter),")
        log("     then re-run this check.")
        log("  2. Drop that benchmark from the collection and tell the 4-benchmark story.")
        log("  3. Run the gate in offline/replay mode (fixtures already include it).")
        return 1

    log("\nAll provider ids confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(check())
