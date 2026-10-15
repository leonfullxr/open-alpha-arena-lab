from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

import httpx
import pytest
from app.llm.providers import (
    OPENAI_CHAT_URL,
    OPENAI_RESPONSES_URL,
    OPENCODE_CLIENT_USER_AGENT,
    OPENCODE_GO_CHAT_URL,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    build_request_bytes,
)
from app.llm.schema import ProposalOutputError, parse_proposal_output

VALID_OUTPUT = json.dumps(
    {
        "proposals": [
            {
                "action": "OPEN_LONG",
                "symbol": "BTC",
                "quantity": 0.01,
                "leverage": 2,
                "stop_loss": 90,
                "take_profit": 120,
                "confidence": 0.75,
                "invalidation": "The trend breaks below 90.",
                "justification": "The supplied snapshot shows upward momentum.",
            }
        ]
    }
)


def test_proposal_schema_accepts_finite_decimal_payload_and_rejects_unsafe_shape() -> None:
    result = parse_proposal_output(VALID_OUTPUT.encode())
    assert result.proposals[0].quantity == Decimal("0.01")
    assert result.proposals[0].action.value == "OPEN_LONG"
    for invalid in (
        {"proposals": [{**json.loads(VALID_OUTPUT)["proposals"][0], "extra": "hidden"}]},
        {"proposals": [{**json.loads(VALID_OUTPUT)["proposals"][0], "quantity": "NaN"}]},
        {"proposals": [{**json.loads(VALID_OUTPUT)["proposals"][0], "confidence": 1.5}]},
        {"proposals": [{**json.loads(VALID_OUTPUT)["proposals"][0], "symbol": "BTC\nsecret"}]},
    ):
        with pytest.raises(ProposalOutputError):
            parse_proposal_output(json.dumps(invalid).encode())


def test_chat_adapter_posts_only_to_fixed_endpoint_and_keeps_only_visible_content() -> None:
    seen: list[httpx.Request] = []
    response = {
        "id": "resp-1",
        "choices": [
            {
                "message": {
                    "content": VALID_OUTPUT,
                    "reasoning": "private hidden reasoning must not be captured",
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response)

    config = ProviderConfig(
        provider="openai",
        model="approved-model",
        endpoint=OPENAI_CHAT_URL,
        input_cost_per_million=Decimal("1"),
        output_cost_per_million=Decimal("2"),
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAICompatibleProvider(config, api_key="local-test-secret", client=client)
        exact_body = build_request_bytes(
            config,
            system_prompt_bytes=b"exact system prompt",
            user_prompt_bytes=b"exact prompt bytes",
        )
        result = provider.invoke(request_bytes=exact_body)
    assert len(seen) == 1
    assert str(seen[0].url) == OPENAI_CHAT_URL
    assert seen[0].headers["authorization"] == "Bearer local-test-secret"
    sent = json.loads(seen[0].content)
    assert sent["messages"] == [
        {"role": "system", "content": "exact system prompt"},
        {"role": "user", "content": "exact prompt bytes"},
    ]
    assert sent["max_tokens"] == 1000
    assert result.output_bytes == VALID_OUTPUT.encode()
    assert b"private hidden" not in result.output_bytes
    assert result.usage == {"input_tokens": 100, "output_tokens": 20}
    assert result.estimated_cost == Decimal("0.00014")
    assert result.response_id == "resp-1"


def test_opencode_endpoint_model_and_user_agent_are_fixed() -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": VALID_OUTPUT}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    config = ProviderConfig(
        provider="opencode_go",
        model="mimo-v2.6-flash",
        endpoint=OPENCODE_GO_CHAT_URL,
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        body = build_request_bytes(
            config, system_prompt_bytes=b"system", user_prompt_bytes=b"snapshot-only prompt"
        )
        OpenAICompatibleProvider(
            config,
            api_key="test-key",
            session_id="opaque-agent-session-0123456789",
            client=client,
        ).invoke(
            request_bytes=body
        )
    assert str(captured[0].url) == OPENCODE_GO_CHAT_URL
    assert captured[0].headers["user-agent"] == OPENCODE_CLIENT_USER_AGENT
    assert captured[0].headers["x-opencode-session"] == "opaque-agent-session-0123456789"
    with pytest.raises(ValueError, match="not approved"):
        ProviderConfig(provider="opencode_go", model="arbitrary", endpoint=OPENCODE_GO_CHAT_URL)


def test_responses_adapter_extracts_visible_output_text_only() -> None:
    request_payloads: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        request_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-2",
                "output": [
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "private"}]},
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": VALID_OUTPUT},
                            {"type": "refusal", "refusal": "not visible output"},
                        ],
                    },
                ],
                "usage": {"input_tokens": 4, "output_tokens": 5},
            },
        )

    config = ProviderConfig(
        provider="openai", model="approved-model", endpoint=OPENAI_RESPONSES_URL
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        body = build_request_bytes(
            config, system_prompt_bytes=b"system", user_prompt_bytes=b"exact prompt"
        )
        result = OpenAICompatibleProvider(config, api_key="test-key", client=client).invoke(
            request_bytes=body
        )
    assert request_payloads[0]["input"] == [
        {"role": "system", "content": [{"type": "input_text", "text": "system"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "exact prompt"}]},
    ]
    assert request_payloads[0]["max_output_tokens"] == 1000
    assert result.output_bytes == VALID_OUTPUT.encode()
    assert b"private" not in result.output_bytes
    assert result.usage == {"input_tokens": 4, "output_tokens": 5}


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "PROVIDER_HTTP_ERROR"),
        (403, "PROVIDER_HTTP_ERROR"),
        (429, "PROVIDER_HTTP_ERROR"),
        (503, "PROVIDER_HTTP_ERROR"),
        (302, "PROVIDER_REDIRECT_REJECTED"),
    ],
)
def test_paid_call_errors_are_sanitized_and_never_retried(status: int, expected_code: str) -> None:
    requests = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            status, headers={"location": "https://attacker.invalid/"}, text="secret"
        )

    config = ProviderConfig(provider="openai", model="approved-model", endpoint=OPENAI_CHAT_URL)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            body = build_request_bytes(
                config, system_prompt_bytes=b"system", user_prompt_bytes=b"prompt"
            )
            OpenAICompatibleProvider(config, api_key="secret", client=client).invoke(
                request_bytes=body
            )
    assert caught.value.code == expected_code
    assert caught.value.status_code == status
    assert requests == 1
    assert "attacker" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_malformed_oversize_and_invalid_usage_responses_fail_closed() -> None:
    config = ProviderConfig(provider="openai", model="approved-model", endpoint=OPENAI_CHAT_URL)
    for body in (b"not-json", b"{" + b" " * 100):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _request, content=body: httpx.Response(200, content=content)
            )
        ) as client:
            provider = OpenAICompatibleProvider(
                config, api_key="test-key", client=client, max_response_bytes=50
            )
            with pytest.raises(ProviderError):
                request = build_request_bytes(
                    config, system_prompt_bytes=b"system", user_prompt_bytes=b"prompt"
                )
                provider.invoke(request_bytes=request)

    bad_usage = {
        "choices": [{"message": {"content": VALID_OUTPUT}}],
        "usage": {"prompt_tokens": -1, "completion_tokens": 0},
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=bad_usage))
    ) as client:
        with pytest.raises(ProviderError, match="PROVIDER_INVALID_RESPONSE"):
            request = build_request_bytes(
                config, system_prompt_bytes=b"system", user_prompt_bytes=b"prompt"
            )
            OpenAICompatibleProvider(config, api_key="test-key", client=client).invoke(
                request_bytes=request
            )

    responses_config = ProviderConfig(
        provider="openai", model="approved-model", endpoint=OPENAI_RESPONSES_URL
    )
    malformed_responses = (
        cast(dict[str, object], {"output": None}),
        cast(dict[str, object], {"output": [{"type": "message", "content": None}]}),
    )
    for malformed in malformed_responses:
        def handle_malformed(
            _request: httpx.Request, body: dict[str, object] = malformed
        ) -> httpx.Response:
            return httpx.Response(200, json=body)

        with httpx.Client(transport=httpx.MockTransport(handle_malformed)) as client:
            body = build_request_bytes(
                responses_config, system_prompt_bytes=b"system", user_prompt_bytes=b"prompt"
            )
            with pytest.raises(ProviderError) as caught:
                OpenAICompatibleProvider(
                    responses_config, api_key="test-key", client=client
                ).invoke(request_bytes=body)
            assert caught.value.code == "PROVIDER_INVALID_RESPONSE"


