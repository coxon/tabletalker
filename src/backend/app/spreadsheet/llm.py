"""HTTP-only LLM client for OpenAI-compatible gateways.

We deliberately avoid the OpenAI / DashScope SDKs:
  - The hackathon gateway is OpenAI-compatible; SDKs add no value.
  - One small file is easier to audit and stub in tests.
  - `httpx.AsyncClient` plays nicely with FastAPI's async stack.

Config is read from env via `LLMConfig.from_env()`:
  LLM_BASE_URL  e.g. https://aigw.asiainfo.com/v1
  LLM_API_KEY   bearer token
  LLM_MODEL     e.g. aliyun/qwen3.6-plus
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    # Default 120 s. Reasoning-heavy models (qwen3.x-plus) emit hundreds
    # of tokens of `reasoning_content` even on small prompts; the planner
    # + finalize calls regularly clear 60 s end-to-end. Override via the
    # LLM_TIMEOUT_S env var if your gateway is faster or slower.
    timeout_s: float = 120.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        try:
            timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "120"))
            # Reject 0, negatives, NaN, +/-inf — these would fail later on the
            # request path with an opaque httpx error; failing here keeps the
            # blast radius at config-load time.
            if not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError(
                    "LLM_TIMEOUT_S must be a positive finite number"
                )
            return cls(
                base_url=os.environ["LLM_BASE_URL"].rstrip("/"),
                api_key=os.environ["LLM_API_KEY"],
                model=os.environ["LLM_MODEL"],
                timeout_s=timeout_s,
            )
        except KeyError as exc:
            raise LLMConfigError(
                f"missing required env var {exc.args[0]!r} "
                "(see .env.example: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL)"
            ) from exc
        except ValueError as exc:
            raise LLMConfigError(
                f"LLM_TIMEOUT_S must be a positive finite number: {exc}"
            ) from exc


class LLMConfigError(Exception):
    """Required env var missing."""


class LLMError(Exception):
    """Network, HTTP, or response-shape problem."""


class ChatClient(Protocol):
    """Minimal interface so tests can swap in a stub."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        ...


class HttpChatClient:
    """Real client against an OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            async with httpx.AsyncClient(timeout=self._config.timeout_s) as client:
                response = await client.post(
                    f"{self._config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            # `str(exc)` is empty for some httpx exceptions (e.g.
            # RemoteProtocolError on a clean connection drop) — without
            # the type label we lose all signal at the 502 boundary.
            raise LLMError(
                f"transport error ({type(exc).__name__}): {exc or '<no message>'}"
            ) from exc

        if response.status_code != 200:
            raise LLMError(
                f"upstream returned {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected response shape: {exc}") from exc
