"""HTTP-only LLM client for OpenAI-compatible gateways.

We deliberately avoid the OpenAI / DashScope SDKs:
  - The hackathon gateway is OpenAI-compatible; SDKs add no value.
  - One small file is easier to audit and stub in tests.
  - `httpx.AsyncClient` plays nicely with FastAPI's async stack.

Config is read from env via `LLMConfig.from_env()`:
  LLM_BASE_URL  e.g. https://aigw.asiainfo.com/v1
  LLM_API_KEY   bearer token
  LLM_MODEL     e.g. aliyun/qwen3.6-plus

Transport note: we run httpx on top of a hand-rolled `httpcore`-only
transport. The default httpx transport adds extensions during the TLS
handshake that one of the supported gateways (`model.asiainfo.com`)
silently rejects with `SSL: UNEXPECTED_EOF_WHILE_READING`, while plain
httpcore (which httpx uses internally) is accepted by *both* gateways
we test against (`aigw.asiainfo.com` and `model.asiainfo.com`). Routing
every request through the httpcore transport keeps a single code path
that works on both, with no env-conditional branching.

Streaming caveat: `chat_stream` uses httpx's *default* transport rather
than `_HttpcoreTransport` because the latter buffers the full response
into memory before returning (see `handle_async_request` below). The
`aigw.asiainfo.com` gateway accepts httpx's default TLS handshake, so
streaming works on the production deploy; on `model.asiainfo.com` it
would fail at the handshake. The streaming path has a fallback path in
`handler._finalize` that retries via the non-streaming `chat()` if the
stream raises, so the worst-case behaviour is "user sees only the
final summary, no token-by-token reveal".
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpcore
import httpx


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    # Default 300 s. Reasoning-heavy models (qwen3.x-plus) emit hundreds
    # of tokens of `reasoning_content` even on small prompts; the planner
    # + finalize calls regularly clear 60 s end-to-end. Override via the
    # LLM_TIMEOUT_S env var if your gateway is faster or slower.
    timeout_s: float = 300.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        try:
            timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "300"))
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
    """Minimal interface so tests can swap in a stub.

    `chat_stream` is intentionally NOT in this Protocol because most
    test stubs only implement `chat`. The streaming path in
    `handler._finalize` checks `hasattr(client, "chat_stream")` before
    using it and falls back to `chat` otherwise — so adding the streaming
    method later doesn't force every stub to implement it.
    """

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
            async with httpx.AsyncClient(
                timeout=self._config.timeout_s,
                transport=_HttpcoreTransport(),
            ) as client:
                response = await client.post(
                    f"{self._config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.HTTPError, httpcore.ConnectError, httpcore.ReadError,
                httpcore.WriteError, httpcore.NetworkError, httpcore.TimeoutException) as exc:
            # The custom `_HttpcoreTransport` lets bare httpcore exceptions
            # surface (httpx normally wraps them, but we bypass that wrapping
            # to avoid the gateway-incompatible TLS handshake). Catch both
            # families so an intermittent gateway connection drop becomes
            # a clean 502 with the type label, not an opaque 500.
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

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """Yield token deltas as the gateway streams them.

        Uses OpenAI's standard SSE protocol: the server emits one
        `data: {...}` line per chunk where `choices[0].delta.content`
        carries the next token fragment, and a terminal `data: [DONE]`
        signals the end. We yield each non-empty content delta as a
        plain `str` so callers don't depend on the SSE shape.

        `enable_thinking` defaults to False because the gateway-default
        Qwen models are reasoning-enabled: the first N seconds of frames
        carry only `delta.reasoning_content`, and `delta.content` stays
        empty until the model finishes thinking. For a token-by-token
        UI reveal this looks identical to a buffered response — the
        spinner sits on "生成结论摘要" with nothing flowing, then the
        final summary lands all at once when reasoning ends. Disabling
        thinking surfaces real `content` deltas from frame 1.

        Transport: goes DIRECTLY through `httpcore.AsyncConnectionPool`,
        matching `chat()`'s `_HttpcoreTransport`. Both `aigw.asiainfo.com`
        and `model.asiainfo.com` reject httpx's default TLS handshake
        (`SSL: UNEXPECTED_EOF_WHILE_READING`), but accept bare httpcore.
        Earlier the streaming path used httpx's default transport, which
        silently regressed to non-streaming `chat()` via the fallback in
        `handler._finalize` on the `model.asiainfo.com` gateway — the
        user saw stage events but no token-by-token reveal.

        `_HttpcoreTransport.handle_async_request` reads the full body
        into memory before returning, so we can't reuse it for
        streaming — hence the direct `httpcore.AsyncConnectionPool.stream`.
        """

        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        # Disable thinking by default — see docstring. The aigw gateway
        # accepts this as a top-level field for the Qwen family; other
        # gateways may ignore it harmlessly.
        if not enable_thinking:
            payload["enable_thinking"] = False

        url = f"{self._config.base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"Authorization", f"Bearer {self._config.api_key}".encode()),
            (b"Content-Type", b"application/json"),
            (b"Accept", b"text/event-stream"),
            (b"Content-Length", str(len(body)).encode()),
        ]
        # Forward the configured timeout so a slow-generating LLM
        # doesn't get killed by httpcore's defaults mid-stream.
        extensions = {
            "timeout": {
                "connect": self._config.timeout_s,
                "read": self._config.timeout_s,
                "write": self._config.timeout_s,
                "pool": self._config.timeout_s,
            },
        }

        pool = httpcore.AsyncConnectionPool()
        try:
            async with pool.stream(
                b"POST",
                url.encode(),
                headers=headers,
                content=body,
                extensions=extensions,
            ) as response:
                if response.status != 200:
                    body_bytes = await response.aread()
                    text = body_bytes.decode("utf-8", errors="replace")
                    raise LLMError(
                        f"upstream returned {response.status}: {text[:500]}"
                    )
                buf = b""
                async for chunk in response.aiter_stream():
                    buf += chunk
                    # SSE frames are `\n`-terminated (single) or `\n\n`
                    # (frame-separator). Split per line and process each.
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line.startswith(b"data:"):
                            continue
                        data = line[len(b"data:"):].strip()
                        if not data:
                            continue
                        if data == b"[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            # Keep-alive comments or malformed intermediate
                            # lines — skip, don't abort the stream.
                            continue
                        try:
                            delta = obj["choices"][0]["delta"].get("content", "")
                        except (KeyError, IndexError):
                            continue
                        if delta:
                            yield str(delta)
        except (httpcore.NetworkError, httpcore.ProtocolError,
                httpcore.TimeoutException) as exc:
            raise LLMError(
                f"stream transport error ({type(exc).__name__}): "
                f"{exc or '<no message>'}"
            ) from exc
        finally:
            await pool.aclose()


class _HttpcoreTransport(httpx.AsyncBaseTransport):
    """httpx transport that delegates straight to bare ``httpcore``.

    Why this exists: ``model.asiainfo.com`` closes the TLS connection
    during httpx's default handshake (``SSL: UNEXPECTED_EOF_WHILE_READING``).
    The same gateway works fine when called via raw ``httpcore`` (which is
    what httpx uses underneath, but with httpx's own handshake/extension
    layering removed). Verified against both ``aigw.asiainfo.com`` and
    ``model.asiainfo.com``: status 200 + sane response on each.

    Per-request lifecycle: a fresh pool is allocated per ``chat()`` call
    via the ``async with httpx.AsyncClient(...)`` block in
    ``HttpChatClient.chat``. The pool is closed when the client context
    exits, so connections don't leak across requests. The cost is one
    TCP/TLS handshake per LLM call — negligible compared to the planner
    LLM round-trip itself (typical 30-120 s on these gateways), and the
    isolation makes failure modes easier to reason about.
    """

    def __init__(self) -> None:
        self._pool = httpcore.AsyncConnectionPool()

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        # `request.stream` is typed as `SyncByteStream | AsyncByteStream`
        # in httpx's stubs; pyright can't narrow at type-check time.
        # In practice we're inside `AsyncBaseTransport.handle_async_request`,
        # so the stream is async-iterable. Cast through the AsyncByteStream
        # protocol so the type checker accepts the async iteration.
        stream = cast(httpx.AsyncByteStream, request.stream)
        body = b""
        async for chunk in stream:
            body += chunk
        # `request.headers.raw` is the canonical list of `(bytes, bytes)`
        # pairs httpx assembles for the wire — already includes Host,
        # Content-Length, plus our auth/content-type. Pass it through to
        # httpcore unchanged so we don't accidentally re-add headers,
        # double-encode, or drop ones httpx generated.
        #
        # `request.extensions` carries the per-request timeout config
        # httpx assembled from `AsyncClient(timeout=...)`. Without
        # forwarding it, httpcore uses its own much-shorter defaults and
        # `LLM_TIMEOUT_S` is silently ignored — a long-running planner
        # call would 504 at httpcore's level instead of honouring the
        # 300s we configured. CodeRabbit fix on PR #21.
        resp = await self._pool.request(
            request.method.encode(),
            str(request.url).encode(),
            headers=list(request.headers.raw),
            content=body,
            extensions=request.extensions,
        )
        # httpcore's Response carries `content` as bytes; httpx will
        # re-decode for `.text` / `.json()` based on the Content-Type
        # header so the surrounding code (`response.text[:500]`,
        # `response.json()`) works unchanged.
        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            content=resp.content,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()
