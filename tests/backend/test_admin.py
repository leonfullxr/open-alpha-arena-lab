from __future__ import annotations

import os
import uuid

import pytest
from app.db.models import Account, AgentRun, PromptVersion, ProviderProfile
from app.services.admin import (
    AdminInputError,
    create_competition,
    create_prompt_version,
    create_provider_profile,
    validate_competition_start,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = DATABASE_URL if DATABASE_URL and DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")


def test_admin_profiles_freeze_rules_and_never_store_provider_secret(monkeypatch) -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    suffix = uuid.uuid4().hex[:10]
    with Session(engine, expire_on_commit=False) as db:
        provider = create_provider_profile(
            db,
            {
                "name": f"test-provider-{suffix}",
                "version": 1,
                "adapter": "opencode_go",
                "model": "mimo-v2.6-flash",
                "api_key_env": f"ARENA_TEST_SECRET_{suffix.upper()}",
                "input_cost_per_million": "1",
                "output_cost_per_million": "1",
                "max_cost_per_request_usd": "0.01",
                "max_input_body_bytes": 1000,
                "max_output_tokens": 100,
                "temperature": "0",
            },
        )
        prompt = create_prompt_version(
            db, name=f"prompt-{suffix}", version=1, template="Use only the given data."
        )
        competition = create_competition(
            db,
            {
                "name": f"Admin lifecycle {suffix}",
                "profile": "alpha_2025_baseline",
                "initial_balance": "10000",
                "inference_budget_usd": "1",
                "agents": [
                    {
                        "name": "Test Atlas",
                        "provider_profile_id": provider.id,
                        "prompt_version_id": prompt.id,
                    }
                ],
            },
        )
        assert competition.state == "DRAFT"
        assert competition.rules_sha256
        assert b'"inference_budget_usd":"1"' in competition.rules_bytes
        agent = db.scalar(select(AgentRun).where(AgentRun.competition_id == competition.id))
        assert agent is not None
        assert agent.provider_profile_id == provider.id
        assert agent.api_key_env == provider.api_key_env
        account = db.scalar(select(Account).where(Account.agent_run_id == agent.id))
        assert account is not None and str(account.cash) == "10000.000000000000000000"
        assert "secret-canary-not-persisted" not in repr(provider.__dict__)
        with pytest.raises(AdminInputError, match="credential is not configured"):
            validate_competition_start(db, competition)
        monkeypatch.setenv(provider.api_key_env, "secret-canary-not-persisted")
        validate_competition_start(db, competition)
        stored = db.get(ProviderProfile, provider.id)
        assert stored is not None
        assert "secret-canary-not-persisted" not in str(stored.api_key_env)
        assert db.get(PromptVersion, prompt.id) is not None
    engine.dispose()


def test_provider_profile_rejects_unapproved_endpoint_and_underbudgeted_cap() -> None:
    assert PG_URL is not None
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with Session(engine) as db:
        base = {
            "name": f"invalid-{uuid.uuid4().hex}",
            "adapter": "custom_url",
            "model": "m",
            "api_key_env": "PROVIDER_KEY",
            "input_cost_per_million": "1",
            "output_cost_per_million": "1",
            "max_cost_per_request_usd": "1",
            "max_output_tokens": 10,
        }
        with pytest.raises(AdminInputError, match="adapter is not approved"):
            create_provider_profile(db, base)
        base["adapter"] = "openai_chat"
        base["max_cost_per_request_usd"] = "0.000001"
        with pytest.raises(AdminInputError, match="below the configured worst-case"):
            create_provider_profile(db, base)
    engine.dispose()
