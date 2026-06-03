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


def maas_config() -> dict | None:
    """Return the MaaS config dict, or None if not fully configured.
    Requires at least an endpoint and an API key."""
    load_dotenv()
    endpoint = os.environ.get("MAAS_ENDPOINT", "").strip().rstrip("/")
    api_key = os.environ.get("MAAS_API_KEY", "").strip()
    model = os.environ.get("MAAS_MODEL", "").strip()
    if not endpoint or not api_key:
        return None
    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model": model or "default",
        "auth_header": os.environ.get("MAAS_AUTH_HEADER", "Authorization").strip(),
    }


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


def chat(messages: list[dict], *, temperature: float = 0.0,
         max_tokens: int = 600, timeout: float = 30.0) -> str:
    """One OpenAI-compatible chat completion against the MaaS endpoint.

    Raises requests.RequestException / KeyError on failure so callers can
    degrade to the deterministic path. Never logs the key."""
    cfg = maas_config()
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
    return r.json()["choices"][0]["message"]["content"]


def ping() -> int:
    """Preflight smoke test: one cheap chat completion to confirm the endpoint,
    key, and auth header all work before you go on stage. Prints a verdict and
    returns a shell exit code (0 = reachable, 1 = not configured / failed).
    Never prints the key."""
    import sys
    import time

    cfg = maas_config()
    if not cfg:
        print("✗ MaaS not configured. Copy .env.example to .env and set "
              "MAAS_ENDPOINT + MAAS_API_KEY (+ MAAS_MODEL).", file=sys.stderr)
        return 1

    print(f"pinging  model={cfg['model']}  endpoint={cfg['endpoint']}  "
          f"key={masked_key()}  header={cfg['auth_header']}", flush=True)
    t0 = time.monotonic()
    try:
        reply = chat([{"role": "user", "content": "Reply with the single word: pong"}],
                     max_tokens=5, timeout=15)
    except Exception as exc:  # network, auth, shape -- report, don't degrade
        print(f"✗ MaaS unreachable / rejected the request: {exc}", file=sys.stderr)
        print("  Check the endpoint URL (include /v1), the key, and MAAS_AUTH_HEADER "
              "(some 3scale plans want a custom header instead of Bearer).", file=sys.stderr)
        return 1
    dt = time.monotonic() - t0
    print(f"✓ MaaS reachable in {dt:.2f}s — replied: {reply.strip()[:60]!r}")
    return 0


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "ping"
    if arg == "ping":
        sys.exit(ping())
    print(f"usage: python3 -m harness.maas ping", file=sys.stderr)
    sys.exit(2)
