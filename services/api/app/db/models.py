from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


MONEY = Numeric(38, 18, asdecimal=True)


class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    profile: Mapped[str] = mapped_column(String(80), nullable=False)
    rules_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rules_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="FINISHED")
    source_label: Mapped[str] = mapped_column(String(120), nullable=False, default="DEMO REPLAY")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    __table_args__ = (CheckConstraint("state in ('DRAFT','RUNNING','PAUSED','FINISHED')"),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("name", "version"),)


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(300), nullable=False)
    api_key_env: Mapped[str] = mapped_column(String(80), nullable=False)
    input_cost_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    output_cost_per_million: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_cost_per_request_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_input_body_bytes: Mapped[int] = mapped_column("max_input_bytes", Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(8, 4, asdecimal=True), nullable=False)
    settings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("version > 0"),
        CheckConstraint("input_cost_per_million > 0"),
        CheckConstraint("output_cost_per_million > 0"),
        CheckConstraint("max_input_bytes between 1 and 250000"),
        CheckConstraint("max_output_tokens between 1 and 2000"),
        CheckConstraint("temperature between 0 and 2"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competitions.id"), nullable=False, index=True
    )
    manifest_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_profile_id: Mapped[str | None] = mapped_column(ForeignKey("provider_profiles.id"))
    model_settings_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    settings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id"), nullable=False)
    api_key_env: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    __table_args__ = (UniqueConstraint("competition_id", "manifest_order"),)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=False, unique=True
    )
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    funding: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    reserved_margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    halted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    peak_equity: Mapped[Decimal | None] = mapped_column(MONEY)
    daily_baseline_equity: Mapped[Decimal | None] = mapped_column(MONEY)
    risk_day: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_label: Mapped[str] = mapped_column(String(120), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quote_set_id: Mapped[str] = mapped_column(ForeignKey("quote_sets.id"), nullable=False)


class DecisionRound(Base):
    __tablename__ = "decision_rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    competition_id: Mapped[str] = mapped_column(ForeignKey("competitions.id"), nullable=False)
    round_index: Mapped[int] = mapped_column(Integer, nullable=False)
    logical_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("market_snapshots.id"), nullable=False)
    execution_quote_set_id: Mapped[str | None] = mapped_column(ForeignKey("quote_sets.id"))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("competition_id", "round_index"),)


class QuoteSet(Base):
    __tablename__ = "quote_sets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_age_ms: Mapped[int | None] = mapped_column(Integer)
    skew_ms: Mapped[int | None] = mapped_column(Integer)


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    quote_set_id: Mapped[str] = mapped_column(ForeignKey("quote_sets.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    bid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ask: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mark: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    funding_rate: Mapped[Decimal | None] = mapped_column(MONEY)
    open_interest: Mapped[Decimal | None] = mapped_column(MONEY)
    oracle_px: Mapped[Decimal | None] = mapped_column(MONEY)
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_at_basis: Mapped[str] = mapped_column(String(60), nullable=False)


class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    volume: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ema20: Mapped[Decimal | None] = mapped_column(MONEY)
    rsi7: Mapped[Decimal | None] = mapped_column(MONEY)
    macd: Mapped[Decimal | None] = mapped_column(MONEY)
    macd_signal: Mapped[Decimal | None] = mapped_column(MONEY)
    macd_histogram: Mapped[Decimal | None] = mapped_column(MONEY)
    __table_args__ = (UniqueConstraint("source", "symbol", "interval", "open_at"),)


class RoundAgentJob(Base):
    __tablename__ = "round_agent_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("decision_rounds.id"), nullable=False)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    terminal_result: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(80))
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("round_id", "agent_run_id"),
        CheckConstraint("(state = 'TERMINAL') = (terminal_result is not null)"),
    )


class DailyBudget(Base):
    __tablename__ = "daily_budgets"
    budget_date: Mapped[date] = mapped_column(Date, primary_key=True)
    cap_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserved_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("cap_usd > 0"),
        CheckConstraint("reserved_usd >= 0"),
        CheckConstraint("reserved_usd <= cap_usd"),
    )


