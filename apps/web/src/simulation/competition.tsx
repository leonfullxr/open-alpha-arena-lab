import { useRef, useState, type KeyboardEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetition, getCompetitionMetrics, getEquityChart, getLeaderboard, type Benchmark, type EquityRange } from './api';
import { ActivityPanel, type ActivityTab } from './activity';
import { modelToneClass, profileTag } from './colors';
import { EquityChart } from './equity-chart';
import { useCompetitionStreamState } from './stream';
import { AgentLink, DataStatus, money, percent, QueryState, StatusBadge, timestamp } from './ui';

const recordTabs: ActivityTab[] = ['Live Trades', 'Positions', 'README.TXT'];

export default function CompetitionPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const [recordTab, setRecordTab] = useState<ActivityTab>('Live Trades');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const competitionQuery = useQuery({
    queryKey: ['competition', competitionId],
    queryFn: () => getCompetition(competitionId),
    enabled: Boolean(competitionId),
    refetchInterval: (query) => ['RUNNING', 'PAUSED', 'DRAFT'].includes(query.state.data?.state ?? '') ? 5_000 : false,
  });
  const competition = competitionQuery.data;
  const leaderboard = useQuery({ queryKey: ['competition', competitionId, 'leaderboard'], queryFn: () => getLeaderboard(competitionId), enabled: Boolean(competitionId) });
  const equity = useQuery({ queryKey: ['competition', competitionId, 'chart', chartRange], queryFn: () => getEquityChart(competitionId, chartRange), enabled: Boolean(competitionId) });
  const metrics = useQuery({ queryKey: ['competition', competitionId, 'metrics'], queryFn: () => getCompetitionMetrics(competitionId), enabled: Boolean(competitionId) });
  const stream = useCompetitionStreamState();
  const benchmark = metrics.data?.benchmark;
  const rows = leaderboard.data ?? [];

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const nextIndex = event.key === 'ArrowRight' ? (index + 1) % recordTabs.length
      : event.key === 'ArrowLeft' ? (index + recordTabs.length - 1) % recordTabs.length
        : event.key === 'Home' ? 0
          : event.key === 'End' ? recordTabs.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    setRecordTab(recordTabs[nextIndex]!);
    tabRefs.current[nextIndex]?.focus();
  }

  return <QueryState loading={competitionQuery.isLoading} error={competitionQuery.error} retry={() => void competitionQuery.refetch()}>
    {competition && <>
      <header className="run-header">
        <div className="run-title">
          <p className="terminal-eyebrow">{profileTag(competition.profile)} · {competition.source_label}</p>
          <h1>{competition.name}</h1>
        </div>
        <div className="run-header-side">
          <StatusBadge state={competition.state} />
          <DataStatus state={competition.state} label={streamLabel(competition.state, stream)} />
          <span className="run-header-meta">{competition.started_at ? `${timestamp(competition.started_at)} → ${competition.ended_at ? timestamp(competition.ended_at) : 'open'}` : 'Not started'}</span>
          <Link className="terminal-button" to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>FULL LEADERBOARD →</Link>
        </div>
      </header>
      <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.length === 0 ? 'The API has no equity points for this competition.' : undefined}>
        {equity.data && <EquityChart agents={competition.agents} rows={equity.data.items} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} benchmark={benchmark} />}
      </QueryState>
      <section className="accounts-panel" aria-label="Model accounts">
        <div className="panel-heading">
          <div><p className="terminal-eyebrow">ACCOUNT VALUE · RANKED BY MARKED EQUITY</p><h2>MODEL ACCOUNTS</h2></div>
          <span className="panel-count">{competition.agents.length} ACCOUNTS</span>
        </div>
        <QueryState loading={leaderboard.isLoading} error={leaderboard.error} retry={() => void leaderboard.refetch()} empty={leaderboard.data?.length === 0 ? 'The API has no ranked accounts for this competition yet.' : undefined}>
        {leaderboard.data && <div className="table-scroll accounts-table"><table><thead><tr>
          <th>RANK</th><th>MODEL</th><th>PROVIDER / MODEL ID</th><th>EQUITY</th><th>RETURN</th><th>REALIZED</th><th>UNREALIZED</th><th>FEES</th><th>FUNDING</th><th>FILLS</th><th>WIN RATE</th>
        </tr></thead><tbody>
          {rows.map((row, index) => {
            const metric = metrics.data?.agents.find((item) => item.agent_id === row.agent_id);
            const agent = competition.agents.find((item) => item.id === row.agent_id);
            return <tr key={row.agent_id}>
              <td className="tabular">{index + 1}</td>
              <td><AgentLink id={row.agent_id} name={row.agent_name} model={row.model} competitionId={competition.id} toneClass={modelToneClass(competition.agents, row.agent_id)} /></td>
              <td className="run-source">{agent ? `${agent.provider} · ${agent.model}` : row.model}</td>
              <td className="tabular">{money(row.equity)}</td>
              <td className={Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{percent(row.roi_pct)}</td>
              <td className="tabular">{money(row.realized_pnl)}</td>
              <td className="tabular">{money(row.unrealized_pnl)}</td>
              <td className="tabular">{money(row.fees)}</td>
              <td className="tabular">{money(row.funding)}</td>
              <td className="tabular">{row.trade_count}</td>
              <td className="tabular">{percent(metric?.win_rate_pct)}</td>
            </tr>;
          })}
        </tbody></table></div>
        }
        </QueryState>
        <BenchmarkRow benchmark={benchmark} loading={metrics.isLoading} error={metrics.error} />
      </section>
      <section className="competition-records" aria-label="Competition records">
        <div className="competition-record-tabs" role="tablist" aria-label="Competition records" aria-orientation="horizontal">{recordTabs.map((tab, index) => <button key={tab} ref={(element) => { tabRefs.current[index] = element; }} id={`competition-record-${slug(tab)}`} role="tab" type="button" tabIndex={recordTab === tab ? 0 : -1} aria-selected={recordTab === tab} aria-controls="competition-record-panel" onKeyDown={(event) => handleTabKeyDown(event, index)} onClick={() => setRecordTab(tab)}>{tab === 'Live Trades' ? 'TRADES' : tab === 'README.TXT' ? 'README.TXT' : tab.toUpperCase()}</button>)}</div>
        <div id="competition-record-panel" role="tabpanel" aria-labelledby={`competition-record-${slug(recordTab)}`}><ActivityPanel key={competition.id} competitionId={competition.id} tab={recordTab} agents={competition.agents} /></div>
      </section>
    </>}
  </QueryState>;
}

