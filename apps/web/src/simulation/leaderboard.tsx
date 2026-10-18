import { useMemo } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight } from 'lucide-react';
import { type AgentMetrics, type LeaderboardRow } from './api';
import { competitionReadOptions } from './competition-reads';
import { AgentLink, decimal, money, PageHeading, profileLabel, QueryState } from './ui';

type SortKey = 'agent_name' | 'equity' | 'roi_pct' | 'realized_pnl' | 'unrealized_pnl' | 'fees' | 'funding' | 'trade_count' | 'win_rate_pct' | 'profit_factor' | 'max_drawdown_pct' | 'sharpe_ratio' | 'average_leverage' | 'current_margin_used' | 'current_gross_exposure';
const sortKeys: SortKey[] = ['agent_name', 'equity', 'roi_pct', 'realized_pnl', 'unrealized_pnl', 'fees', 'funding', 'trade_count', 'win_rate_pct', 'profit_factor', 'max_drawdown_pct', 'sharpe_ratio', 'average_leverage', 'current_margin_used', 'current_gross_exposure'];
type ColumnKey = Exclude<SortKey, 'agent_name'>;
type MetricView = 'overview' | 'risk' | 'trading' | 'custom';
const columnLabels: Record<ColumnKey, string> = {
  equity: 'Marked equity', roi_pct: 'Return', realized_pnl: 'Realized P&L', unrealized_pnl: 'Unrealized P&L', fees: 'Fees', funding: 'Funding', trade_count: 'Fills', win_rate_pct: 'Win rate', profit_factor: 'Profit factor', max_drawdown_pct: 'Max drawdown', sharpe_ratio: 'Sharpe', average_leverage: 'Avg. leverage', current_margin_used: 'Margin used', current_gross_exposure: 'Gross exposure',
};
const metricViews: Record<Exclude<MetricView, 'custom'>, ColumnKey[]> = {
  overview: ['equity', 'roi_pct', 'max_drawdown_pct', 'trade_count'],
  risk: ['roi_pct', 'sharpe_ratio', 'max_drawdown_pct', 'average_leverage', 'current_margin_used', 'current_gross_exposure'],
  trading: ['trade_count', 'win_rate_pct', 'profit_factor', 'realized_pnl', 'fees', 'funding'],
};

