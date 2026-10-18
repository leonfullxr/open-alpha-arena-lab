import { useRef, useState, type KeyboardEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeftRight, ArrowRight, ArrowUpRight, BriefcaseBusiness, MessageSquareText, NotebookText } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { ActivityPanel, type ActivityTab } from './activity';
import { type Benchmark, type EquityRange } from './api';
import { competitionReadOptions, useCompetitionLiveStatus } from './competition-reads';
import { EquityChart } from './equity-chart';
import { AssetIcon } from './asset-action-icons';
import { AgentLink, DataStatus, decimal, money, PageHeading, profileLabel, QueryState, timestamp } from './ui';

const tabs: ActivityTab[] = ['Live trades', 'Model chat', 'Positions', 'Research notes'];
const tabIcons = [ArrowLeftRight, MessageSquareText, BriefcaseBusiness, NotebookText];

export default function CompetitionPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const [tab, setTab] = useState<ActivityTab>('Live trades');
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const competitionQuery = useQuery({ ...competitionReadOptions.liveCompetition(competitionId), enabled: Boolean(competitionId) });
  const competition = competitionQuery.data;
  const leaderboard = useQuery({ ...competitionReadOptions.leaderboard(competitionId), enabled: Boolean(competitionId) });
  const equity = useQuery({ ...competitionReadOptions.chart(competitionId, chartRange), enabled: Boolean(competitionId) });
  const metrics = useQuery({ ...competitionReadOptions.metrics(competitionId), enabled: Boolean(competitionId) });
  const stream = useCompetitionLiveStatus();
  const leading = leaderboard.data?.[0];
  const benchmark = metrics.data?.benchmark;

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const nextIndex = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0
          : event.key === 'End' ? tabs.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    setTab(tabs[nextIndex]!);
    tabRefs.current[nextIndex]?.focus();
  }

  return <QueryState loading={competitionQuery.isLoading} error={competitionQuery.error} retry={() => void competitionQuery.refetch()}>
    {competition && <>
      <PageHeading eyebrow={`${profileLabel(competition.profile)} · ${competition.source_label}`} title={competition.name} detail={`Started ${competition.started_at ? timestamp(competition.started_at) : 'not started'}${competition.ended_at ? ` · finished ${timestamp(competition.ended_at)}` : ''}`}>
        <Link className="terminal-button" to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>Leaderboard <ArrowRight aria-hidden="true" size={15} /></Link>
      </PageHeading>
          <div className="run-status-line"><DataStatus state={competition.state} label={runLabel(competition.state, stream)} /><span>Every account starts with {money(competition.initial_balance)} virtual capital.</span></div>
      <section className="overview-metrics" aria-label="Competition summary">
        <Metric label="Competing models" value={String(competition.agents.length)} detail="Independent virtual accounts" />
        <Metric label="Current leader" value={leading?.agent_name ?? 'Waiting for results'} detail={leading ? `${signedPercent(leading.roi_pct)} return` : 'No ranked account data yet'} />
        <Metric label="Recorded fills" value={leaderboard.data ? leaderboard.data.reduce((total, row) => total + row.trade_count, 0).toLocaleString() : '—'} detail="Across all model accounts" />
        <Metric label="Elapsed time" value={elapsed(competition.started_at, competition.ended_at)} detail={competition.state === 'RUNNING' ? 'Simulation clock' : competition.state === 'FINISHED' ? 'Final run duration' : 'Simulation duration'} />
      </section>
      <div className="dashboard-grid">
        <div className="dashboard-main">
          <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.length === 0 ? 'The API has no equity points for this competition.' : undefined}>
            {equity.data && <EquityChart agents={competition.agents} rows={equity.data.items} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} benchmark={benchmark} />}
          </QueryState>
          <section className="account-summary" aria-label="Leaderboard preview">
            <div className="account-summary-heading"><div><p className="terminal-eyebrow">Ranked by marked equity</p><h2>Leaderboard</h2></div><Link className="leaderboard-open" to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>Full analysis <ArrowUpRight aria-hidden="true" size={14} /></Link></div>
            {leaderboard.isLoading ? <div className="query-state" role="status">Loading account rankings…</div> : leaderboard.error ? <div className="query-error" role="alert">{leaderboard.error.message} <button onClick={() => void leaderboard.refetch()}>Retry</button></div> : leaderboard.data?.length ? <div className="table-scroll compact-leaderboard" role="region" tabIndex={0} aria-label="Top model accounts, scroll horizontally for more columns"><table><thead><tr><th>Rank</th><th>Model</th><th>Return</th><th>Equity</th><th>Max drawdown</th><th>Fills</th></tr></thead><tbody>{leaderboard.data.slice(0, 6).map((row, index) => {
              const risk = metrics.data?.agents.find((item) => item.agent_id === row.agent_id);
              return <tr key={row.agent_id}><td>{index + 1}</td><td><AgentLink id={row.agent_id} name={row.agent_name} model={row.model} competitionId={competition.id} /></td><td className={Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{signedPercent(row.roi_pct)}</td><td>{money(row.equity)}</td><td>{risk?.max_drawdown_pct == null ? 'N/A' : `${Number(risk.max_drawdown_pct).toFixed(2)}%`}</td><td>{row.trade_count.toLocaleString()}</td></tr>;
            })}</tbody></table></div> : <div className="query-state">No ranked account data is available yet.</div>}
            <BenchmarkTile benchmark={benchmark} loading={metrics.isLoading} />
            {metrics.isError && <p className="leader-note">Competition metrics unavailable: {metrics.error.message}</p>}
          </section>
        </div>
      </div>
      <section className="dashboard-activity" aria-label="Competition activity">
        <div className="activity-workspace-heading"><div><p className="terminal-eyebrow">Inspect the public record</p><h2>Activity &amp; evidence</h2></div><span>Fills, decisions, positions and research notes</span></div>
          <div className="tab-list" role="tablist" aria-label="Competition records" aria-orientation="horizontal">{tabs.map((item, index) => { const Icon = tabIcons[index]!; return <button key={item} ref={(element) => { tabRefs.current[index] = element; }} id={`tab-${slug(item)}`} role="tab" tabIndex={tab === item ? 0 : -1} aria-selected={tab === item} aria-controls="activity-panel" onKeyDown={(event) => handleTabKeyDown(event, index)} onClick={() => setTab(item)}><Icon aria-hidden="true" size={15} />{item}</button>; })}</div>
          <div id="activity-panel" role="tabpanel" aria-labelledby={`tab-${slug(tab)}`}>
            <ActivityPanel competitionId={competition.id} tab={tab} agents={competition.agents} />
          </div>
      </section>
    </>}
  </QueryState>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }): React.JSX.Element {
  return <div className="overview-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function signedPercent(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%` : 'N/A';
}