def test_real_http_wait_for_generation_can_exceed_subsecond_idle_time() -> None:
    class DelayedHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            self.rfile.read(length)
            time.sleep(0.7)
            content = json.dumps(
                {"choices": [{"message": {"content": VALID_OUTPUT}}], "usage": {}}
            ).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    class LocalOriginClient:
        def __init__(self, local_url: str) -> None:
            self.local_url = local_url
            self.client = httpx.Client(follow_redirects=False)

        def stream(
            self,
            method: str,
            url: str,
            *,
            content: bytes,
            headers: Mapping[str, str],
            timeout: httpx.Timeout,
            follow_redirects: bool,
        ) -> AbstractContextManager[httpx.Response]:
            assert url == OPENAI_CHAT_URL
            return self.client.stream(
                method,
                self.local_url,
                content=content,
                headers=headers,
                timeout=timeout,
                follow_redirects=follow_redirects,
            )

        def close(self) -> None:
            self.client.close()

    server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = ProviderConfig(provider="openai", model="approved-model", endpoint=OPENAI_CHAT_URL)
        body = build_request_bytes(
            config, system_prompt_bytes=b"system", user_prompt_bytes=b"prompt"
        )
        local_url = f"http://127.0.0.1:{server.server_port}/chat"
        client = LocalOriginClient(local_url)
        started = time.monotonic()
        result = OpenAICompatibleProvider(
            config,
            api_key="test-key",
            timeout_seconds=2,
            client=cast(httpx.Client, client),
        ).invoke(request_bytes=body)
        assert time.monotonic() - started >= 0.6
        assert result.output_bytes == VALID_OUTPUT.encode()
        client.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_endpoint_redirects_and_nonapproved_urls_are_rejected() -> None:
    with pytest.raises(ValueError, match="endpoint is not approved"):
        ProviderConfig(provider="openai", model="model", endpoint="http://127.0.0.1:8000")
    config = ProviderConfig(provider="openai", model="model", endpoint=OPENAI_CHAT_URL)
    with pytest.raises(ValueError, match="key is required"):
        OpenAICompatibleProvider(config, api_key="\n")
