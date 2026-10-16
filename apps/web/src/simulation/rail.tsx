import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ActivityPanel, type ActivityTab } from './activity';
import { DecisionFeed } from './chat';
import { getCompetitionMetrics, getLeaderboard, getTradeHistory, type Competition, type Trade } from './api';
import { RulesEvidence, useRulesArtifact } from './rules';
import { useCompetitionStream } from './stream';
import { modelToneClass, profileTag } from './colors';
import { AgentLink, decimal, money, percent, QueryState, StatusBadge, timestamp } from './ui';

type RailTab = 'chat' | 'details' | 'fills' | 'positions';
type RailMode = 'aggregate' | 'run';

const AGGREGATE_TABS = [
  { id: 'chat', label: 'MODELCHAT' },
  { id: 'details', label: 'SEASON DETAILS' },
] as const satisfies ReadonlyArray<{ id: RailTab; label: string }>;

const RUN_TABS = [
  { id: 'fills', label: 'TRADES' },
  { id: 'chat', label: 'MODELCHAT' },
  { id: 'positions', label: 'POSITIONS' },
  { id: 'details', label: 'COMP DETAILS' },
] as const satisfies ReadonlyArray<{ id: RailTab; label: string }>;

const PROFILE_NOTES: Readonly<Record<string, string>> = {
  alpha_2025_baseline: 'Fixed inputs and execution policy keep accounts within this profile directly comparable.',
  research_extended: 'Experiments that change methods or execution policy are kept in a separate research track.',
};

export function ActivityRail({ mode, competition, competitions, loading, error }: {
  mode: RailMode;
  competition?: Competition;
  competitions: Competition[];
  loading?: boolean;
  error?: Error | null;
}): React.JSX.Element {
  const [tab, setTab] = useState<RailTab>('chat');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const badge = competition ? profileTag(competition.profile) : undefined;
  const tabs = mode === 'run' ? RUN_TABS : AGGREGATE_TABS;

  useEffect(() => { setTab('chat'); }, [mode, competition?.id]);

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0
          : event.key === 'End' ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setTab(tabs[next]!.id);
    tabRefs.current[next]?.focus();
  }

  return <aside id="model-activity" className={`arena-rail arena-rail--${mode}`} aria-label={mode === 'run' ? 'Run activity' : 'Season activity'}>
    <div className="arena-rail-tabs" role="tablist" aria-label="Activity views" aria-orientation="horizontal">
      {tabs.map((item, index) => <button key={item.id} ref={(element) => { tabRefs.current[index] = element; }} id={`rail-tab-${item.id}`} role="tab" type="button" tabIndex={tab === item.id ? 0 : -1} aria-selected={tab === item.id} aria-controls="rail-panel" onKeyDown={(event) => handleKeyDown(event, index)} onClick={() => setTab(item.id)}>{item.label}</button>)}
    </div>
    <div className="arena-rail-panel" id="rail-panel" role="tabpanel" aria-labelledby={`rail-tab-${tab}`}>
      {mode === 'aggregate'
        ? tab === 'chat'
          ? <AggregateChat competitions={competitions} loading={loading} error={error} />
          : <SeasonDetails competitions={competitions} loading={loading} error={error} />
        : !competition
          ? <QueryState loading={loading} error={error} empty="The public API has no competition to inspect yet."><div /></QueryState>
          : tab === 'chat'
            ? <DecisionFeed key={competition.id} competitionId={competition.id} agents={competition.agents} badge={badge} />
            : tab === 'fills'
              ? <FillsPanel competition={competition} />
              : tab === 'positions'
                ? <ActivityPanel key={`${competition.id}-positions`} competitionId={competition.id} agents={competition.agents} tab={'Positions' satisfies ActivityTab} />
                : <RunDetails competition={competition} />}
    </div>
  </aside>;
}

