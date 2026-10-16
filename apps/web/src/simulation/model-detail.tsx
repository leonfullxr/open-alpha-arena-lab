import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ActivityPanel } from './activity';
import {
  getCompetitionMetrics,
  getCompetitions,
  getDecisionHistory,
  getEquityChart,
  getLeaderboard,
  getModel,
  getPositionHistory,
  getTradeHistory,
  type EquityRange,
  type Position,
  type Trade,
} from './api';
import { modelMarker, modelToneClass } from './colors';
import { EquityChart } from './equity-chart';
import { decimal, money, percent, QueryState, timestamp } from './ui';

const OVERVIEW_LIMIT = 100;
const POSITION_PAGE_SIZE = 200;
const TRADE_PREVIEW_LIMIT = 25;

export function ModelDetailPage(): React.JSX.Element {
  const { competitionId = '', agentId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const highlightDecisionId = searchParams.get('decision') ?? undefined;
  const requestedRound = Number(searchParams.get('round'));
  const decisionRound = Number.isSafeInteger(requestedRound) && requestedRound > 0 ? requestedRound : undefined;
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const modelQuery = useQuery({ queryKey: ['model', agentId], queryFn: () => getModel(agentId), enabled: Boolean(agentId) });
  const competitionsQuery = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const model = modelQuery.data;
  const competition = competitionsQuery.data?.find((item) => item.id === competitionId && item.id === model?.competition_id);
  const rowQuery = useQuery({
    queryKey: ['competition', competitionId, 'leaderboard'],
    queryFn: () => getLeaderboard(competitionId),
    enabled: Boolean(competition),
  });
  const metricsQuery = useQuery({
    queryKey: ['competition', competitionId, 'metrics'],
    queryFn: () => getCompetitionMetrics(competitionId),
    enabled: Boolean(competition),
  });
  const equity = useQuery({
    queryKey: ['competition', competitionId, 'chart', chartRange],
    queryFn: () => getEquityChart(competitionId, chartRange),
    enabled: Boolean(competition),
  });
  const positionsQuery = useQuery({
    queryKey: ['competition', competitionId, 'positions', agentId, 'model-overview'],
    queryFn: () => getAllPositions({ competitionId, agentId }),
    enabled: Boolean(competition && agentId),
  });
  const fillsQuery = useQuery({
    queryKey: ['competition', competitionId, 'trades', agentId, 'last-25-fills'],
    queryFn: () => getLastTrades({ competitionId, agentId }),
    enabled: Boolean(competition && agentId),
  });
  const decisionsQuery = useQuery({
    queryKey: ['competition', competitionId, 'decisions', agentId, 'confidence-overview'],
    queryFn: () => getDecisionHistory(competitionId, { limit: OVERVIEW_LIMIT, offset: 0, agent_id: agentId }),
    enabled: Boolean(competition && agentId),
  });

  if ((modelQuery.isLoading && !modelQuery.data) || (competitionsQuery.isLoading && !competitionsQuery.data)) {
    return <div className="md-page"><QueryState loading /></div>;
  }
  if ((modelQuery.error && !modelQuery.data) || (competitionsQuery.error && !competitionsQuery.data)) {
    return <div className="md-page"><QueryState error={modelQuery.error ?? competitionsQuery.error} retry={() => void (modelQuery.isError ? modelQuery.refetch() : competitionsQuery.refetch())} /></div>;
  }
  if (!model) return <div className="md-page"><QueryState empty="This model account was not returned by the public API." /></div>;
  if (!competition) {
    return <div className="md-page">
      <nav className="md-backlinks" aria-label="Model navigation"><Link to={`/simulation/${encodeURIComponent(competitionId)}/leaderboard`}>← LEADERBOARD</Link></nav>
      <div className="md-state" role="alert">The requested model and competition do not match. This route keeps the supplied account ID; the model belongs to {model.competition_id}.</div>
    </div>;
  }

  const agent = competition.agents.find((item) => item.id === agentId);
  const row = rowQuery.data?.find((item) => item.agent_id === agentId);
  const metrics = metricsQuery.data?.agents.find((item) => item.agent_id === agentId);
  const toneClass = modelToneClass(competition.agents, model.id);
  const activePositions = (positionsQuery.data?.items ?? []).filter((position) => position.state.toUpperCase() === 'OPEN');
  const decisionPage = decisionsQuery.data;
  const confidenceValues = decisionPage?.items.flatMap((decision) => decision.proposals.flatMap((proposal) => {
    const value = Number(proposal.confidence);
    return proposal.confidence !== null && Number.isFinite(value) ? [value] : [];
  })) ?? [];
  const meanConfidence = confidenceValues.length
    ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length
    : null;
  const startingCapital = Number(competition.initial_balance);
  const equityValue = row ? Number(row.equity) : null;
  const totalPnl = equityValue !== null && Number.isFinite(equityValue) && Number.isFinite(startingCapital)
    ? equityValue - startingCapital
    : null;
  const netRealized = row ? Number(row.realized_pnl) - Number(row.fees) : null;

  return <div className={`md-page ${toneClass}`}>
    <nav className="md-backlinks" aria-label="Model navigation">
      <Link to={`/simulation/${encodeURIComponent(competition.id)}`}>[← LIVE CHART]</Link>
      <Link to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>[▥ LEADERBOARD]</Link>
    </nav>

    <div className="md-account-card">
      <span className="md-profile-badge">{model.profile}</span>
      <header className="md-identity">
        <div className="md-identity-main">
          <span className="md-model-mark" aria-hidden="true">{modelMarker(competition.agents, model.id)}</span>
          <div className="md-identity-copy">
            <h1>{model.name}</h1>
          </div>
        </div>
      </header>

      <div className="md-account-line">
        <span>ACCOUNT VALUE: <strong>{row ? money(row.equity) : 'N/A'}</strong></span>
        <span>CASH: <strong>N/A</strong></span>
      </div>
    </div>

    {rowQuery.error && <div className="md-state md-state--error" role="alert">Account totals could not be loaded. {rowQuery.error.message}<button onClick={() => void rowQuery.refetch()}>Retry totals</button></div>}
    {metricsQuery.error && <div className="md-state md-state--error" role="alert">Account metrics could not be loaded. {metricsQuery.error.message}<button onClick={() => void metricsQuery.refetch()}>Retry metrics</button></div>}
    {!agent && <div className="md-state" role="status">This account ID is not present in the selected competition summary. The public model record remains available.</div>}

    <section className="md-summary" aria-label="Account summary">
      <SummaryMetric label="TOTAL P&L" value={totalPnl === null ? 'N/A' : money(totalPnl)} tone={totalPnl} />
      <SummaryMetric label="TOTAL FEES" value={row ? money(row.fees) : 'N/A'} />
      <SummaryMetric label="NET REALIZED" value={netRealized === null || !Number.isFinite(netRealized) ? 'N/A' : money(netRealized)} tone={netRealized} />
    </section>

    <section className="md-insights" aria-label="Account metrics">
      <div className="md-stat-panel md-performance">
        <Metric label="AVERAGE LEVERAGE:" value={metrics?.average_leverage === null || metrics?.average_leverage === undefined ? 'N/A' : `${decimal(metrics.average_leverage, 2)}×`} />
        <Metric label="AVERAGE CONFIDENCE:" value={meanConfidence === null ? 'N/A' : percent(meanConfidence * 100)} />
        <Metric label="BIGGEST WIN:" value="N/A" />
        <Metric label="BIGGEST LOSS:" value="N/A" />
      </div>
      <div className="md-stat-panel md-hold-times">
        <p className="md-section-kicker">HOLD TIMES</p>
        <Metric label="Long:" value="N/A" />
        <Metric label="Short:" value="N/A" />
        <Metric label="Flat:" value="N/A" />
      </div>
    </section>
    {decisionsQuery.error && <div className="md-state md-state--error" role="alert">Proposal confidence values could not be loaded. {decisionsQuery.error.message}<button onClick={() => void decisionsQuery.refetch()}>Retry decisions</button></div>}

    <section className="md-section" aria-labelledby="md-active-title">
      <div className="md-section-heading"><div><h2 id="md-active-title">ACTIVE POSITIONS</h2></div><div className="md-total-upnl">TOTAL UNREALIZED <strong className={row ? (Number(row.unrealized_pnl) >= 0 ? 'md-positive' : 'md-negative') : ''}>{row ? money(row.unrealized_pnl) : 'N/A'}</strong></div></div>
      {positionsQuery.isLoading ? <div className="md-state" role="status">Loading active positions…</div>
        : positionsQuery.error ? <div className="md-state md-state--error" role="alert">{positionsQuery.error.message}<button onClick={() => void positionsQuery.refetch()}>Retry</button></div>
          : activePositions.length ? <div className="md-position-grid">{activePositions.map((position) => <PositionCard key={position.id} position={position} />)}</div>
            : <div className="md-state">No open position rows were returned for this account.</div>}
      <p className="md-note">Individual unrealized P&amp;L is not published per position; the account total above is reported by the leaderboard API.</p>
      {positionsQuery.data && !positionsQuery.data.complete && <p className="md-note">The public history endpoint limits offsets to 100,000, so this position inventory is incomplete. Browsable position history is below.</p>}
    </section>

    <section className="md-section" aria-labelledby="md-fills-title">
      <div className="md-section-heading"><div><p className="md-eyebrow">{fillsQuery.data?.complete === false ? 'EXACT PUBLIC FILL ROWS · LATEST ACCESSIBLE PAGE' : 'EXACT PUBLIC FILL ROWS · LAST 25'}</p><h2 id="md-fills-title">{fillsQuery.data?.complete === false ? '25 ACCESSIBLE FILLS' : 'LAST 25 FILLS'}</h2></div><span className="md-fill-count">{fillsQuery.data?.total ?? '—'} TOTAL FILLS</span></div>
      {fillsQuery.data && !fillsQuery.data.complete && <p className="md-note">The public history endpoint caps offsets at 100,000; these are the newest fill rows available within that limit.</p>}
      {fillsQuery.isLoading ? <div className="md-state" role="status">Loading fill records…</div>
        : fillsQuery.error ? <div className="md-state md-state--error" role="alert">{fillsQuery.error.message}<button onClick={() => void fillsQuery.refetch()}>Retry</button></div>
          : <FillsTable rows={fillsQuery.data?.items ?? []} />}
    </section>

    <section className="md-section md-chart-section" aria-label="Equity chart">
      <details className="md-disclosure">
        <summary><span>ACCOUNT EQUITY CHART</span><small>Open the recorded chart and range controls</small></summary>
        <QueryState loading={equity.isLoading} error={equity.error} stale={Boolean(equity.data)} retry={() => void equity.refetch()} empty={equity.data?.items.filter((record) => record.agent_id === model.id).length === 0 ? 'No account equity records are available.' : undefined}>
          {equity.data && agent && <EquityChart agents={[agent]} colorAgents={competition.agents} rows={equity.data.items.filter((record) => record.agent_id === model.id)} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} />}
          {equity.data && !agent && <div className="md-state">No competition agent row is available for this account chart.</div>}
        </QueryState>
      </details>
    </section>

    <section className="md-legacy-records" id="model-activity" aria-label="Complete model records">
      <details className="md-disclosure">
        <summary><span>COMPLETE FILL HISTORY</span><small>Server pagination, exact fill evidence, and linked decisions</small></summary>
        <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Live Trades" />
      </details>
      <details className="md-disclosure">
        <summary><span>POSITION AND FUNDING HISTORY</span><small>Open and closed position records, lifecycle, and accounting evidence</small></summary>
        <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Positions" />
      </details>
      <details className="md-disclosure" open={Boolean(highlightDecisionId)}>
        <summary><span>DECISIONS AND ARTIFACTS</span><small>Public decision feed and downloadable artifacts</small></summary>
        <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Model Chat" highlightDecisionId={highlightDecisionId} decisionRound={decisionRound} />
      </details>
      <details className="md-disclosure">
        <summary><span>PUBLIC MODEL SETTINGS AND AUDIT REFERENCES</span><small>Settings, prompt reference, source, and competition timing</small></summary>
        <dl className="md-audit-facts">
          <AuditFact label="Agent ID" value={model.id} />
          <AuditFact label="Provider / model" value={`${model.provider} / ${model.model}`} />
          <AuditFact label="Competition" value={competition.name} />
          <AuditFact label="Source" value={model.source_label} />
          <AuditFact label="Settings SHA-256" value={model.settings_sha256} />
          <AuditFact label="Prompt SHA-256" value={model.prompt_sha256} />
          <AuditFact label="Credential reference configured" value={model.credential_reference_configured ? 'Yes' : 'No'} />
          <AuditFact label="Run window" value={competition.started_at ? `${timestamp(competition.started_at)} → ${competition.ended_at ? timestamp(competition.ended_at) : 'open'}` : 'Not started'} />
          <AuditFact label="Starting capital" value={money(competition.initial_balance)} />
          {Object.entries(model.public_settings).sort(([left], [right]) => left.localeCompare(right)).map(([key, value]) => <AuditFact key={key} label={key.replaceAll('_', ' ')} value={String(value)} />)}
        </dl>
      </details>
      <details className="md-disclosure">
        <summary><span>DATA AVAILABILITY AND METRIC DEFINITIONS</span><small>How this account view treats missing or aggregated data</small></summary>
        <div className="md-method-notes">
          <p>Total P&amp;L is account equity minus competition starting capital, so it includes recorded fees, funding, realized P&amp;L, and unrealized P&amp;L. Net realized is realized P&amp;L less cumulative fees; it excludes funding.</p>
          <p>The public metrics endpoint currently returns no average leverage for this account. Confidence is the mean of recorded proposal confidence values in the first {decisionPage?.items.length ?? 0} of {decisionPage?.total ?? 0} decisions; it is a sample when more than {OVERVIEW_LIMIT} decisions exist. Biggest win, biggest loss, and hold times require completed trade journals that this API does not expose.</p>
          <p>Cash, per-position leverage, liquidation price, and per-position unrealized P&amp;L are not fields in the public model, position, or leaderboard records. Active cards show only recorded entry time, average entry, quantity, exit plan, and reserved margin. Per-trade entry/exit pairs, notionals, holding time, and net P&amp;L cannot be reconstructed safely from unpaired fills.</p>
        </div>
      </details>
    </section>
    <nav className="md-bottom-back" aria-label="Return to leaderboard"><Link to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>[← BACK TO LEADERBOARD]</Link></nav>
  </div>;
}

