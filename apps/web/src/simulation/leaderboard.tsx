import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitionMetrics, getCompetitions, getLeaderboard, type AgentMetrics, type LeaderboardRow } from './api';
import { modelToneClass, profileTag } from './colors';
import { AgentLink, decimal, money, percent, QueryState, timestamp } from './ui';

type SortKey = 'agent_name' | 'equity' | 'roi_pct' | 'realized_pnl' | 'unrealized_pnl' | 'fees' | 'funding' | 'trade_count' | 'win_rate_pct' | 'profit_factor' | 'max_drawdown_pct' | 'sharpe_ratio' | 'average_leverage' | 'current_margin_used' | 'current_gross_exposure';

export default function LeaderboardPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const navigate = useNavigate();
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const selected = competitions.data?.find((item) => item.id === competitionId);
  const rowsQuery = useQuery({ queryKey: ['competition', competitionId, 'leaderboard'], queryFn: () => getLeaderboard(competitionId), enabled: Boolean(competitionId) });
  const metrics = useQuery({ queryKey: ['competition', competitionId, 'metrics'], queryFn: () => getCompetitionMetrics(competitionId), enabled: Boolean(competitionId) });
  const [sortKey, setSortKey] = useState<SortKey>('equity');
  const [descending, setDescending] = useState(true);
  const rows = useMemo(() => [...(rowsQuery.data ?? [])].sort((a, b) => compare(a, metricFor(metrics.data?.agents, a.agent_id), b, metricFor(metrics.data?.agents, b.agent_id), sortKey, descending)), [rowsQuery.data, metrics.data, sortKey, descending]);

  function changeSort(key: SortKey): void {
    if (sortKey === key) setDescending((value) => !value);
    else { setSortKey(key); setDescending(key !== 'agent_name'); }
  }

  return <>
    <header className="run-header">
      <div className="run-title">
        <p className="terminal-eyebrow">PUBLIC RANKINGS / ACCOUNT METRICS</p>
        <h1>LEADERBOARD</h1>
      </div>
      <div className="run-header-side">
        {selected ? <span className="run-header-meta">{selected.name} · {profileTag(selected.profile)} · {selected.state}</span> : <span className="run-header-meta">NO COMPETITION SELECTED</span>}
        <span className="run-header-meta">{selected ? `${selected.agents.length} ACCOUNTS · ${money(selected.initial_balance)} STARTING CAPITAL` : ''}</span>
        <label className="run-picker">RUN
          <select value={competitionId} onChange={(event) => { if (event.target.value) navigate(`/simulation/${encodeURIComponent(event.target.value)}/leaderboard`); }} disabled={!competitions.data?.length}>
            {competitions.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
      </div>
    </header>
    {metrics.error && <div className="metric-availability" role="status">Account metrics unavailable: {metrics.error.message}. Returned equity and P&amp;L values remain available below.</div>}
    <QueryState loading={competitions.isLoading || rowsQuery.isLoading} error={competitions.error ?? rowsQuery.error} retry={() => void (competitions.isError ? competitions.refetch() : rowsQuery.refetch())} empty={rowsQuery.data?.length === 0 ? 'No leaderboard rows are available for this competition.' : !competitionId && !competitions.isLoading ? 'The API has no competitions yet.' : undefined}>
      {selected && rowsQuery.data && <>
        <section className="leaderboard-section" aria-labelledby="leaderboard-title">
          <div className="panel-heading">
            <div><p className="terminal-eyebrow">{selected.profile} · {selected.source_label}</p><h2 id="leaderboard-title">RANKED ACCOUNTS</h2></div>
            <span className="panel-count">{selected.started_at ? `${timestamp(selected.started_at)} → ${selected.ended_at ? timestamp(selected.ended_at) : 'open'}` : 'NOT STARTED'}</span>
          </div>
          <div className="table-scroll leaderboard-table"><table><thead><tr>
            <th>RANK</th>
            <SortHeader label="ACCOUNT" sortKey="agent_name" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="MARKED EQUITY" sortKey="equity" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="RETURN" sortKey="roi_pct" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="REALIZED P&amp;L" sortKey="realized_pnl" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="UNREALIZED P&amp;L" sortKey="unrealized_pnl" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="FEES" sortKey="fees" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="FUNDING" sortKey="funding" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="FILLS" sortKey="trade_count" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="WIN RATE" sortKey="win_rate_pct" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="PROFIT FACTOR" sortKey="profit_factor" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="MAX DRAWDOWN" sortKey="max_drawdown_pct" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="SHARPE" sortKey="sharpe_ratio" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="AVG. LEVERAGE" sortKey="average_leverage" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="MARGIN USED" sortKey="current_margin_used" active={sortKey} descending={descending} onSort={changeSort} />
            <SortHeader label="GROSS EXPOSURE" sortKey="current_gross_exposure" active={sortKey} descending={descending} onSort={changeSort} />
          </tr></thead><tbody>{rows.map((row, index) => {
            const metric = metricFor(metrics.data?.agents, row.agent_id);
            return <tr key={row.agent_id}>
              <td className="tabular">{index + 1}</td>
              <td><AgentLink competitionId={selected.id} id={row.agent_id} name={row.agent_name} model={row.model} toneClass={modelToneClass(selected.agents, row.agent_id)} /></td>
              <td className="tabular">{money(row.equity)}</td>
              <td className={Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{percent(row.roi_pct)}</td>
              <td className="tabular">{money(row.realized_pnl)}</td><td className="tabular">{money(row.unrealized_pnl)}</td><td className="tabular">{money(row.fees)}</td><td className="tabular">{money(row.funding)}</td><td className="tabular">{row.trade_count}</td>
              <td className="tabular">{percent(metric?.win_rate_pct)}</td><td className="tabular">{decimalOrNA(metric?.profit_factor)}</td><td className="tabular">{percent(metric?.max_drawdown_pct)}</td><td className="tabular">{decimalOrNA(metric?.sharpe_ratio, 3)}</td><td className="tabular">{decimalOrNA(metric?.average_leverage)}</td><td className="tabular">{money(metric?.current_margin_used ?? NaN)}</td><td className="tabular">{metric?.current_gross_exposure === null || metric?.current_gross_exposure === undefined ? 'N/A' : money(metric.current_gross_exposure)}</td>
            </tr>;
          })}</tbody></table></div>
          <div className="table-footnote"><p>The initial order uses marked equity against equal starting capital. Sorting recalculates rank. A metric shown as N/A was returned as null or had no matching account row. <Link to={`/simulation/${encodeURIComponent(selected.id)}`}>OPEN THE COMPETITION RECORD →</Link></p><details><summary>METRIC DEFINITIONS</summary><p>Return is marked equity versus starting capital. Win rate counts positive realized trade journals; profit factor is gross realized profit divided by gross realized loss. Maximum drawdown is the largest peak-to-trough equity decline. Sharpe is calculated per round from sampled equity returns without annualization. Margin used is reserved margin on open positions; gross exposure is their marked notional. Average leverage is N/A when the API has no value.</p></details></div>
        </section>
      </>}
    </QueryState>
  </>;
}

function SortHeader({ label, sortKey, active, descending, onSort }: { label: string; sortKey: SortKey; active: SortKey; descending: boolean; onSort: (key: SortKey) => void }): React.JSX.Element {
  return <th aria-sort={active === sortKey ? descending ? 'descending' : 'ascending' : 'none'}><button className="sort-button" type="button" onClick={() => onSort(sortKey)}>{label}{active === sortKey ? descending ? ' ↓' : ' ↑' : ''}</button></th>;
}

function metricFor(rows: AgentMetrics[] | undefined, id: string): AgentMetrics | undefined { return rows?.find((row) => row.agent_id === id); }

function metricValue(row: LeaderboardRow, metric: AgentMetrics | undefined, key: SortKey): string | number | null {
  if (key === 'agent_name' || key === 'equity' || key === 'roi_pct' || key === 'realized_pnl' || key === 'unrealized_pnl' || key === 'fees' || key === 'funding' || key === 'trade_count') return row[key];
  return metric?.[key] ?? null;
}

function compare(a: LeaderboardRow, aMetrics: AgentMetrics | undefined, b: LeaderboardRow, bMetrics: AgentMetrics | undefined, key: SortKey, descending: boolean): number {
  const left = metricValue(a, aMetrics, key);
  const right = metricValue(b, bMetrics, key);
  if (left === null) return right === null ? a.agent_id.localeCompare(b.agent_id) : 1;
  if (right === null) return -1;
  const result = key === 'agent_name' ? String(left).localeCompare(String(right)) : Number(left) - Number(right);
  return (descending ? -1 : 1) * result || a.agent_id.localeCompare(b.agent_id);
}

function decimalOrNA(value: string | number | null | undefined, digits = 2): string {
  return value === null || value === undefined || value === '' ? 'N/A' : decimal(value, digits);
}
