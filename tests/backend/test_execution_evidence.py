from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from app.api.public_rules import serialize_rules
from app.core.canonical import canonical_json_bytes, sha256_hex
from app.core.rules import canonical_profile
from app.db.models import (
    Account,
    AgentRun,
    Competition,
    DecisionRound,
    DomainEvent,
    EquitySample,
    Fill,
    InvocationAttempt,
    MarketQuote,
    MarketSnapshot,
    Order,
    Position,
    PromptVersion,
    QuoteSet,
    RoundAgentJob,
    TradeProposal,
)
from app.db.session import get_db
from app.main import public_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
PG_URL = _DATABASE_URL if _DATABASE_URL and _DATABASE_URL.startswith("postgresql") else None
pytestmark = pytest.mark.skipif(PG_URL is None, reason="TEST_DATABASE_URL is not configured")


def _migrated_schema(monkeypatch: pytest.MonkeyPatch) -> tuple[str, object, object]:
    assert PG_URL is not None
    schema = f"execution_evidence_{uuid.uuid4().hex}"
    admin_engine = create_engine(PG_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    # PGOPTIONS avoids putting connection parameters in the URL; psycopg's URL
    # query encoding for libpq's options has portability/authentication issues.
    monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    command.upgrade(Config("services/api/alembic.ini"), "head")
    engine = create_engine(PG_URL, pool_pre_ping=True)
    return schema, admin_engine, engine


def test_public_trade_linkage_rules_export_and_append_only_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema, admin_engine, engine = _migrated_schema(monkeypatch)
    competition_id = str(uuid.uuid4())
    agent_id, account_id = str(uuid.uuid4()), str(uuid.uuid4())
    prompt_id = str(uuid.uuid4())
    snapshot_id, quote_set_id = str(uuid.uuid4()), str(uuid.uuid4())
    round_id, job_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    market_order_id, legacy_order_id = str(uuid.uuid4()), str(uuid.uuid4())
    market_fill_id, legacy_fill_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    rules = {
        **canonical_profile("alpha_2025_baseline"),
        "inference_budget_usd": "2.50",
    }
    rules_bytes = canonical_json_bytes(rules)
    with Session(engine) as db:
        db.add(
            Competition(
                id=competition_id,
                name="Evidence audit",
                profile="alpha_2025_baseline",
                rules_bytes=rules_bytes,
                rules_sha256=sha256_hex(rules_bytes),
                initial_balance=Decimal("10000"),
                state="FINISHED",
                source_label="LIVE DATA · PAPER",
                started_at=now - timedelta(minutes=10),
                ended_at=now,
                event_seq=8,
            )
        )
        db.add(
            PromptVersion(
                id=prompt_id,
                name=f"execution-evidence-{uuid.uuid4().hex}",
                version=1,
                template_bytes=b"safe prompt",
                sha256=hashlib.sha256(b"safe prompt").hexdigest(),
            )
        )
        db.flush()
        db.add(
            AgentRun(
                id=agent_id,
                competition_id=competition_id,
                manifest_order=0,
                name="Audit Agent",
                provider="MockLLMAdapter",
                model="audit-model",
                model_settings_bytes=b"{}",
                settings_sha256="a" * 64,
                prompt_version_id=prompt_id,
                status="ACTIVE",
            )
        )
        db.flush()
        db.add(
            Account(
                id=account_id,
                agent_run_id=agent_id,
                cash=Decimal("10000"),
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
                reserved_margin=Decimal("0"),
                halted=False,
                version=0,
            )
        )
        db.add(
            EquitySample(
                id=str(uuid.uuid4()),
                account_id=account_id,
                round_index=12,
                logical_at=now,
                equity=Decimal("10000"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                fees=Decimal("0"),
                funding=Decimal("0"),
            )
        )
        quote_bytes = canonical_json_bytes(
            {"quotes": {"BTC": {"bid": "99", "ask": "100", "mark": "99.5"}}}
        )
        db.add(
            QuoteSet(
                id=quote_set_id,
                source="hyperliquid",
                captured_at=now,
                complete=True,
                max_age_ms=100,
                skew_ms=0,
            )
        )
        db.flush()
        db.add_all(
            [
                MarketQuote(
                    quote_set_id=quote_set_id,
                    symbol="BTC",
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    mark=Decimal("99.5"),
                    funding_rate=None,
                    open_interest=None,
                    oracle_px=None,
                    source_at=now,
                    received_at=now,
                    context_received_at=now,
                    source_at_basis="hyperliquid_l2_book_time",
                ),
                MarketSnapshot(
                    id=snapshot_id,
                    canonical_bytes=quote_bytes,
                    sha256=sha256_hex(quote_bytes),
                    source_label="hyperliquid",
                    captured_at=now,
                    quote_set_id=quote_set_id,
                ),
            ]
        )
        db.flush()
        db.add(
            DecisionRound(
                id=round_id,
                competition_id=competition_id,
                round_index=12,
                logical_at=now,
                snapshot_id=snapshot_id,
                execution_quote_set_id=quote_set_id,
                deadline_at=now,
            )
        )
        db.flush()
        db.add(
            RoundAgentJob(
                id=job_id,
                round_id=round_id,
                agent_run_id=agent_id,
                state="RESPONDED",
                fence=1,
            )
        )
        db.flush()
        db.add(
            InvocationAttempt(
                id=attempt_id,
                job_id=job_id,
                prompt_bytes=b"safe prompt",
                prompt_sha256=hashlib.sha256(b"safe prompt").hexdigest(),
                provider="MockLLMAdapter",
                model="audit-model",
                public_parameters={},
                dispatched_at=now,
                fence=1,
            )
        )
        db.add(
            TradeProposal(
                id=proposal_id,
                job_id=job_id,
                sequence=0,
                action="OPEN_LONG",
                symbol="BTC",
                quantity=Decimal("0.1"),
                raw_bytes=b"{}",
            )
        )
        db.flush()
        db.add_all(
            [
                Order(
                    id=market_order_id,
                    account_id=account_id,
                    proposal_id=proposal_id,
                    idempotency_key=f"evidence-market:{uuid.uuid4()}",
                    kind="MARKET",
                    status="FILLED",
                    event_sequence=8,
                    quote_set_id=quote_set_id,
                ),
                Order(
                    id=legacy_order_id,
                    account_id=account_id,
                    proposal_id=None,
                    idempotency_key=f"evidence-legacy:{uuid.uuid4()}",
                    kind="PROTECTIVE_EXIT",
                    status="FILLED",
                    event_sequence=None,
                    quote_set_id=None,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                Fill(
                    id=market_fill_id,
                    order_id=market_order_id,
                    symbol="BTC",
                    side="BUY",
                    quantity=Decimal("0.1"),
                    price=Decimal("100.020000000000000000"),
                    fee=Decimal("0.005"),
                    executed_at=now,
                    ordinal=0,
                ),
                Fill(
                    id=legacy_fill_id,
                    order_id=legacy_order_id,
                    symbol="BTC",
                    side="SELL",
                    quantity=Decimal("0.1"),
                    price=Decimal("99"),
                    fee=Decimal("0.005"),
                    executed_at=None,
                    ordinal=None,
                ),
                Position(
                    id=str(uuid.uuid4()),
                    account_id=account_id,
                    symbol="BTC",
                    side="LONG",
                    quantity=Decimal("0.1"),
                    average_entry=Decimal("100"),
                    reserved_margin=Decimal("2"),
                    stop_loss=None,
                    take_profit=None,
                    state="CLOSED",
                    opened_at=now - timedelta(minutes=3),
                    closed_at=now - timedelta(minutes=1),
                ),
                DomainEvent(
                    id=str(uuid.uuid4()),
                    competition_id=competition_id,
                    sequence=8,
                    account_id=account_id,
                    event_type="agent.decision",
                    payload={"round": 12},
                    event_at=now,
                ),
            ]
        )
        db.commit()

    def test_session():
        with Session(engine) as db:
            yield db

    public_app.dependency_overrides[get_db] = test_session
    try:
        with TestClient(public_app) as client:
            root = f"/competitions/{competition_id}"
            trade_response = client.get(f"{root}/trades?limit=10")
            assert trade_response.status_code == 200, trade_response.text
            trades = trade_response.json()["items"]
            assert [row["fill_id"] for row in trades] == [legacy_fill_id, market_fill_id]
            legacy = trades[0]
            assert legacy["executed_at"] is None and legacy["event_sequence"] is None
            assert legacy["fill_ordinal"] is None and legacy["quote_set_id"] is None
            trade = trades[1]
            assert trade["decision_id"] == attempt_id
            assert trade["proposal_sequence"] == 0 and trade["round"] == 12
            assert trade["event_sequence"] == 8 and trade["fill_ordinal"] == 0
            assert trade["quote_set_id"] == quote_set_id
            assert trade["execution_quote"] == {
                "bid": "99.000000000000000000",
                "ask": "100.000000000000000000",
                "mark": "99.500000000000000000",
                "source_at": now.isoformat(),
                "source_at_basis": "hyperliquid_l2_book_time",
            }
            rules_response = client.get(f"{root}/rules")
            assert rules_response.status_code == 200, rules_response.text
            rules_body = rules_response.json()
            assert rules_body["sha256"] == sha256_hex(rules_bytes)
            assert base64.b64decode(rules_body["bytes_base64"]) == rules_bytes
            assert rules_body["public"]["inference_budget_usd"] == "2.50"
            assert rules_body["public"]["indicator_policy"] == "trailing_500_v1"
            assert rules_body["public"]["indicator_warmup_bars"] == 500
            assert rules_body["withheld_fields"] is False
            unsupported_rules = {**rules, "indicator_warmup_bars": 501}
            unsupported_bytes = canonical_json_bytes(unsupported_rules)
            with pytest.raises(ValueError, match="unsupported indicator warmup"):
                serialize_rules(
                    Competition(
                        id=competition_id,
                        name="Unsupported policy",
                        profile="alpha_2025_baseline",
                        rules_bytes=unsupported_bytes,
                        rules_sha256=sha256_hex(unsupported_bytes),
                        initial_balance=Decimal("10000"),
                        state="FINISHED",
                        source_label="LIVE DATA · PAPER",
                        event_seq=0,
                    )
                )
            canary_bytes = canonical_json_bytes({**rules, "private_canary": "RULE_SECRET"})
            canary_competition = Competition(
                id=competition_id,
                name="Canary rules",
                profile="alpha_2025_baseline",
                rules_bytes=canary_bytes,
                rules_sha256=sha256_hex(canary_bytes),
                initial_balance=Decimal("10000"),
                state="FINISHED",
                source_label="LIVE DATA · PAPER",
                event_seq=0,
            )
            canary_artifact = serialize_rules(canary_competition)
            assert canary_artifact.withheld_fields is True
            assert canary_artifact.bytes_withheld is True
            assert canary_artifact.bytes_base64 is None
            writer_engine = create_engine(
                PG_URL,
                pool_pre_ping=True,
                connect_args={"options": f"-csearch_path={schema}"},
            )
            injected = False

            def concurrent_writer(
                connection: Connection,
                cursor: object,
                statement: str,
                parameters: object,
                context: object,
                executemany: bool,
            ) -> None:
                nonlocal injected
                if injected or "from competitions" not in statement.lower():
                    return
                injected = True
                assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
                with Session(writer_engine) as writer:
                    writer.add(
                        EquitySample(
                            id=str(uuid.uuid4()),
                            account_id=account_id,
                            round_index=13,
                            logical_at=now,
                            equity=Decimal("10001"),
                            realized_pnl=Decimal("1"),
                            unrealized_pnl=Decimal("0"),
                            fees=Decimal("0"),
                            funding=Decimal("0"),
                        )
                    )
                    writer.commit()

            event.listen(engine, "after_cursor_execute", concurrent_writer)
            try:
                export_response = client.get(f"{root}/export?limit=1")
            finally:
                event.remove(engine, "after_cursor_execute", concurrent_writer)
                writer_engine.dispose()
            assert injected is True
            assert export_response.status_code == 200, export_response.text
            export = export_response.json()
            assert export["rules"] == rules_body
            assert export["total_trades"] == 2 and export["exported_trades"] == 1
            assert export["truncated_trades"] is True and export["truncated"] is True
            assert export["total_positions"] == 1 and export["exported_positions"] == 1
            assert export["total_equity_points"] == 1
            assert export["exported_equity_points"] == 1
            assert export["truncated_equity"] is False
            assert len(export["equity"]) == 1
            with Session(engine) as verify:
                assert verify.scalar(
                    select(func.count()).select_from(EquitySample).where(
                        EquitySample.account_id == account_id
                    )
                ) == 2
            positions = client.get(f"{root}/positions?include_closed=true").json()["items"]
            assert positions[0]["closed_at"] is not None
            assert client.post(f"{root}/rules").status_code == 405

    finally:
        public_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_round_quote_pin_is_write_once_but_round_and_order_rows_stay_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema, admin_engine, engine = _migrated_schema(monkeypatch)
    try:
        with Session(engine) as db:
            competition_id = str(uuid.uuid4())
            agent_id, prompt_id, account_id = (
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )
            quote_set_id, snapshot_id = str(uuid.uuid4()), str(uuid.uuid4())
            alternate_quote_set_id = str(uuid.uuid4())
            round_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            rules_bytes = canonical_json_bytes(canonical_profile("alpha_2025_baseline"))
            db.add(
                Competition(
                    id=competition_id,
                    name="Pin trigger test",
                    profile="alpha_2025_baseline",
                    rules_bytes=rules_bytes,
                    rules_sha256=sha256_hex(rules_bytes),
                    initial_balance=Decimal("10000"),
                    state="RUNNING",
                    source_label="LIVE DATA · PAPER",
                    started_at=now,
                    event_seq=0,
                )
            )
            db.add(
                PromptVersion(
                    id=prompt_id,
                    name=f"pin-{uuid.uuid4().hex}",
                    version=1,
                    template_bytes=b"x",
                    sha256=hashlib.sha256(b"x").hexdigest(),
                )
            )
            db.flush()
            db.add(
                AgentRun(
                    id=agent_id,
                    competition_id=competition_id,
                    manifest_order=0,
                    name="Pin Agent",
                    provider="MockLLMAdapter",
                    model="pin",
                    model_settings_bytes=b"{}",
                    settings_sha256="b" * 64,
                    prompt_version_id=prompt_id,
                    status="ACTIVE",
                )
            )
            db.flush()
            db.add(
                Account(
                    id=account_id,
                    agent_run_id=agent_id,
                    cash=Decimal("10000"),
                    realized_pnl=0,
                    fees=0,
                    funding=0,
                    reserved_margin=0,
                    halted=False,
                    version=0,
                )
            )
            raw = canonical_json_bytes({})
            db.add(
                QuoteSet(
                    id=quote_set_id,
                    source="hyperliquid",
                    captured_at=now,
                    complete=True,
                    max_age_ms=10,
                    skew_ms=0,
                )
            )
            db.add(
                QuoteSet(
                    id=alternate_quote_set_id,
                    source="hyperliquid",
                    captured_at=now,
                    complete=True,
                    max_age_ms=10,
                    skew_ms=0,
                )
            )
            db.flush()
            db.add(
                MarketSnapshot(
                    id=snapshot_id,
                    canonical_bytes=raw,
                    sha256=sha256_hex(raw),
                    source_label="hyperliquid",
                    captured_at=now,
                    quote_set_id=quote_set_id,
                )
            )
            db.flush()
            round_row = DecisionRound(
                id=round_id,
                competition_id=competition_id,
                round_index=0,
                logical_at=now,
                snapshot_id=snapshot_id,
                execution_quote_set_id=None,
                deadline_at=now,
            )
            db.add(round_row)
            db.flush()
            order = Order(
                id=str(uuid.uuid4()),
                account_id=account_id,
                proposal_id=None,
                idempotency_key=f"append-only:{uuid.uuid4()}",
                kind="PROTECTIVE_EXIT",
                status="FILLED",
                event_sequence=1,
                quote_set_id=quote_set_id,
            )
            db.add(order)
            db.flush()
            immutable_order_id = order.id
            round_row.execution_quote_set_id = quote_set_id
            db.commit()

        def update_rejected(statement: str, params: dict[str, object]) -> None:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(statement), params)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE decision_rounds SET execution_quote_set_id = :quote_set "
                    "WHERE id = :round_id"
                ),
                {"quote_set": quote_set_id, "round_id": round_id},
            )
        update_rejected(
            "UPDATE decision_rounds SET execution_quote_set_id = NULL WHERE id = :round_id",
            {"round_id": round_id},
        )
        update_rejected(
            "UPDATE decision_rounds SET execution_quote_set_id = :quote_set WHERE id = :round_id",
            {"quote_set": alternate_quote_set_id, "round_id": round_id},
        )
        update_rejected(
            "UPDATE decision_rounds SET logical_at = :logical_at WHERE id = :round_id",
            {"logical_at": now + timedelta(seconds=1), "round_id": round_id},
        )
        update_rejected(
            "UPDATE decision_rounds SET snapshot_id = :snapshot_id WHERE id = :round_id",
            {"snapshot_id": str(uuid.uuid4()), "round_id": round_id},
        )
        update_rejected(
            "DELETE FROM decision_rounds WHERE id = :round_id", {"round_id": round_id}
        )
        update_rejected(
            "UPDATE orders SET event_sequence = 2 WHERE id = :order_id",
            {"order_id": immutable_order_id},
        )
        with Session(engine) as db:
            assert (
                db.scalar(select(Order.id).where(Order.id == immutable_order_id))
                == immutable_order_id
            )
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()
