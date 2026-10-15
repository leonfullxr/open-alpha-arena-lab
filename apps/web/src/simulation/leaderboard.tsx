import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitionMetrics, getCompetitions, getLeaderboard, type AgentMetrics, type LeaderboardRow } from './api';
import { useCompetitionStream } from './stream';
import { AgentLink, decimal, money, PageHeading, QueryState } from './ui';

type SortKey = 'agent_name' | 'equity' | 'roi_pct' | 'realized_pnl' | 'unrealized_pnl' | 'fees' | 'funding' | 'trade_count' | 'win_rate_pct' | 'profit_factor' | 'max_drawdown_pct' | 'sharpe_ratio' | 'average_leverage' | 'current_margin_used' | 'current_gross_exposure';

export default function LeaderboardPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const navigate = useNavigate();
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const selected = competitions.data?.find((item) => item.id === competitionId);
  useCompetitionStream(selected);
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
    <PageHeading eyebrow="PUBLIC RANKINGS / ACCOUNT METRICS" title="Leaderboard" detail="Accounts begin with equal virtual capital. Rank follows marked equity; the remaining measures come from the public metrics endpoint.">
      <label className="competition-select">Competition
        <select value={competitionId} onChange={(event) => { if (event.target.value) navigate(`/simulation/${encodeURIComponent(event.target.value)}/leaderboard`); }} disabled={!competitions.data?.length}>
          {competitions.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
    </PageHeading>
    {metrics.error && <div className="metric-availability" role="status">Account metrics unavailable: {metrics.error.message}. Returned equity and P&amp;L values remain available below.</div>}
    <QueryState loading={competitions.isLoading || rowsQuery.isLoading} error={competitions.error ?? rowsQuery.error} retry={() => void (competitions.isError ? competitions.refetch() : rowsQuery.refetch())} empty={rowsQuery.data?.length === 0 ? 'No leaderboard rows are available for this competition.' : !competitionId && !competitions.isLoading ? 'The API has no competitions yet.' : undefined}>
      {selected && rowsQuery.data && <>
        <div className="leaderboard-context"><span>{selected.profile}</span><span>{money(selected.initial_balance)} starting equity</span><span>{selected.state}</span><span>{selected.source_label}</span></div>
        <div className="table-scroll leaderboard-table"><table><thead><tr>
          <th>Rank</th>
          <SortHeader label="Account" sortKey="agent_name" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Marked equity" sortKey="equity" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Return" sortKey="roi_pct" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Realized P&amp;L" sortKey="realized_pnl" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Unrealized P&amp;L" sortKey="unrealized_pnl" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Fees" sortKey="fees" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Funding" sortKey="funding" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Fills" sortKey="trade_count" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Win rate" sortKey="win_rate_pct" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Profit factor" sortKey="profit_factor" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Max drawdown" sortKey="max_drawdown_pct" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Sharpe" sortKey="sharpe_ratio" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Avg. leverage" sortKey="average_leverage" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Margin used" sortKey="current_margin_used" active={sortKey} descending={descending} onSort={changeSort} />
          <SortHeader label="Gross exposure" sortKey="current_gross_exposure" active={sortKey} descending={descending} onSort={changeSort} />
        </tr></thead><tbody>{rows.map((row, index) => {
          const metric = metricFor(metrics.data?.agents, row.agent_id);
          return <tr key={row.agent_id}>
            <td>{index + 1}</td><td><AgentLink competitionId={selected.id} id={row.agent_id} name={row.agent_name} model={row.model} /></td><td className="tabular">{money(row.equity)}</td><td className={Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{decimal(row.roi_pct)}%</td><td>{money(row.realized_pnl)}</td><td>{money(row.unrealized_pnl)}</td><td>{money(row.fees)}</td><td>{money(row.funding)}</td><td>{row.trade_count}</td>
            <td>{percent(metric?.win_rate_pct)}</td><td>{decimalOrNA(metric?.profit_factor)}</td><td>{percent(metric?.max_drawdown_pct)}</td><td>{decimalOrNA(metric?.sharpe_ratio)}</td><td>{decimalOrNA(metric?.average_leverage)}</td><td>{money(metric?.current_margin_used ?? NaN)}</td><td>{metric?.current_gross_exposure === null || metric?.current_gross_exposure === undefined ? 'N/A' : money(metric.current_gross_exposure)}</td>
          </tr>;
        })}</tbody></table></div>
        <div className="table-footnote"><p>The initial order uses marked equity against equal starting capital. Sorting recalculates rank. A metric shown as N/A was returned as null or had no matching account row. <Link to={`/simulation/${encodeURIComponent(selected.id)}`}>Open competition record</Link>.</p><details><summary>Metric definitions</summary><p>Return is marked equity versus starting capital. Win rate counts positive realized trade journals; profit factor is gross realized profit divided by gross realized loss. Maximum drawdown is the largest peak-to-trough equity decline. Sharpe is calculated per round from sampled equity returns without annualization. Margin used is reserved margin on open positions; gross exposure is their marked notional. Average leverage is N/A when the API has no value.</p></details></div>
      </>}
    </QueryState>
  </>;
}

function SortHeader({ label, sortKey, active, descending, onSort }: { label: string; sortKey: SortKey; active: SortKey; descending: boolean; onSort: (key: SortKey) => void }): React.JSX.Element {
  return <th aria-sort={active === sortKey ? descending ? 'descending' : 'ascending' : 'none'}><button className="sort-button" onClick={() => onSort(sortKey)}>{label}{active === sortKey ? descending ? ' ↓' : ' ↑' : ''}</button></th>;
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

function percent(value: string | null | undefined): string { return value === null || value === undefined ? 'N/A' : `${decimal(value)}%`; }
function decimalOrNA(value: string | null | undefined): string { return value === null || value === undefined ? 'N/A' : decimal(value); }
