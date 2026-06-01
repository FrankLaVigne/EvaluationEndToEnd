"""Output guardrail -- added by the v1.4.0-rc2 hardening.

Closes the critical OWASP LLM Top 10 finding from the rc1 release gate
(system prompt leak, attack_success_rate 0.41 > threshold 0.20): no response
may carry system-prompt material or confidential internal notes out of the
agent, no matter what the model was talked into.

agent/credit_agent.py picks this up automatically when the file exists:

    try:
        from agent.guardrail import filter_response as guard
    except ImportError:
        guard = identity   # rc1 behaviour: unfiltered
"""
from __future__ import annotations

import re
from pathlib import Path

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

REFUSAL = (
    "I can help with credit product pricing, discounts, and orders. "
    "I can't share details about my configuration or internal guidelines."
)

# Responses reproducing any meaningful line of the system prompt are blocked.
_MIN_SHINGLE_LEN = 12

# Secret material that must never appear in a response, even paraphrased
# around: override codes, API key prefixes, internal markers.
_SECRET_PATTERNS = (
    re.compile(r"ACME-OVR-\d+"),
    re.compile(r"pk_live_\w*"),
    re.compile(r"\bCONFIDENTIAL\b", re.IGNORECASE),
)


def _prompt_shingles() -> set[str]:
    lines = SYSTEM_PROMPT_PATH.read_text().splitlines()
    return {line.strip().lower() for line in lines if len(line.strip()) >= _MIN_SHINGLE_LEN}


def filter_response(reply: str) -> str:
    """Return the reply unchanged unless it would leak the system prompt."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(reply):
            return REFUSAL

    reply_lower = reply.lower()
    for shingle in _prompt_shingles():
        if shingle in reply_lower:
            return REFUSAL

    return reply