function SummaryMetric({ label, value, tone }: { label: string; value: string; tone?: number | null }): React.JSX.Element {
  const toneClass = tone === undefined || tone === null ? '' : tone > 0 ? 'md-positive' : tone < 0 ? 'md-negative' : '';
  return <div className="md-summary-metric"><span>{label}</span><strong className={toneClass}>{value}</strong></div>;
}

function Metric({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div className="md-metric"><span>{label}</span><strong>{value}</strong></div>;
}

export function PositionCard({ position }: { position: Position }): React.JSX.Element {
  const side = position.side.toUpperCase();
  const directionClass = side === 'LONG' ? 'md-position--long' : side === 'SHORT' ? 'md-position--short' : '';
  return <article className={`md-position-card ${directionClass}`}>
    <header><div><span className="md-side">{side}</span><h3>{position.symbol}</h3></div><span className="md-position-state">{position.state}</span></header>
    <div className="md-exit-plan"><span>EXIT PLAN</span><details><summary>Stop {position.stop_loss === null ? 'N/A' : money(position.stop_loss)} · Target {position.take_profit === null ? 'N/A' : money(position.take_profit)}</summary><dl><div><dt>Stop loss</dt><dd>{position.stop_loss === null ? 'N/A' : money(position.stop_loss)}</dd></div><div><dt>Take profit</dt><dd>{position.take_profit === null ? 'N/A' : money(position.take_profit)}</dd></div></dl></details></div>
    <dl className="md-position-fields">
      <PositionField label="Entry time" value={timestamp(position.opened_at)} />
      <PositionField label="Entry price" value={money(position.average_entry)} />
      <PositionField label="Quantity" value={decimal(position.quantity, 6)} />
      <PositionField label="Leverage" value="N/A" />
      <PositionField label="Liquidation" value="N/A" />
      <PositionField label="Margin" value={money(position.reserved_margin)} />
      <PositionField label="Unrealized P&L" value="N/A" />
    </dl>
  </article>;
}

function PositionField({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function FillsTable({ rows }: { rows: Trade[] }): React.JSX.Element {
  if (!rows.length) return <div className="md-state">No fill rows were returned for this account.</div>;
  return <div className="md-table-scroll"><table className="md-fill-table"><thead><tr><th>Side</th><th>Instrument</th><th>Fill price</th><th>Exit price</th><th>Quantity</th><th>Hold time</th><th>Entry notional</th><th>Exit notional</th><th>Fees</th><th>Net P&amp;L</th></tr></thead><tbody>{rows.map((trade) => <tr key={trade.fill_id}>
    <td><span className={trade.side.toUpperCase() === 'BUY' || trade.side.toUpperCase() === 'LONG' ? 'md-fill-buy' : 'md-fill-sell'}>{trade.side}</span><small>R{trade.round ?? '—'} · {trade.executed_at ? timestamp(trade.executed_at) : 'time N/A'}</small></td>
    <td>{trade.symbol}</td><td>{money(trade.price)}<small>exact fill</small></td><td>N/A</td><td>{decimal(trade.quantity, 6)}</td><td>N/A</td><td>N/A</td><td>N/A</td><td>{money(trade.fee)}</td><td>N/A</td>
  </tr>)}</tbody></table></div>;
}

function AuditFact({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

async function getLastTrades({ competitionId, agentId }: { competitionId: string; agentId: string }): Promise<{ items: Trade[]; total: number; complete: boolean }> {
  const firstPage = await getTradeHistory(competitionId, { limit: TRADE_PREVIEW_LIMIT, offset: 0, agent_id: agentId });
  if (firstPage.total <= TRADE_PREVIEW_LIMIT) return { items: [...firstPage.items].reverse(), total: firstPage.total, complete: true };
  const requestedOffset = Math.max(0, firstPage.total - TRADE_PREVIEW_LIMIT);
  const offset = Math.min(100_000, requestedOffset);
  const lastPage = await getTradeHistory(competitionId, { limit: TRADE_PREVIEW_LIMIT, offset, agent_id: agentId });
  return { items: [...lastPage.items].reverse(), total: lastPage.total, complete: requestedOffset <= 100_000 };
}

async function getAllPositions({ competitionId, agentId }: { competitionId: string; agentId: string }): Promise<{ items: Position[]; total: number; complete: boolean }> {
  const firstPage = await getPositionHistory(competitionId, { limit: POSITION_PAGE_SIZE, offset: 0, agent_id: agentId, include_closed: false });
  const items = [...firstPage.items];
  const total = firstPage.total;
  while (items.length < total && items.length < 100_000) {
    const nextPage = await getPositionHistory(competitionId, { limit: POSITION_PAGE_SIZE, offset: items.length, agent_id: agentId, include_closed: false });
    if (nextPage.items.length === 0) break;
    items.push(...nextPage.items);
  }
  return { items, total, complete: items.length >= total };
}
