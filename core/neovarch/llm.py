"""Streaming client for OpenAI-compatible ``/chat/completions`` with tool calls."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

import aiohttp


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""

    def parsed_args(self) -> dict[str, Any]:
        if not self.arguments.strip():
            return {}
        try:
            value = json.loads(self.arguments)
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError:
            return {"_raw": self.arguments}


@dataclass
class Completion:
    text: str = ""
    reasoning: str = ""
    reasoning_skipped: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


async def _sse_lines(resp: aiohttp.ClientResponse) -> AsyncIterator[str]:
    buffer = b""
    async for chunk in resp.content.iter_any():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line.decode("utf-8", "replace").rstrip("\r")
    if buffer:
        yield buffer.decode("utf-8", "replace")


async def stream_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    on_text: Callable[[str], Any] | None = None,
    on_reasoning: Callable[[str], Any] | None = None,
    timeout_s: float = 600,
    session: aiohttp.ClientSession | None = None,
    extra_headers: dict[str, str] | None = None,
    verify_ssl: bool = True,
    reasoning_effort: str | None = None,
) -> Completion:
    """POST a streaming chat completion; call back per text/reasoning delta.

    ``reasoning_effort`` (minimal/low/medium/high) is sent as the
    OpenAI-compatible ``reasoning_effort`` field; OpenRouter-style gateways get
    ``reasoning: {effort}``. A provider that rejects the field is asked again
    without it, and the completion says so (``reasoning_skipped``).
    """
    if reasoning_effort:
        try:
            return await _stream_chat(base_url, api_key, model, messages, tools, on_text, on_reasoning, timeout_s,
                                      session, extra_headers, verify_ssl, reasoning_effort)
        except LLMError as exc:
            text = str(exc).lower()
            if "http 400" not in text and "http 422" not in text:
                raise
            if "reason" not in text and "unrecognized" not in text and "unknown" not in text \
                    and "not support" not in text and "extra" not in text:
                raise
        out = await _stream_chat(base_url, api_key, model, messages, tools, on_text, on_reasoning, timeout_s,
                                 session, extra_headers, verify_ssl, None)
        out.reasoning_skipped = True
        return out
    return await _stream_chat(base_url, api_key, model, messages, tools, on_text, on_reasoning, timeout_s,
                              session, extra_headers, verify_ssl, None)


def reasoning_fields(base_url: str, effort: str | None) -> dict[str, Any]:
    """The request fields that carry a reasoning effort for this provider."""
    if not effort:
        return {}
    if "openrouter.ai" in (base_url or ""):
        return {"reasoning": {"effort": effort}}
    return {"reasoning_effort": effort}


async def _stream_chat(base_url, api_key, model, messages, tools, on_text, on_reasoning, timeout_s,
                       session, extra_headers, verify_ssl, reasoning_effort) -> Completion:
    if not base_url:
        raise LLMError("Belum ada model. Pilih model di Pengaturan → Model (No model provider configured; run `neovarch setup` or set model.base_url in config.yaml).")
    url = base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {"model": model or "default", "messages": messages, "stream": True,
                            "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    body.update(reasoning_fields(base_url, reasoning_effort))
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for k, v in (extra_headers or {}).items():
        if k and v is not None:
            headers[str(k)] = str(v)

    out = Completion()
    calls: dict[int, ToolCall] = {}
    own = session is None
    sess = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s))
    try:
        async with sess.post(url, json=body, headers=headers, ssl=ssl.create_default_context() if verify_ssl else False) as resp:
            if resp.status >= 400:
                detail = (await resp.text())[:800]
                raise LLMError(f"provider returned HTTP {resp.status}: {detail}")
            ctype = resp.headers.get("Content-Type", "")
            if "text/event-stream" not in ctype:
                # Some servers ignore stream=true; accept a plain JSON completion.
                data = await resp.json(content_type=None)
                return _from_plain(data, on_text)
            async for line in _sse_lines(resp):
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise LLMError(str(event["error"].get("message") if isinstance(event["error"], dict) else event["error"]))
                if event.get("usage"):
                    # Merge, never replace: a split stream sends the prompt counts in an early
                    # chunk and the completion in the last one (see usage_stats.merge_stream_usage).
                    from neovarch.usage_stats import merge_stream_usage
                    out.usage = merge_stream_usage(out.usage, event["usage"]) or {}
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        out.text += text
                        if on_text:
                            on_text(text)
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if isinstance(reasoning, str) and reasoning:
                        out.reasoning += reasoning
                        if on_reasoning:
                            on_reasoning(reasoning)
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index", len(calls)))
                        call = calls.setdefault(idx, ToolCall(id=tc.get("id") or f"call_{idx}", name=""))
                        if tc.get("id"):
                            call.id = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            call.name += fn["name"]
                        if fn.get("arguments"):
                            call.arguments += fn["arguments"]
                    if choice.get("finish_reason"):
                        out.finish_reason = choice["finish_reason"]
    except aiohttp.ClientError as exc:
        raise LLMError(f"could not reach the model provider at {url}: {exc}") from exc
    finally:
        if own:
            await sess.close()
    out.tool_calls = [calls[i] for i in sorted(calls)]
    return out


def _from_plain(data: dict, on_text) -> Completion:
    out = Completion()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    out.text = msg.get("content") or ""
    if out.text and on_text:
        on_text(out.text)
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        out.tool_calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=fn.get("arguments", "")))
    out.finish_reason = choice.get("finish_reason") or ""
    out.usage = data.get("usage") or {}
    return out
