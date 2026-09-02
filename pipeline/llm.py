"""LLM provider interface: structured JSON extraction via Ollama (default) or the Anthropic API.

Both providers expose the same `extract_json(system, user, schema)` call so stages never know
which model is behind it. Provider selection is `LLM_PROVIDER` in .env.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _ollama_extract(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    s = settings()
    resp = httpx.post(
        f"{s.ollama_base_url}/api/chat",
        json={
            "model": s.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,  # Ollama structured outputs: constrained to this JSON schema
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        },
        timeout=300,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"ollama returned non-JSON: {content[:200]}") from e


def _anthropic_extract(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    s = settings()
    if not s.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
        json={
            "model": s.anthropic_model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": "emit",
                    "description": "Emit the extraction result.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "emit"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    for block in resp.json()["content"]:
        if block.get("type") == "tool_use":
            return block["input"]
    raise LLMError("anthropic response had no tool_use block")


def extract_json(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    provider = settings().llm_provider
    if provider == "ollama":
        return _ollama_extract(system, user, schema)
    if provider == "anthropic":
        return _anthropic_extract(system, user, schema)
    raise LLMError(f"unknown LLM_PROVIDER {provider!r}")


def model_name() -> str:
    s = settings()
    return (
        f"ollama:{s.ollama_model}"
        if s.llm_provider == "ollama"
        else f"anthropic:{s.anthropic_model}"
    )
