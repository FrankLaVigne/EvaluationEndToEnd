"""Red Hat AI MaaS (Models-as-a-Service) live backend -- optional.

MaaS endpoints are OpenAI-compatible (vLLM/KServe serving /v1/chat/completions)
and gated by an API key, typically issued and rate-limited by an API-management
layer (3scale). From this harness's point of view that is just "a base URL + a
bearer key", so it slots into the same live/fixture seam everything else uses.

Configuration comes from the environment, optionally seeded from a gitignored
`.env` at the repo root. NOTHING secret is committed:

    MAAS_ENDPOINT     OpenAI-compatible base URL, e.g.
                      https://my-model.apps.<cluster>/v1   (include the /v1)
    MAAS_MODEL        served model name, e.g. llama-3-3-70b-instruct
    MAAS_API_KEY      the API key (3scale app key or serving token)
    MAAS_AUTH_HEADER  optional; header name for the key. Default "Authorization"
                      with a "Bearer " prefix. Set to e.g. "api-key" if your
                      3scale plan expects the raw key in a custom header.

When unconfigured or unreachable, callers fall back to the deterministic agent
or the ./specs fixtures -- exactly like every other live path here. A live
endpoint is therefore pure upside: it can never break the demo.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = ROOT / ".env"

_dotenv_loaded = False


def load_dotenv(path: Path | None = None) -> None:
    """Seed os.environ from a simple KEY=VALUE .env file, without overriding
    variables already set in the real environment. Idempotent."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    p = path or DOTENV_PATH
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def maas_config(model: str | None = None) -> dict | None:
    """Return the MaaS config dict for a model, or None if not configured.
    Requires an API key plus EITHER:
      * MAAS_BASE + a model name (endpoint = {base}/{model}/v1), so one base
        serves many models on the same key -- pass `model` to switch; or
      * MAAS_ENDPOINT (a single fully-qualified OpenAI-compatible URL)."""
    load_dotenv()
    api_key = os.environ.get("MAAS_API_KEY", "").strip()
    if not api_key:
        return None
    model = (model or os.environ.get("MAAS_MODEL", "")).strip()
    base = os.environ.get("MAAS_BASE", "").strip().rstrip("/")
    explicit = os.environ.get("MAAS_ENDPOINT", "").strip().rstrip("/")
    if base and model:
        endpoint = f"{base}/{model}/v1"
    elif explicit:
        endpoint = explicit
        model = model or "default"
    else:
        return None
    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model": model or "default",
        "auth_header": os.environ.get("MAAS_AUTH_HEADER", "Authorization").strip(),
    }


def available_models() -> list[str]:
    """Models offered in the UI/CLI picker: MAAS_MODELS (comma-separated) if set,
    else the single MAAS_MODEL."""
    load_dotenv()
    raw = os.environ.get("MAAS_MODELS", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    one = os.environ.get("MAAS_MODEL", "").strip()
    return [one] if one else []


def is_configured() -> bool:
    return maas_config() is not None


def masked_key() -> str:
    """A log-safe rendering of the key: never the value, only the last 4."""
    cfg = maas_config()
    if not cfg:
        return "(unset)"
    key = cfg["api_key"]
    return f"…{key[-4:]}" if len(key) > 4 else "(set)"


def _auth_headers(cfg: dict) -> dict:
    header = cfg["auth_header"]
    if header.lower() == "authorization":
        return {"Authorization": f"Bearer {cfg['api_key']}"}
    return {header: cfg["api_key"]}


def chat(messages: list[dict], *, model: str | None = None, temperature: float = 0.0,
         max_tokens: int = 600, timeout: float = 30.0) -> str:
    """One OpenAI-compatible chat completion against the MaaS endpoint.

    Raises requests.RequestException / KeyError on failure so callers can
    degrade to the deterministic path. Never logs the key."""
    cfg = maas_config(model)
    if not cfg:
        raise RuntimeError("MaaS not configured (set MAAS_ENDPOINT + MAAS_API_KEY)")
    url = f"{cfg['endpoint']}/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(url, json=payload, headers=_auth_headers(cfg), timeout=timeout)
    r.raise_for_status()
    # some models return content: null (e.g. empty completion / reasoning-only) --
    # coerce to "" so callers never trip over None.
    return r.json()["choices"][0]["message"].get("content") or ""


def ping(model: str | None = None) -> int:
    """Preflight smoke test: one cheap chat completion to confirm the endpoint,
    key, and auth header all work before you go on stage. Prints a verdict and
    returns a shell exit code (0 = reachable, 1 = not configured / failed).
    Never prints the key."""
    import sys
    import time

    cfg = maas_config(model)
    if not cfg:
        print("✗ MaaS not configured. Copy .env.example to .env and set "
              "MAAS_API_KEY plus MAAS_BASE+MAAS_MODEL (or MAAS_ENDPOINT).", file=sys.stderr)
        return 1

    print(f"pinging  model={cfg['model']}  endpoint={cfg['endpoint']}  "
          f"key={masked_key()}  header={cfg['auth_header']}", flush=True)
    t0 = time.monotonic()
    try:
        reply = chat([{"role": "user", "content": "Reply with the single word: pong"}],
                     model=model, max_tokens=5, timeout=25)
    except Exception as exc:  # network, auth, shape -- report, don't degrade
        print(f"✗ MaaS unreachable / rejected the request: {exc}", file=sys.stderr)
        print("  Check the endpoint URL (include /v1), the key, and MAAS_AUTH_HEADER "
              "(some 3scale plans want a custom header instead of Bearer).", file=sys.stderr)
        return 1
    dt = time.monotonic() - t0
    shown = reply.strip()[:60] if reply.strip() else "(empty completion)"
    print(f"✓ MaaS reachable in {dt:.2f}s — replied: {shown!r}", flush=True)
    return 0


def ping_all() -> int:
    """Ping every model in MAAS_MODELS -- a preflight for the whole fleet. One
    model failing (down, slow, malformed) never aborts the sweep."""
    import sys
    models = available_models()
    if not models:
        return ping()
    failed = []
    for m in models:
        try:
            rc = ping(m)
        except Exception as exc:  # belt-and-suspenders: keep sweeping
            print(f"✗ {m}: {exc}", file=sys.stderr)
            rc = 1
        if rc != 0:
            failed.append(m)
        print("", file=sys.stderr)
    total = len(models)
    if failed:
        print(f"fleet: {total - len(failed)}/{total} reachable; "
              f"unreachable: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"fleet: {total}/{total} reachable.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    cmd = args[0] if args else "ping"
    if cmd == "ping":
        sys.exit(ping(args[1] if len(args) > 1 else None))
    if cmd == "ping-all":
        sys.exit(ping_all())
    print("usage: python3 -m harness.maas ping [MODEL] | ping-all", file=sys.stderr)
    sys.exit(2)