function slug(value: string): string { return value.toLowerCase().replace(/[^a-z0-9]+/g, '-'); }

function streamLabel(state: string, stream: 'paused' | 'connected' | 'reconnecting'): string {
  if (state === 'RUNNING') return stream === 'connected' ? 'EVENT STREAM CONNECTED' : stream === 'reconnecting' ? 'RECONNECTING · 5 S REFRESH' : 'CONNECTING';
  if (state === 'PAUSED') return 'PAUSED · 5 S REFRESH';
  return state;
}

function BenchmarkRow({ benchmark, loading, error }: { benchmark: Benchmark | null | undefined; loading: boolean; error: Error | null }): React.JSX.Element {
  return <div className="benchmark-row">
    <div className="benchmark-heading"><span className="terminal-eyebrow">BENCHMARK</span><strong>{benchmark?.label ?? 'BTC buy-and-hold summary'}</strong></div>
    {benchmark
      ? <>
        <span className="benchmark-value">{money(benchmark.equity)}</span>
        <span className={Number(benchmark.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{percent(benchmark.roi_pct)}</span>
        <span className="benchmark-detail">{money(benchmark.start_price)} → {money(benchmark.end_price)} · {benchmark.symbol} · fee {percent(Number(benchmark.fee_rate) * 100, 2)} · slippage {Number(benchmark.slippage_bps).toFixed(1)} bps</span>
        <span className="benchmark-detail">{benchmark.method}</span>
      </>
      : <span className="benchmark-detail">{loading ? 'Loading the API benchmark summary…' : error ? `Benchmark unavailable: ${error.message}` : 'The API returned no benchmark summary for this competition.'}</span>}
  </div>;
}
