import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { DecisionFeed } from './chat';
import { getCompetitionMetrics, getLeaderboard, type Competition } from './api';
import { RulesEvidence, useRulesArtifact } from './rules';
import { modelToneClass, profileTag } from './colors';
import { AgentLink, money, percent, QueryState, StatusBadge, timestamp } from './ui';

type RailTab = 'chat' | 'details';
const RAIL_TABS: RailTab[] = ['chat', 'details'];

export function ActivityRail({ competition, loading, error }: { competition?: Competition; loading?: boolean; error?: Error | null }): React.JSX.Element {
  const [tab, setTab] = useState<RailTab>('chat');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const badge = competition ? profileTag(competition.profile) : undefined;

  useEffect(() => { setTab('chat'); }, [competition?.id]);

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const next = event.key === 'ArrowRight' ? (index + 1) % RAIL_TABS.length
      : event.key === 'ArrowLeft' ? (index + RAIL_TABS.length - 1) % RAIL_TABS.length
        : event.key === 'Home' ? 0
          : event.key === 'End' ? RAIL_TABS.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setTab(RAIL_TABS[next]!);
    tabRefs.current[next]?.focus();
  }

  return <aside id="model-activity" className="arena-rail" aria-label="Model activity">
    <div className="arena-rail-tabs" role="tablist" aria-label="Activity views" aria-orientation="horizontal">
      {RAIL_TABS.map((item, index) => <button key={item} ref={(element) => { tabRefs.current[index] = element; }} id={`rail-tab-${item}`} role="tab" type="button" tabIndex={tab === item ? 0 : -1} aria-selected={tab === item} aria-controls="rail-panel" onKeyDown={(event) => handleKeyDown(event, index)} onClick={() => setTab(item)}>{item === 'chat' ? 'MODEL CHAT' : 'COMPETITION DETAILS'}</button>)}
    </div>
    <div className="arena-rail-panel" id="rail-panel" role="tabpanel" aria-labelledby={`rail-tab-${tab}`}>
      {!competition
        ? <QueryState loading={loading} error={error} empty="The public API has no competition to stream yet."><div /></QueryState>
        : tab === 'chat'
          ? <DecisionFeed key={competition.id} competitionId={competition.id} agents={competition.agents} badge={badge} />
          : <RunDetails competition={competition} />}
    </div>
  </aside>;
}

function RunDetails({ competition }: { competition: Competition }): React.JSX.Element {
  const leaderboard = useQuery({ queryKey: ['competition', competition.id, 'leaderboard'], queryFn: () => getLeaderboard(competition.id), enabled: Boolean(competition.id) });
  const metrics = useQuery({ queryKey: ['competition', competition.id, 'metrics'], queryFn: () => getCompetitionMetrics(competition.id), enabled: Boolean(competition.id) });
  const rules = useRulesArtifact(competition.id);
  const leader = leaderboard.data?.[0];

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
      {leaderboard.error && <p className="run-note">Account rows unavailable: {leaderboard.error.message}</p>}
    </section>
    <section className="run-metrics" aria-label="Account metrics">
      <h2>ACCOUNT METRICS</h2>
      {metrics.isLoading && <p className="run-note" role="status">Loading metrics…</p>}
      {metrics.error && <p className="run-note">Metrics unavailable: {metrics.error.message}</p>}
      {metrics.data && <dl className="run-facts">
        {metrics.data.agents.map((agent) => {
          const name = competition.agents.find((item) => item.id === agent.agent_id)?.name ?? agent.agent_id;
          return <div key={agent.agent_id}><dt>{name}</dt><dd>Win rate {percent(agent.win_rate_pct)} · Sharpe {agent.sharpe_ratio === null ? 'N/A' : Number(agent.sharpe_ratio).toFixed(3)} · Max drawdown {percent(agent.max_drawdown_pct)} · Closed trades {agent.closed_trades}</dd></div>;
        })}
        {metrics.data.benchmark && <div><dt>{metrics.data.benchmark.label}</dt><dd>{money(metrics.data.benchmark.equity)} · {percent(metrics.data.benchmark.roi_pct)} · {metrics.data.benchmark.symbol}</dd></div>}
      </dl>}
    </section>
    <p className="run-note"><Link to={`/simulation/${encodeURIComponent(competition.id)}/leaderboard`}>FULL LEADERBOARD</Link></p>
    {leader && <p className="run-note">Rank leader {leader.agent_name} at {money(leader.equity)}, ranked by marked equity against shared starting capital.</p>}
    <section className="run-rules" aria-label="Frozen competition rules">
      <h2>FROZEN RULES</h2>
      {rules.isLoading && <p className="run-note" role="status">Loading frozen rules…</p>}
      {rules.error && <p className="query-error" role="alert">{rules.error.message} <button onClick={() => void rules.refetch()}>Retry rules</button></p>}
      {rules.data && <RulesEvidence artifact={rules.data} />}
    </section>
  </div>;
}
