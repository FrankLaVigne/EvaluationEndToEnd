"""EvalHub client CLI -- submit the release-gate job and poll for the verdict.

The request/response shapes come from ./specs (job-edd-release-gate.json in,
results-*.json out); nothing is invented here. Every command degrades to the
./specs fixtures when EvalHub is unreachable, so the demo always completes.

Commands
--------
  health            is EvalHub up?
  check-providers   confirm spec provider ids against GET /providers
  load-collection   PUT the collection (applies .provider-map.json swaps)
  submit            POST the job spec, print the new job id
  poll JOB_ID       GET the job until it reaches a terminal state
  gate              submit + poll with full degradation; prints the final
                    job record as JSON on stdout (for release-gate.sh / jq)
  prebake           run a real live job to completion and save its id for
                    replay mode (do this on good wifi, before the talk)

Environment
-----------
  EVALHUB    base URL of the EvalHub server   (default http://localhost:8080)
  GATE_MODE  auto | live | replay | offline   (default auto)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from harness import check_providers as provider_check
from harness.results_provider import (
    PROVIDER_MAP_PATH,
    SPECS,
    FixtureProvider,
    LiveProvider,
    candidate_of,
    load_job_spec,
    log,
    run_gate,
    save_prebaked,
)

COLLECTION_PATH = SPECS / "collection-edd-release-suite.json"


def cmd_health(args) -> int:
    live = LiveProvider(load_job_spec(args.job_spec))
    if live.health():
        log(f"EvalHub OK at {live.base_url}")
        return 0
    log(f"EvalHub UNREACHABLE at {live.base_url} (offline fixtures will be used)")
    return 1


def cmd_check_providers(args) -> int:
    return provider_check.check()


def cmd_load_collection(args) -> int:
    collection = json.loads(COLLECTION_PATH.read_text())

    # apply provider-id swaps discovered by check-providers; never ship the
    # custom_agent_judge placeholder silently
    if PROVIDER_MAP_PATH.exists():
        mapping = json.loads(PROVIDER_MAP_PATH.read_text())
        for bench in collection["benchmarks"]:
            if bench["provider_id"] in mapping:
                log(f"[provider swap] {bench['id']}: {bench['provider_id']} -> {mapping[bench['provider_id']]}")
                bench["provider_id"] = mapping[bench["provider_id"]]
    else:
        placeholders = [b["id"] for b in collection["benchmarks"]
                        if b["provider_id"] in provider_check.PLACEHOLDER_IDS]
        if placeholders:
            log(f"WARNING: placeholder provider id still present for: {', '.join(placeholders)}")
            log("Run `python3 -m harness.check_providers` first, or register the contrib adapter.")
            if not args.allow_placeholder:
                log("Refusing to load (use --allow-placeholder to override).")
                return 1

    live = LiveProvider(load_job_spec(args.job_spec))
    if not live.health():
        log(f"EvalHub unreachable at {live.base_url}; collection load skipped (offline mode).")
        return 0
    try:
        live.put_collection(collection)
        log(f"Collection '{collection['name']}' loaded into {live.base_url}.")
        return 0
    except requests.RequestException as exc:
        log(f"Collection load failed: {exc}")
        return 1


def cmd_submit(args) -> int:
    job_spec = load_job_spec(args.job_spec)
    live = LiveProvider(job_spec)
    if live.health():
        try:
            job_id = live.submit()
            log(f"[submitted to {live.base_url}]")
            print(job_id)
            return 0
        except requests.RequestException as exc:
            log(f"[live submit failed ({exc}) -> fixtures]")
    else:
        log(f"[EvalHub unreachable at {live.base_url} -> fixtures]")
    print(FixtureProvider(job_spec).submit())
    return 0


def cmd_poll(args) -> int:
    job_spec = load_job_spec(args.job_spec)
    live = LiveProvider(job_spec)
    if live.health():
        try:
            record = live.poll(args.job_id, timeout=args.timeout)
            print(json.dumps(record, indent=2))
            return 0
        except (requests.RequestException, TimeoutError) as exc:
            log(f"[poll failed ({exc}) -> fixtures]")
    else:
        log(f"[EvalHub unreachable -> fixtures]")
    print(json.dumps(FixtureProvider(job_spec).fetch(args.job_id), indent=2))
    return 0


def cmd_gate(args) -> int:
    job_spec = load_job_spec(args.job_spec)
    record, provenance = run_gate(job_spec, mode=args.mode, timeout=args.timeout)
    log(f"[verdict source: {provenance}]")
    print(json.dumps(record, indent=2))
    return 0


def cmd_prebake(args) -> int:
    job_spec = load_job_spec(args.job_spec)
    candidate = candidate_of(job_spec)
    live = LiveProvider(job_spec)
    if not live.health():
        log(f"EvalHub unreachable at {live.base_url}; cannot prebake. "
            "Do this on good wifi before the talk.")
        return 1
    log(f"Submitting live job for {candidate} (this runs the FULL suite -- "
        "garak + lm-eval can take a while)...")
    job_id = live.submit()
    log(f"Job {job_id} submitted; polling up to {args.timeout:.0f}s...")
    record = live.poll(job_id, timeout=args.timeout)
    state = record.get("status", {}).get("state")
    if state != "completed":
        log(f"Job finished in state '{state}'; not saving as prebaked.")
        return 1
    save_prebaked(candidate, job_id)
    verdict = record.get("results", {}).get("test", {})
    log(f"Prebaked {candidate} -> job {job_id} "
        f"(score {verdict.get('score')}, pass {verdict.get('pass')}). "
        "Replay mode will use it.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="evalhub_client",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--job-spec", type=Path, default=None,
                        help="path to the job spec JSON (default specs/job-edd-release-gate.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")
    sub.add_parser("check-providers")

    p = sub.add_parser("load-collection")
    p.add_argument("--allow-placeholder", action="store_true",
                   help="load the collection even if placeholder provider ids remain")

    sub.add_parser("submit")

    p = sub.add_parser("poll")
    p.add_argument("job_id")
    p.add_argument("--timeout", type=float, default=360)

    p = sub.add_parser("gate")
    p.add_argument("--mode", default=None, choices=["auto", "live", "replay", "offline"],
                   help="override GATE_MODE (default auto)")
    p.add_argument("--timeout", type=float, default=360)

    p = sub.add_parser("prebake")
    p.add_argument("--timeout", type=float, default=3600)

    args = parser.parse_args()
    if getattr(args, "mode", "unset") is None:
        import os
        args.mode = os.environ.get("GATE_MODE", "auto")

    handlers = {
        "health": cmd_health,
        "check-providers": cmd_check_providers,
        "load-collection": cmd_load_collection,
        "submit": cmd_submit,
        "poll": cmd_poll,
        "gate": cmd_gate,
        "prebake": cmd_prebake,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