class SpendReservation(Base):
    __tablename__ = "spend_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("round_agent_jobs.id"), nullable=False, unique=True
    )
    competition_id: Mapped[str] = mapped_column(ForeignKey("competitions.id"), nullable=False)
    budget_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("amount_usd > 0"),
        Index("ix_spend_reservations_competition_day", "competition_id", "budget_date"),
    )


class InvocationAttempt(Base):
    __tablename__ = "invocation_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("round_agent_jobs.id"), nullable=False, unique=True
    )
    prompt_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    public_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)


class InvocationResult(Base):
    __tablename__ = "invocation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("invocation_attempts.id"), nullable=False, unique=True
    )
    output_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradeProposal(Base):
    __tablename__ = "trade_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("round_agent_jobs.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    raw_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (UniqueConstraint("job_id", "sequence"),)


class RiskEvaluation(Base):
    __tablename__ = "risk_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("trade_proposals.id"), nullable=False, unique=True
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("trade_proposals.id"))
    quote_set_id: Mapped[str | None] = mapped_column(ForeignKey("quote_sets.id"))
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    event_sequence: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (Index("ix_orders_event_sequence", "event_sequence"),)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ordinal: Mapped[int | None] = mapped_column(Integer)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    average_entry: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reserved_margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    stop_loss: Mapped[Decimal | None] = mapped_column(MONEY)
    take_profit: Mapped[Decimal | None] = mapped_column(MONEY)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("(state = 'CLOSED') = (closed_at is not null)"),
        Index(
            "uq_positions_open_account_symbol",
            "account_id",
            "symbol",
            unique=True,
            postgresql_where=text("state = 'OPEN'"),
            sqlite_where=text("state = 'OPEN'"),
        ),
    )


class ProtectiveOrder(Base):
    __tablename__ = "protective_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)


class LedgerJournal(Base):
    __tablename__ = "ledger_journals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerPosting(Base):
    __tablename__ = "ledger_postings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    journal_id: Mapped[str] = mapped_column(ForeignKey("ledger_journals.id"), nullable=False)
    bucket: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    __table_args__ = (Index("ix_postings_journal", "journal_id"),)


class FundingPayment(Base):
    __tablename__ = "funding_payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    rate: Mapped[Decimal | None] = mapped_column(MONEY)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    oracle_px: Mapped[Decimal | None] = mapped_column(MONEY)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("funding_rate_evidence.id"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="PAID")
    reason: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        UniqueConstraint("position_id", "event_at"),
        CheckConstraint("status in ('PAID','SKIPPED')"),
        CheckConstraint("(status = 'PAID') = (amount is not null)"),
        CheckConstraint("status != 'PAID' or rate is not null"),
    )


class FundingBoundaryTask(Base):
    __tablename__ = "funding_boundary_tasks"
    boundary_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CAPTURE_PENDING")
    expected_symbols: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    oracle_quote_set_id: Mapped[str | None] = mapped_column(ForeignKey("quote_sets.id"))
    oracle_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("market_snapshots.id"))
    context_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capture_owner: Mapped[str | None] = mapped_column(String(80))
    capture_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    poll_owner: Mapped[str | None] = mapped_column(String(80))
    poll_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status in ('CAPTURE_PENDING','PENDING','READY','UNAVAILABLE')"),
    )


class FundingRateEvidence(Base):
    __tablename__ = "funding_rate_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    boundary_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    rate: Mapped[Decimal | None] = mapped_column(MONEY)
    history_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_record_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    sha256: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("symbol", "boundary_at"),
        CheckConstraint("status in ('READY','UNAVAILABLE')"),
        CheckConstraint(
            "(status = 'READY') = (rate is not null and history_event_at is not null "
            "and raw_record_bytes is not null and sha256 is not null)"
        ),
    )


class EquitySample(Base):
    __tablename__ = "equity_samples"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    round_index: Mapped[int] = mapped_column(Integer, nullable=False)
    logical_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    funding: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    __table_args__ = (UniqueConstraint("account_id", "round_index"),)


class DomainEvent(Base):
    __tablename__ = "domain_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    competition_id: Mapped[str] = mapped_column(ForeignKey("competitions.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("competition_id", "sequence"),)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("role in ('admin','viewer')"),)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    abs_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(180))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
