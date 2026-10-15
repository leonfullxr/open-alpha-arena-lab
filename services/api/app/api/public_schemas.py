from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ItemT = TypeVar("ItemT")


class PageDTO[ItemT](PublicModel):
    items: list[ItemT]
    limit: int
    offset: int
    total: int


class StatusDTO(PublicModel):
    state: str
    demo_label: str
    competition_count: int
    schema_version: int


class TickerItem(PublicModel):
    symbol: str
    bid: str
    ask: str
    mark: str
    source: str
    event_at: str
    received_at: str
    age_seconds: str
    stale: bool


class AgentSummary(PublicModel):
    id: str
    name: str
    provider: str
    model: str


class CompetitionSummary(PublicModel):
    id: str
    name: str
    profile: str
    state: str
    source_label: str
    initial_balance: str
    started_at: str | None
    ended_at: str | None
    agents: list[AgentSummary]


class EquityPoint(PublicModel):
    agent_id: str
    agent_name: str
    round: int
    timestamp: str
    equity: str
    realized_pnl: str
    unrealized_pnl: str
    fees: str
    funding: str


class EquityChartDTO(PublicModel):
    range: str
    points: int
    total_raw: int
    sampled: bool
    items: list[EquityPoint]


class LeaderboardRow(PublicModel):
    rank: int
    agent_id: str
    agent_name: str
    model: str
    equity: str
    roi_pct: str
    realized_pnl: str
    unrealized_pnl: str
    fees: str
    funding: str
    trade_count: int


class PublicEventPayload(PublicModel):
    agent_id: str | None = None
    round: int | None = None
    action: str | None = None
    source: str | None = None
    symbol: str | None = None
    quantity: str | None = None
    price: str | None = None
    fee: str | None = None
    reason: str | None = None


class EventDTO(PublicModel):
    sequence: int
    event_type: str
    event_at: str
    agent_id: str | None
    payload: PublicEventPayload


class EventPageDTO(PublicModel):
    items: list[EventDTO]
    after: int
    next_after: int
    has_more: bool


def public_event_payload(value: dict[str, Any]) -> PublicEventPayload:
    allowed = {
        "agent_id",
        "round",
        "action",
        "source",
        "symbol",
        "quantity",
        "price",
        "fee",
        "reason",
    }
    return PublicEventPayload.model_validate(
        {key: item for key, item in value.items() if key in allowed}
    )


class ProposalEvidenceDTO(PublicModel):
    action: str
    symbol: str
    quantity: str
    leverage: str | None
    stop_loss: str | None
    take_profit: str | None
    confidence: str | None
    invalidation: str | None
    justification: str
    risk_decision: str | None
    risk_reasons: list[str]


class DecisionDTO(PublicModel):
    id: str
    agent_id: str
    agent_name: str
    round: int
    action: str | None
    symbol: str | None
    quantity: str | None
    justification: str | None
    market_summary: str | None
    proposals: list[ProposalEvidenceDTO]
    validation_status: str
    validation_errors: list[str]
    prompt_sha256: str | None
    output_sha256: str | None
    artifact_url: str | None
    provider: str
    model: str
    error_code: str | None = None
    latency_ms: int | None = None
    estimated_cost_usd: str | None = None
    usage: dict[str, int]
    execution_result: str | None = None


class PositionDTO(PublicModel):
    agent_id: str
    agent_name: str
    symbol: str
    side: str
    quantity: str
    average_entry: str
    reserved_margin: str
    stop_loss: str | None
    take_profit: str | None
    state: str


class TradeDTO(PublicModel):
    agent_id: str
    agent_name: str
    symbol: str
    side: str
    quantity: str
    price: str
    fee: str
    order_id: str
    status: str


class ModelDTO(PublicModel):
    id: str
    name: str
    provider: str
    model: str
    status: str
    source_label: str
    credential_reference_configured: bool
    competition_id: str
    profile: str
    settings_sha256: str
    prompt_sha256: str
    public_settings: dict[str, str | int]


class ExportDTO(PublicModel):
    competition: CompetitionSummary
    leaderboard: list[LeaderboardRow]
    equity: list[EquityPoint]
    decisions: list[DecisionDTO]
    truncated: bool
    exported_decisions: int
    exported_equity_points: int


class ArtifactDTO(PublicModel):
    id: str
    prompt_sha256: str
    output_sha256: str
    prompt_bytes_base64: str
    output_bytes_base64: str
    output_publicly_releasable: bool


class AgentMetricsDTO(PublicModel):
    agent_id: str
    win_rate_pct: str | None
    profit_factor: str | None
    max_drawdown_pct: str | None
    sharpe_ratio: str | None
    average_leverage: str | None
    current_margin_used: str
    current_gross_exposure: str | None
    closed_trades: int
    winning_trades: int
    losing_trades: int


class BenchmarkDTO(PublicModel):
    symbol: str
    label: str
    start_at: str
    end_at: str
    start_price: str
    end_price: str
    equity: str
    roi_pct: str
    fee_rate: str
    slippage_bps: str
    method: str


class CompetitionMetricsDTO(PublicModel):
    competition_id: str
    agents: list[AgentMetricsDTO]
    benchmark: BenchmarkDTO | None
