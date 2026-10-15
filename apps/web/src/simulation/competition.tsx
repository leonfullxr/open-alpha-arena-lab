import { useRef, useState, type KeyboardEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ActivityPanel, type ActivityTab } from './activity';
import { getCompetition, getCompetitionMetrics, getEquityChart, getLeaderboard, type Benchmark, type EquityRange } from './api';
import { EquityChart } from './equity-chart';
import { useCompetitionStream } from './stream';
import { AgentLink, DataStatus, money, PageHeading, QueryState, StatusBadge, timestamp } from './ui';

const tabs: ActivityTab[] = ['Live Trades', 'Model Chat', 'Positions', 'README.TXT'];

export default function CompetitionPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const [tab, setTab] = useState<ActivityTab>('Live Trades');
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const competitionQuery = useQuery({
    queryKey: ['competition', competitionId],
    queryFn: () => getCompetition(competitionId),
    enabled: Boolean(competitionId),
    refetchInterval: (query) => query.state.data?.state === 'RUNNING' ? 5_000 : false,
  });
  const competition = competitionQuery.data;
  const leaderboard = useQuery({ queryKey: ['competition', competitionId, 'leaderboard'], queryFn: () => getLeaderboard(competitionId), enabled: Boolean(competitionId) });
  const equity = useQuery({ queryKey: ['competition', competitionId, 'chart', chartRange], queryFn: () => getEquityChart(competitionId, chartRange), enabled: Boolean(competitionId) });
  const metrics = useQuery({ queryKey: ['competition', competitionId, 'metrics'], queryFn: () => getCompetitionMetrics(competitionId), enabled: Boolean(competitionId) });
  const stream = useCompetitionStream(competition);
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
      <PageHeading eyebrow={`${competition.profile} / ${competition.source_label}`} title={competition.name} detail={`Started ${competition.started_at ? timestamp(competition.started_at) : 'not started'}${competition.ended_at ? ` · finished ${timestamp(competition.ended_at)}` : ''}`}>
        <StatusBadge state={competition.state} />
        <Link className="terminal-button" to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>Leaderboard</Link>
      </PageHeading>
      <div className="run-status-line"><DataStatus state={competition.state} label={runLabel(competition.source_label, competition.state, stream)} /><span>Every account starts with {money(competition.initial_balance)} virtual capital.</span></div>
      <div className="dashboard-grid">
        <div className="dashboard-main">
          <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.length === 0 ? 'The API has no equity points for this competition.' : undefined}>
            {equity.data && <EquityChart agents={competition.agents} rows={equity.data.items} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} benchmark={benchmark} />}
          </QueryState>
          <section className="account-summary" aria-label="Account summaries">
            <div className="account-summary-heading"><div><p className="terminal-eyebrow">ACCOUNT VALUE</p><h2>Model accounts</h2></div><span>{competition.agents.length} accounts</span></div>
            <div className="account-list">{competition.agents.map((agent) => {
              const row = leaderboard.data?.find((item) => item.agent_id === agent.id);
              return <article className="account-tile" key={agent.id}>
                <AgentLink id={agent.id} name={agent.name} model={agent.model} competitionId={competition.id} />
                <strong>{row ? money(row.equity) : '—'}</strong>
                <span className={Number(row?.roi_pct ?? 0) >= 0 ? 'value-positive' : 'value-negative'}>{row ? `${Number(row.roi_pct).toFixed(2)}%` : 'Waiting for account data'}</span>
                <span className="account-subline">{row ? `${money(row.fees)} fees · ${row.trade_count} fills` : 'Waiting for account data'}</span>
              </article>;
            })}</div>
            <BenchmarkTile benchmark={benchmark} loading={metrics.isLoading} />
            {metrics.isError && <p className="leader-note">Competition metrics unavailable: {metrics.error.message}</p>}
            {leading && <p className="leader-note">Current rank leader: {leading.agent_name}, ranked by marked equity against shared starting capital.</p>}
          </section>
        </div>
        <aside className="dashboard-activity" aria-label="Competition activity">
          <div className="tab-list" role="tablist" aria-label="Competition records" aria-orientation="horizontal">{tabs.map((item, index) => <button key={item} ref={(element) => { tabRefs.current[index] = element; }} id={`tab-${slug(item)}`} role="tab" tabIndex={tab === item ? 0 : -1} aria-selected={tab === item} aria-controls="activity-panel" onKeyDown={(event) => handleTabKeyDown(event, index)} onClick={() => setTab(item)}>{item}</button>)}</div>
          <div id="activity-panel" role="tabpanel" aria-labelledby={`tab-${slug(tab)}`}>
            <ActivityPanel competitionId={competition.id} tab={tab} agents={competition.agents} />
          </div>
        </aside>
      </div>
    </>}
  </QueryState>;
}

function runLabel(source: string, state: string, stream: 'paused' | 'connected' | 'reconnecting'): string {
  if (state === 'RUNNING') return `${source} · ${stream === 'connected' ? 'event stream connected' : stream === 'reconnecting' ? 'reconnecting, 5 s refresh' : 'connecting'}`;
  return `${source} · ${state}`;
}

function BenchmarkTile({ benchmark, loading }: { benchmark: Benchmark | null | undefined; loading: boolean }): React.JSX.Element {
  return <div className="benchmark-tile">
    <div className="benchmark-heading"><span>{benchmark?.label ?? 'BTC buy & hold'}</span><strong>{benchmark ? money(benchmark.equity) : loading ? 'Loading…' : 'N/A'}</strong></div>
    {benchmark ? <><span>{Number(benchmark.roi_pct).toFixed(2)}% return · {benchmark.symbol}</span><small>{money(benchmark.start_price)} → {money(benchmark.end_price)} · fee {Number(benchmark.fee_rate).toFixed(2)}% · slippage {Number(benchmark.slippage_bps).toFixed(1)} bps</small></> : <small>{loading ? 'Loading API benchmark summary.' : 'No benchmark summary is available for this competition.'}</small>}
  </div>;
}

function slug(value: string): string { return value.toLowerCase().replace(/[^a-z0-9]+/g, '-'); }