function AggregateChat({ competitions, loading, error }: { competitions: Competition[]; loading?: boolean; error?: Error | null }): React.JSX.Element {
  const [competitionId, setCompetitionId] = useState(competitions[0]?.id ?? '');
  const [agentId, setAgentId] = useState('');
  const competition = competitions.find((item) => item.id === competitionId);
  useCompetitionStream(competition);

  useEffect(() => {
    if (!competitions.some((item) => item.id === competitionId)) setCompetitionId(competitions[0]?.id ?? '');
  }, [competitions, competitionId]);
  useEffect(() => { setAgentId(''); }, [competitionId]);

  if (competitions.length === 0) {
    return <QueryState loading={loading} error={error} empty="There are no published runs with model activity yet."><div /></QueryState>;
  }
  return <div className="aggregate-chat">
    <p className="rail-intro">Choose a published run and account to inspect its public decisions. This preview is scoped to the selected run.</p>
    <div className="aggregate-chat-filters">
      <label htmlFor="aggregate-run-filter">RUN</label>
      <select id="aggregate-run-filter" value={competitionId} onChange={(event) => setCompetitionId(event.target.value)}>
        {competitions.map((item) => <option key={item.id} value={item.id}>{sourceMarker(item.source_label)} · {item.name}</option>)}
      </select>
      <label htmlFor="aggregate-model-filter">MODEL</label>
      <select id="aggregate-model-filter" value={agentId} onChange={(event) => setAgentId(event.target.value)} disabled={!competition}>
        <option value="">ALL MODELS</option>
        {(competition?.agents ?? []).map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
      </select>
    </div>
    {competition && <div className="aggregate-chat-selected">
      <header><div><span>{profileTag(competition.profile)} · {sourceMarker(competition.source_label)}</span><h2>{competition.name}</h2></div><Link to={`/simulation?run=${encodeURIComponent(competition.id)}`}>OPEN LIVE NOTE →</Link></header>
      <DecisionFeed key={`${competition.id}-${agentId}`} competitionId={competition.id} agents={competition.agents} agentId={agentId || undefined} showAgentFilter={false} badge={profileTag(competition.profile)} emptyMessage="No public decisions are recorded for this run and model." />
    </div>}
  </div>;
}

function SeasonDetails({ competitions, loading, error }: { competitions: Competition[]; loading?: boolean; error?: Error | null }): React.JSX.Element {
  if ((loading || error) && competitions.length === 0) return <QueryState loading={loading} error={error}><div /></QueryState>;
  const profiles = [...new Set(competitions.map((item) => item.profile))];
  const models = [...new Map(competitions.flatMap((run) => run.agents.map((agent) => [`${agent.provider}:${agent.model}`, { agent, run }] as const))).values()];
  return <div className="season-details">
    <header className="season-details-heading"><p className="terminal-eyebrow">OPEN ALPHA ARENA LAB</p><h2>PUBLIC RUN INDEX</h2><p>Paper experiments, grouped by their declared profile and linked to their public record.</p></header>
    <div className="season-model-legend" aria-label="Models listed in published runs">{models.map(({ agent, run }) => <span className={modelToneClass(run.agents, agent.id)} key={`${agent.provider}:${agent.model}`}><i aria-hidden="true" />{agent.name}</span>)}</div>
    <section className="season-method"><h3>HOW TO READ THIS SEASON</h3><p>The baseline keeps shared experiment inputs fixed for within-run comparisons. Extended research is listed separately when its methods or execution policy differ. Each card points to an actual run returned by the public API.</p></section>
    {profiles.length === 0 ? <div className="query-state">The public API has not published a run profile yet.</div> : <section className="season-competitions"><div><p className="terminal-eyebrow">COMPETITIONS</p><h3>Published runs</h3></div>{profiles.map((profile) => {
      const runs = competitions.filter((item) => item.profile === profile);
      return <section className="season-profile" key={profile}>
        <div className="season-profile-heading"><div><span className="profile-tag">{profileTag(profile)}</span><h2>{profile.replaceAll('_', ' ')}</h2></div><span>{runs.length} {runs.length === 1 ? 'run' : 'runs'}</span></div>
        <p>{PROFILE_NOTES[profile] ?? 'The API reports this profile without a published display definition.'}</p>
        <div className="season-run-cards">{runs.map((run) => <Link className="season-run-card" to={`/simulation?run=${encodeURIComponent(run.id)}`} key={run.id}>
          <span className="season-run-marker" aria-hidden="true">→</span>
          <span className="season-run-copy"><strong>{run.name}</strong><small>{sourceMarker(run.source_label)} · {run.agents.length} {run.agents.length === 1 ? 'account' : 'accounts'}</small></span>
          <StatusBadge state={run.state} />
        </Link>)}</div>
      </section>;
    })}</section>}
    <p className="availability-note">Baseline and extended results are reported as separate tracks; this view does not rank across profiles.</p>
  </div>;
}

function sourceMarker(source: string): string {
  const normalized = source.toUpperCase();
  if (normalized.includes('TEST FIXTURE')) return 'TEST FIXTURE';
  if (normalized.includes('DEMO REPLAY')) return 'DEMO REPLAY';
  return source || 'SOURCE NOT REPORTED';
}

function FillsPanel({ competition }: { competition: Competition }): React.JSX.Element {
  const pageSize = 20;
  const [page, setPage] = useState(0);
  const query = { limit: pageSize, offset: page * pageSize };
  const fills = useQuery({
    queryKey: ['competition', competition.id, 'trades', query],
    queryFn: () => getTradeHistory(competition.id, query),
    enabled: Boolean(competition.id),
  });
  const total = fills.data?.total ?? 0;
  const pageCount = Math.ceil(total / pageSize);
  useEffect(() => { setPage((current) => Math.min(current, Math.max(0, pageCount - 1))); }, [pageCount]);

  return <section className="rail-fills" aria-labelledby="rail-fills-title">
    <div className="panel-heading"><div><p className="terminal-eyebrow">RECORDED EXECUTIONS</p><h2 id="rail-fills-title">Trade fills</h2></div><span className="panel-count">{total} API RECORDS</span></div>
    <p className="complete-history-note">These rows are individual fill records returned by the API; they do not imply a closed round-trip trade.</p>
    {fills.isLoading ? <div className="query-state" role="status">Loading fill records…</div>
      : <QueryState error={fills.error} stale={fills.data !== undefined} retry={() => void fills.refetch()}>
          <FillTable rows={fills.data?.items ?? []} />
          {pageCount > 1 && <div className="history-pagination"><span>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} of {total} fills</span><div><button disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>PREV</button><button disabled={page + 1 >= pageCount} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>NEXT</button></div></div>}
      </QueryState>}
  </section>;
}

