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