function elapsed(start: string | null, end: string | null): string {
  if (!start) return 'Not started';
  const startMs = new Date(start).valueOf();
  const endMs = end ? new Date(end).valueOf() : Date.now();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return 'N/A';
  const minutes = Math.floor((endMs - startMs) / 60_000);
  const days = Math.floor(minutes / 1_440);
  const hours = Math.floor((minutes % 1_440) / 60);
  const remainder = minutes % 60;
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${remainder}m` : `${remainder}m`;
}

function runLabel(state: string, stream: 'paused' | 'connected' | 'reconnecting'): string {
  if (state === 'RUNNING') return stream === 'connected' ? 'Live event stream connected' : stream === 'reconnecting' ? 'Reconnecting - refreshing every 5 seconds' : 'Connecting to live updates';
  if (state === 'PAUSED') return 'Competition updates paused';
  if (state === 'FINISHED') return 'Final record - updates stopped';
  if (state === 'DRAFT') return 'Draft - not started';
  return state.toLocaleLowerCase().replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase());
}

function BenchmarkTile({ benchmark, loading }: { benchmark: Benchmark | null | undefined; loading: boolean }): React.JSX.Element {
  const returnPct = benchmark ? Number(benchmark.roi_pct) : null;
  return <div className="benchmark-tile">
    <div className="benchmark-heading">
      <div className="benchmark-title"><strong>{benchmark ? benchmark.label.replace(benchmark.symbol, '').trim() || 'Buy & hold' : 'Buy & hold'}</strong><span><AssetIcon symbol={benchmark?.symbol ?? 'BTC'} size={17} /></span></div>
      <div className="benchmark-value"><span>Ending equity</span><strong>{benchmark ? money(benchmark.equity) : loading ? 'Loading…' : 'N/A'}</strong></div>
    </div>
    {benchmark && returnPct !== null ? <>
      <p className={`benchmark-return ${returnPct >= 0 ? 'value-positive' : 'value-negative'}`}>{returnPct > 0 ? '+' : ''}{decimal(returnPct)}% return</p>
      <dl className="benchmark-assumptions">
        <div className="benchmark-price-window"><dt>Price window</dt><dd><span><small>Start</small><strong>{money(benchmark.start_price)}</strong></span><span className="benchmark-arrow" aria-hidden="true">→</span><span><small>End</small><strong>{money(benchmark.end_price)}</strong></span></dd></div>
        <div><dt>Fee</dt><dd>{decimal(Number(benchmark.fee_rate) * 100)}%</dd></div>
        <div><dt>Slippage</dt><dd>{decimal(benchmark.slippage_bps, 1)} bps</dd></div>
      </dl>
    </> : <p className="benchmark-unavailable" role="status">{loading ? 'Loading benchmark data…' : 'No benchmark summary is available for this competition.'}</p>}
  </div>;
}

function slug(value: string): string { return value.toLowerCase().replace(/[^a-z0-9]+/g, '-'); }