function FillTable({ rows }: { rows: Trade[] }): React.JSX.Element {
  if (rows.length === 0) return <div className="query-state">The API has no fill records for this run.</div>;
  return <div className="table-scroll"><table className="rail-fill-table"><thead><tr><th>TIME</th><th>MODEL</th><th>SYMBOL</th><th>SIDE</th><th>QUANTITY</th><th>FILL PRICE</th><th>FEE</th><th>STATUS</th></tr></thead><tbody>{rows.map((fill) => <tr key={fill.fill_id}>
    <td>{fill.executed_at ? timestamp(fill.executed_at) : 'Not recorded'}</td><td>{fill.agent_name}</td><td>{fill.symbol}</td><td>{fill.side}</td><td>{decimal(fill.quantity, 6)}</td><td>{money(fill.price)}</td><td>{money(fill.fee)}</td><td>{fill.status}</td>
  </tr>)}</tbody></table></div>;
}

function RunDetails({ competition }: { competition: Competition }): React.JSX.Element {
  const leaderboard = useQuery({ queryKey: ['competition', competition.id, 'leaderboard'], queryFn: () => getLeaderboard(competition.id), enabled: Boolean(competition.id) });
  const metrics = useQuery({ queryKey: ['competition', competition.id, 'metrics'], queryFn: () => getCompetitionMetrics(competition.id), enabled: Boolean(competition.id) });
  const rules = useRulesArtifact(competition.id);

  return <div className="run-details">
    <dl className="run-facts">
      <div><dt>Run</dt><dd>{competition.name}</dd></div>
      <div><dt>Profile</dt><dd><code>{competition.profile}</code></dd></div>
      <div><dt>State</dt><dd><StatusBadge state={competition.state} /></dd></div>
      <div><dt>Source</dt><dd>{competition.source_label}</dd></div>
      <div><dt>Started</dt><dd>{competition.started_at ? timestamp(competition.started_at) : 'Not started'}</dd></div>
      <div><dt>Finished</dt><dd>{competition.ended_at ? timestamp(competition.ended_at) : 'Still open'}</dd></div>
      <div><dt>Starting capital</dt><dd>{money(competition.initial_balance)} virtual</dd></div>
      <div><dt>Accounts</dt><dd>{competition.agents.length}</dd></div>
    </dl>
    <section className="run-accounts" aria-label="Accounts in this run">
      <h2>ACCOUNTS</h2>
      <div className="table-scroll"><table><thead><tr><th>MODEL</th><th>EQUITY</th><th>RETURN</th></tr></thead><tbody>
        {competition.agents.map((agent) => {
          const row = leaderboard.data?.find((item) => item.agent_id === agent.id);
          return <tr key={agent.id}>
            <td><AgentLink id={agent.id} name={agent.name} model={agent.model} competitionId={competition.id} toneClass={modelToneClass(competition.agents, agent.id)} /></td>
            <td className="tabular">{row ? money(row.equity) : '—'}</td>
            <td className={Number(row?.roi_pct ?? 0) >= 0 ? 'value-positive' : 'value-negative'}>{row ? percent(row.roi_pct) : '—'}</td>
          </tr>;
        })}
      </tbody></table></div>
      {leaderboard.isLoading && <p className="run-note" role="status">Loading account rows…</p>}
      {leaderboard.error && <p className="run-note" role="alert">{leaderboard.error.message} <button className="small-button" onClick={() => void leaderboard.refetch()}>RETRY</button></p>}
    </section>
    <section className="run-metrics"><h2>RUN METRICS</h2>
      {metrics.isLoading ? <p className="run-note" role="status">Loading run metrics…</p>
        : <QueryState error={metrics.error} stale={metrics.data !== undefined} retry={() => void metrics.refetch()}>
          {metrics.data ? <ul>{metrics.data.agents.map((agent) => <li key={agent.agent_id}><span>{competition.agents.find((item) => item.id === agent.agent_id)?.name ?? agent.agent_id}</span><span>{percent(agent.win_rate_pct)} win rate · {agent.winning_trades} wins · {agent.closed_trades} closed trades</span></li>)}</ul>
            : <p className="run-note">The API returned no run metrics.</p>}
        </QueryState>}
      {metrics.data?.benchmark && <p className="run-note">{metrics.data.benchmark.label}: {money(metrics.data.benchmark.equity)} · {percent(metrics.data.benchmark.roi_pct)} · {metrics.data.benchmark.symbol}</p>}
    </section>
    <p className="run-note"><Link to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>OPEN THE FULL LEADERBOARD →</Link></p>
    <section className="run-rules"><h2>FROZEN RULES</h2>
      {rules.isLoading ? <p className="run-note" role="status">Loading rule artifact…</p>
        : <QueryState error={rules.error} stale={rules.data !== undefined} retry={() => void rules.refetch()}>
          {rules.data ? <RulesEvidence artifact={rules.data} /> : <p className="run-note">The API returned no rule artifact.</p>}
        </QueryState>}
    </section>
    <p className="run-note"><Link to={`/simulation/${encodeURIComponent(competition.id)}`}>OPEN THE LIVE CHART AND FULL RUN RECORD →</Link></p>
  </div>;
}