export default function LeaderboardPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const competitions = useQuery(competitionReadOptions.liveCompetitions());
  const selected = competitions.data?.find((item) => item.id === competitionId);
  const rowsQuery = useQuery({ ...competitionReadOptions.leaderboard(competitionId), enabled: Boolean(competitionId) });
  const metrics = useQuery({ ...competitionReadOptions.metrics(competitionId), enabled: Boolean(competitionId) });
  const requestedSort = searchParams.get('sort');
  const sortKey: SortKey = requestedSort && sortKeys.includes(requestedSort as SortKey) ? requestedSort as SortKey : 'equity';
  const descending = searchParams.get('order') !== 'asc';
  const requestedView = searchParams.get('view') as MetricView | null;
  const view: MetricView = requestedView && ['overview', 'risk', 'trading', 'custom'].includes(requestedView) ? requestedView : 'overview';
  const customColumns = searchParams.get('columns')?.split(',').filter((key): key is ColumnKey => sortKeys.includes(key as SortKey) && key !== 'agent_name') ?? metricViews.overview;
  const columns = view === 'custom' ? customColumns : metricViews[view];
  const rows = useMemo(() => [...(rowsQuery.data ?? [])].sort((a, b) => compare(a, metricFor(metrics.data?.agents, a.agent_id), b, metricFor(metrics.data?.agents, b.agent_id), sortKey, descending)), [rowsQuery.data, metrics.data, sortKey, descending]);

  function changeSort(key: SortKey): void {
    const nextDescending = sortKey === key ? !descending : key !== 'agent_name';
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('sort', key);
      next.set('order', nextDescending ? 'desc' : 'asc');
      return next;
    });
  }

  function changeView(nextView: MetricView): void {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('view', nextView);
      if (nextView !== 'custom') next.delete('columns');
      else if (!next.has('columns')) next.set('columns', metricViews.overview.join(','));
      return next;
    });
  }

  function toggleColumn(key: ColumnKey): void {
    const nextColumns = columns.includes(key) ? columns.filter((column) => column !== key) : [...columns, key];
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('view', 'custom');
      next.set('columns', nextColumns.join(','));
      return next;
    });
  }

  return <>
    <PageHeading eyebrow="Public rankings / account metrics" title="Leaderboard" detail="Accounts begin with equal virtual capital. Rank follows marked equity; the remaining measures come from the public metrics endpoint." />
    <div className="leaderboard-toolbar">
      <label htmlFor="leaderboard-view">Metric view</label>
      <select id="leaderboard-view" value={view} onChange={(event) => changeView(event.target.value as MetricView)}>
        <option value="overview">Overview</option><option value="risk">Risk</option><option value="trading">Trading</option><option value="custom">Custom</option>
      </select>
      <span>Ranked by {columnLabels[sortKey as ColumnKey] ?? 'account name'} · {selected ? profileLabel(selected.profile) : 'Selected competition'} · {selected ? money(selected.initial_balance) : '—'} starting capital</span>
    </div>
    {view === 'custom' && <fieldset className="leaderboard-columns"><legend>Visible columns</legend>{sortKeys.filter((key): key is ColumnKey => key !== 'agent_name').map((key) => <label key={key}><input type="checkbox" checked={columns.includes(key)} onChange={() => toggleColumn(key)} />{columnLabels[key]}</label>)}</fieldset>}
    {metrics.error && <div className="metric-availability" role="status">Account metrics unavailable: {metrics.error.message}. Returned equity and P&amp;L values remain available below.</div>}
    <QueryState loading={competitions.isLoading || rowsQuery.isLoading} error={competitions.error ?? rowsQuery.error} retry={() => void (competitions.isError ? competitions.refetch() : rowsQuery.refetch())} empty={rowsQuery.data?.length === 0 ? 'No leaderboard rows are available for this competition.' : !competitionId && !competitions.isLoading ? 'The API has no competitions yet.' : undefined}>
      {selected && rowsQuery.data && <>
        <p className="table-scroll-hint">Swipe horizontally to inspect the remaining metrics.</p>
        <div className="table-scroll leaderboard-table" role="region" tabIndex={0} aria-label="Competition leaderboard table, scroll horizontally for more columns"><table><thead><tr>
          <th>Rank</th>
          <SortHeader label="Account" sortKey="agent_name" active={sortKey} descending={descending} onSort={changeSort} />
          {columns.map((key) => <SortHeader key={key} label={columnLabels[key]} sortKey={key} active={sortKey} descending={descending} onSort={changeSort} />)}
        </tr></thead><tbody>{rows.map((row, index) => {
          const metric = metricFor(metrics.data?.agents, row.agent_id);
          return <tr key={row.agent_id}>
            <td>{index + 1}</td><td><AgentLink competitionId={selected.id} id={row.agent_id} name={row.agent_name} model={row.model} /></td>{columns.map((key) => <td key={key} className={key === 'roi_pct' ? Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative' : undefined}>{formatColumn(row, metric, key)}</td>)}
          </tr>;
        })}</tbody></table></div>
        <div className="leaderboard-mobile-list" role="list" aria-label="Ranked model accounts">
          {rows.map((row, index) => {
            const metric = metricFor(metrics.data?.agents, row.agent_id);
            return <article className="leaderboard-mobile-row" key={row.agent_id} role="listitem">
              <div className="leaderboard-mobile-identity"><span>#{index + 1}</span><AgentLink competitionId={selected.id} id={row.agent_id} name={row.agent_name} model={row.model} /></div>
              <dl>{columns.map((key) => <div key={key}>
                <dt>{columnLabels[key]}</dt>
                <dd className={key === 'roi_pct' ? Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative' : undefined}>{formatColumn(row, metric, key)}</dd>
              </div>)}</dl>
            </article>;
          })}
        </div>
        <div className="table-footnote"><p>The initial order uses marked equity against equal starting capital. Sorting recalculates rank. A metric shown as N/A was returned as null or had no matching account row. <Link to={`/simulation/${encodeURIComponent(selected.id)}`}>Open competition record <ArrowUpRight aria-hidden="true" size={13} /></Link>.</p><details><summary>Metric definitions</summary><p>Return is marked equity versus starting capital. Win rate counts positive realized trade journals; profit factor is gross realized profit divided by gross realized loss. Maximum drawdown is the largest peak-to-trough equity decline. Sharpe is calculated per round from sampled equity returns without annualization. Margin used is reserved margin on open positions; gross exposure is their marked notional. Average leverage is N/A when the API has no value.</p></details></div>
      </>}
    </QueryState>
  </>;
}

function SortHeader({ label, sortKey, active, descending, onSort }: { label: string; sortKey: SortKey; active: SortKey; descending: boolean; onSort: (key: SortKey) => void }): React.JSX.Element {
  const direction = active === sortKey ? descending ? 'descending' : 'ascending' : null;
  return <th aria-sort={direction ?? 'none'}><button className="sort-button" data-direction={direction ?? undefined} aria-label={direction ? `Sort by ${label}; currently ${direction}` : `Sort by ${label}`} onClick={() => onSort(sortKey)}>{label}</button></th>;
}

function metricFor(rows: AgentMetrics[] | undefined, id: string): AgentMetrics | undefined { return rows?.find((row) => row.agent_id === id); }

function formatColumn(row: LeaderboardRow, metric: AgentMetrics | undefined, key: ColumnKey): string {
  const value = metricValue(row, metric, key);
  if (key === 'equity' || key === 'realized_pnl' || key === 'unrealized_pnl' || key === 'fees' || key === 'funding' || key === 'current_margin_used' || key === 'current_gross_exposure') return value === null ? 'N/A' : money(value);
  if (key === 'roi_pct' || key === 'win_rate_pct' || key === 'max_drawdown_pct') return value === null ? 'N/A' : `${decimal(value)}%`;
  if (key === 'trade_count') return value === null ? 'N/A' : Number(value).toLocaleString();
  return value === null ? 'N/A' : decimal(value);
}

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
