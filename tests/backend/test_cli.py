from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from app import cli
from app.llm import smoke
from app.market.hyperliquid import HyperliquidClient

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "live-smoke.example.json"


@pytest.mark.parametrize(
    ("rounds", "key", "error_code"),
    [
        (6, "smoke-test-key", "SMOKE_ROUND_LIMIT"),
        (5, None, "PROVIDER_NOT_CONFIGURED"),
    ],
    ids=("round-limit-before-market", "missing-key-before-market"),
)
def test_live_smoke_preflight_errors_are_sanitized_and_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rounds: int,
    key: str | None,
    error_code: str,
) -> None:
    calls = {"market_client": 0, "provider": 0}

    def forbidden_client_init(self: object, *args: object, **kwargs: object) -> None:
        calls["market_client"] += 1
        raise AssertionError("market client must not be constructed for failed preflight")

    def forbidden_provider(*args: Any, **kwargs: Any) -> None:
        calls["provider"] += 1
        raise AssertionError("provider must not be called for failed preflight")

    monkeypatch.setattr(HyperliquidClient, "__init__", forbidden_client_init)
    monkeypatch.setattr(smoke, "run_once", forbidden_provider)
    if key is None:
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENCODE_API_KEY", key)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "arena",
            "live-smoke",
            "--config",
            str(CONFIG_PATH),
            "--rounds",
            str(rounds),
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"error_code": error_code}
    assert calls == {"market_client": 0, "provider": 0}
    assert "smoke-test-key" not in output.out


def test_live_smoke_unexpected_failure_hides_exception_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_smoke(*args: Any, **kwargs: Any) -> object:
        raise RuntimeError("provider response and credential secret")

    monkeypatch.setattr(smoke, "run_live_smoke", fail_smoke)
    monkeypatch.setattr(
        sys,
        "argv",
        ["arena", "live-smoke", "--config", str(CONFIG_PATH), "--rounds", "1"],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"error_code": "SMOKE_INTERNAL_ERROR"}
    assert "provider response" not in output.out
    assert "credential secret" not in output.out
