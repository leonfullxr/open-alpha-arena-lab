from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENCODE_GO_CHAT_URL = "https://opencode.ai/inference/go/v1/chat/completions"
OPENCODE_CLIENT_USER_AGENT = "open-alpha-arena-lab/0.1"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_PROVIDER_RESPONSE_BYTES = 1_000_000
MAX_OUTPUT_TOKENS = 2_000
MAX_REQUEST_SECONDS = 120.0


class ProviderError(RuntimeError):
    """A sanitized provider failure suitable for durable job error codes."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = (
            status_code
            if status_code is not None and 100 <= status_code <= 599
            else None
        )


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider: str
    model: str
    endpoint: str
    max_output_tokens: int = 1_000
    temperature: Decimal = Decimal("0")
    input_cost_per_million: Decimal | None = None
    output_cost_per_million: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.provider or len(self.provider) > 60:
            raise ValueError("provider identifier is invalid")
        if not self.model or len(self.model) > 120:
            raise ValueError("model identifier is invalid")
        if self.endpoint not in {OPENAI_CHAT_URL, OPENCODE_GO_CHAT_URL, OPENAI_RESPONSES_URL}:
            raise ValueError("provider endpoint is not approved")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("maximum output tokens must be bounded")
        for value in (
            self.temperature,
            self.input_cost_per_million,
            self.output_cost_per_million,
        ):
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value < 0
            ):
                raise ValueError("provider numeric settings must be finite and non-negative")
        if self.temperature > 2:
            raise ValueError("temperature exceeds provider bound")
        if self.endpoint == OPENCODE_GO_CHAT_URL and self.model not in {
            "mimo-v2.6-flash",
            "glm-5.3-flash",
        }:
            raise ValueError("model is not approved for OpenCode Go")

    @property
    def public_parameters(self) -> dict[str, int | str]:
        return {
            "max_output_tokens": self.max_output_tokens,
            "temperature": format(self.temperature, "f"),
            "response_format": "json_object",
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    output_bytes: bytes
    usage: dict[str, int]
    latency_ms: int
    estimated_cost: Decimal | None
    response_id: str | None


def build_request_bytes(
    config: ProviderConfig, *, system_prompt_bytes: bytes, user_prompt_bytes: bytes
) -> bytes:
    """Build the exact non-secret HTTP body persisted before inference dispatch."""
    try:
        system_text = system_prompt_bytes.decode("utf-8", errors="strict")
        user_text = user_prompt_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ValueError("provider prompts must be UTF-8") from None
    if not system_text or not user_text:
        raise ValueError("system and user prompts are required")
    if config.endpoint == OPENAI_RESPONSES_URL:
        body: dict[str, object] = {
            "model": config.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
            ],
            "temperature": config.temperature,
            "max_output_tokens": config.max_output_tokens,
            "text": {"format": {"type": "json_object"}},
        }
    else:
        body = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
    return _canonical_request_bytes(body)


def _canonical_request_bytes(value: object) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("provider request cannot contain non-finite numeric values")
        return format(value, "f").encode("ascii")
    if isinstance(value, list):
        return b"[" + b",".join(_canonical_request_bytes(item) for item in value) + b"]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        parts = []
        for key in sorted(value):
            encoded_key = json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            parts.append(encoded_key + b":" + _canonical_request_bytes(value[key]))
        return b"{" + b",".join(parts) + b"}"
    raise ValueError("provider request contains an unsupported value")


def _parse_json(payload: bytes) -> object:
    try:
        return json.loads(payload, parse_float=Decimal, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ProviderError("PROVIDER_INVALID_RESPONSE") from None


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProviderError("PROVIDER_INVALID_RESPONSE")
    return value


def _visible_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            part = _mapping(item)
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)
    raise ProviderError("PROVIDER_INVALID_RESPONSE")


def _nonnegative_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ProviderError("PROVIDER_INVALID_RESPONSE")
    if value < 0 or (isinstance(value, Decimal) and value != value.to_integral_value()):
        raise ProviderError("PROVIDER_INVALID_RESPONSE")
    return int(value)


def _usage(raw: object) -> dict[str, int]:
    data = _mapping(raw)
    if "prompt_tokens" in data or "completion_tokens" in data:
        return {
            "input_tokens": _nonnegative_count(data.get("prompt_tokens", 0)),
            "output_tokens": _nonnegative_count(data.get("completion_tokens", 0)),
        }
    return {
        "input_tokens": _nonnegative_count(data.get("input_tokens", 0)),
        "output_tokens": _nonnegative_count(data.get("output_tokens", 0)),
    }


def _estimated_cost(config: ProviderConfig, usage: dict[str, int]) -> Decimal | None:
    if config.input_cost_per_million is None or config.output_cost_per_million is None:
        return None
    return (
        Decimal(usage["input_tokens"]) * config.input_cost_per_million
        + Decimal(usage["output_tokens"]) * config.output_cost_per_million
    ) / Decimal(1_000_000)


class OpenAICompatibleProvider:
    """Single-attempt OpenAI-compatible chat and Responses client.

    The adapter accepts only immutable server-supplied prompts and approved endpoints;
    it never retries paid calls or follows redirects.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        api_key: str,
        timeout_seconds: float = MAX_REQUEST_SECONDS,
        max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
        session_id: str | None = None,
        client: httpx.Client | None = None,
        monotonic: Any = time.monotonic,
    ) -> None:
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise ValueError("provider key is required")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_REQUEST_SECONDS:
            raise ValueError("provider deadline must be bounded")
        if not 1 <= max_response_bytes <= MAX_PROVIDER_RESPONSE_BYTES:
            raise ValueError("provider response size bound is invalid")
        if session_id is not None and not re.fullmatch(r"[A-Za-z0-9._-]{16,128}", session_id):
            raise ValueError("provider conversation identifier is invalid")
        self.config = config
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._session_id = session_id
        self._client = client or httpx.Client(follow_redirects=False)
        self._owns_client = client is None
        self._monotonic = monotonic

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAICompatibleProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def invoke(self, *, request_bytes: bytes) -> ProviderResult:
        if not isinstance(request_bytes, bytes) or not request_bytes:
            raise ValueError("request body must be exact non-empty bytes")
        self._validate_request(request_bytes)
        started = self._monotonic()
        deadline = started + self._timeout_seconds
        connect_timeout = min(5.0, self._timeout_seconds * 0.05)
        remaining_read = max(0.1, self._timeout_seconds - connect_timeout)
        timeout = httpx.Timeout(
            self._timeout_seconds,
            connect=connect_timeout,
            read=remaining_read,
            write=remaining_read,
            pool=connect_timeout,
        )
        try:
            with self._client.stream(
                "POST",
                self.config.endpoint,
                content=request_bytes,
                headers=self._headers(),
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise ProviderError(
                        "PROVIDER_REDIRECT_REJECTED", status_code=response.status_code
                    )
                if not 200 <= response.status_code < 300:
                    raise ProviderError("PROVIDER_HTTP_ERROR", status_code=response.status_code)
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        length = int(content_length)
                    except ValueError:
                        raise ProviderError("PROVIDER_INVALID_RESPONSE") from None
                    if length < 0:
                        raise ProviderError("PROVIDER_INVALID_RESPONSE")
                    if length > self._max_response_bytes:
                        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE")
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    raw.extend(chunk)
                    if len(raw) > self._max_response_bytes:
                        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE")
                    if self._monotonic() > deadline:
                        raise ProviderError("PROVIDER_TIMEOUT")
            visible_text, usage, response_id = self._extract(bytes(raw))
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("PROVIDER_TIMEOUT") from None
        except httpx.RequestError:
            raise ProviderError("PROVIDER_TRANSPORT_ERROR") from None
        latency_ms = max(0, int((self._monotonic() - started) * 1000))
        return ProviderResult(
            output_bytes=visible_text.encode("utf-8"),
            usage=usage,
            latency_ms=latency_ms,
            estimated_cost=_estimated_cost(self.config, usage),
            response_id=response_id,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        }
        if self.config.endpoint == OPENCODE_GO_CHAT_URL:
            headers["user-agent"] = OPENCODE_CLIENT_USER_AGENT
            if self._session_id is not None:
                headers["x-opencode-session"] = self._session_id
        return headers

    def _validate_request(self, request_bytes: bytes) -> dict[str, Any]:
        value = _mapping(_parse_json(request_bytes))
        expected = _parse_json(
            build_request_bytes(
                self.config,
                system_prompt_bytes=self._extract_prompt(request_bytes, "system"),
                user_prompt_bytes=self._extract_prompt(request_bytes, "user"),
            )
        )
        if value != expected:
            raise ValueError("provider request does not match its frozen settings")
        return dict(value)

    def _extract_prompt(self, request_bytes: bytes, role: str) -> bytes:
        body = _mapping(_parse_json(request_bytes))
        messages = body.get("messages") if "messages" in body else body.get("input")
        if not isinstance(messages, list):
            raise ValueError("provider request has no explicit system and user prompts")
        for message in messages:
            item = _mapping(message)
            if item.get("role") != role:
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content.encode("utf-8")
            if isinstance(content, list) and len(content) == 1:
                part = _mapping(content[0])
                text_value = part.get("text")
                if part.get("type") in {"input_text", "text"} and isinstance(text_value, str):
                    return text_value.encode("utf-8")
        raise ValueError("provider request is missing an explicit prompt role")

    def _extract(self, payload: bytes) -> tuple[str, dict[str, int], str | None]:
        try:
            root = _mapping(_parse_json(payload))
            usage = _usage(root.get("usage", {}))
            response_id = root.get("id")
            if response_id is not None and not isinstance(response_id, str):
                raise ProviderError("PROVIDER_INVALID_RESPONSE")
            if self.config.endpoint == OPENAI_RESPONSES_URL:
                text = root.get("output_text")
                if isinstance(text, str):
                    visible = text
                else:
                    output_value = root.get("output", [])
                    if not isinstance(output_value, list):
                        raise ProviderError("PROVIDER_INVALID_RESPONSE")
                    output: list[str] = []
                    for item in output_value:
                        block = _mapping(item)
                        if block.get("type") != "message":
                            continue
                        content_value = block.get("content", [])
                        if not isinstance(content_value, list):
                            raise ProviderError("PROVIDER_INVALID_RESPONSE")
                        for content in content_value:
                            part = _mapping(content)
                            if part.get("type") == "output_text" and isinstance(
                                part.get("text"), str
                            ):
                                output.append(part["text"])
                    visible = "".join(output)
            else:
                choices = root.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise ProviderError("PROVIDER_INVALID_RESPONSE")
                choice = _mapping(choices[0])
                message = _mapping(choice.get("message"))
                visible = _visible_text(message.get("content"))
        except ProviderError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ProviderError("PROVIDER_INVALID_RESPONSE") from None
        if not visible or len(visible.encode("utf-8")) > self._max_response_bytes:
            raise ProviderError("PROVIDER_INVALID_RESPONSE")
        return visible, usage, response_id
