import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitionMetrics, getCompetitions, getLeaderboard, type AgentMetrics, type Competition, type LeaderboardRow } from './api';
import { modelColor, modelMarker, modelToneClass } from './colors';
import { decimal, money, percent, QueryState } from './ui';
import './leaderboard.css';

type Tab = 'overall' | 'advanced';
export type SortKey = 'equity' | 'roi_pct' | 'total_pnl' | 'fees' | 'win_rate_pct' | 'sharpe_ratio' | 'trade_count' | 'average_leverage';
export type Values = Record<SortKey, number | null> & {
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  funding: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number | null;
  current_margin_used: number | null;
  current_gross_exposure: number | null;
  closed_trades: number | null;
  winning_trades: number | null;
  losing_trades: number | null;
};
export type DisplayRow = {
  key: string;
  name: string;
  provider: string;
  model: string;
  agentIds: string[];
  values: Values;
  members: number;
};

export default function LeaderboardPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const navigate = useNavigate();
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const selected = competitions.data?.find((item) => item.id === competitionId);
  const rowsQuery = useQuery({ queryKey: ['competition', competitionId, 'leaderboard'], queryFn: () => getLeaderboard(competitionId), enabled: Boolean(competitionId) });
  const metrics = useQuery({ queryKey: ['competition', competitionId, 'metrics'], queryFn: () => getCompetitionMetrics(competitionId), enabled: Boolean(competitionId) });
  const [average, setAverage] = useState(false);
  const [tab, setTab] = useState<Tab>('overall');
  const [sortKey, setSortKey] = useState<SortKey>('equity');
  const [descending, setDescending] = useState(true);
  const overallTab = useRef<HTMLButtonElement>(null);
  const advancedTab = useRef<HTMLButtonElement>(null);

  const sourceRows = useMemo(() => makeRows(rowsQuery.data ?? [], metrics.data?.agents, selected), [rowsQuery.data, metrics.data, selected]);
  const rows = useMemo(() => {
    const displayRows = average ? averageRows(sourceRows) : sourceRows;
    return [...displayRows].sort((a, b) => compareRows(a, b, sortKey, descending));
  }, [sourceRows, average, sortKey, descending]);
  const winner = useMemo(() => [...rows].sort((a, b) => compareRows(a, b, 'equity', true))[0], [rows]);

  function changeSort(key: SortKey): void {
    if (sortKey === key) setDescending((value) => !value);
    else { setSortKey(key); setDescending(true); }
  }

  function moveTab(event: React.KeyboardEvent<HTMLButtonElement>): void {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const current: Tab = event.currentTarget.id === 'lb-tab-overall' ? 'overall' : 'advanced';
    const next: Tab = event.key === 'Home' ? 'overall' : event.key === 'End' ? 'advanced' : current === 'overall' ? 'advanced' : 'overall';
    setTab(next);
    (next === 'overall' ? overallTab : advancedTab).current?.focus();
  }

  return <div className="leaderboard-page">
    <header className="lb-header">
      <div className="lb-title-block"><h1>LEADERBOARD</h1></div>
      <div className="lb-controls">
        <label className="lb-scope"><span>COMPETITION:</span>
          <select value={competitionId} onChange={(event) => { if (event.target.value) navigate(`/simulation/${encodeURIComponent(event.target.value)}/leaderboard`); }} disabled={!competitions.data?.length}>
            {competitions.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="lb-average"><span>AVERAGE:</span><input type="checkbox" checked={average} onChange={(event) => setAverage(event.target.checked)} /></label>
      </div>
    </header>

    {metrics.error && <div className="lb-alert" role="status">Account metrics unavailable: {metrics.error.message}. Leaderboard equity and order data remain available.</div>}
    <QueryState loading={competitions.isLoading || rowsQuery.isLoading} error={competitions.error ?? rowsQuery.error} retry={() => void (competitions.isError ? competitions.refetch() : rowsQuery.refetch())} empty={rowsQuery.data?.length === 0 ? 'No leaderboard rows are available for this competition.' : !competitionId && !competitions.isLoading ? 'The API has no competitions yet.' : undefined}>
      {selected && rowsQuery.data && <>
        <div className="lb-tabs" role="tablist" aria-label="Leaderboard metrics">
          <button ref={overallTab} type="button" role="tab" id="lb-tab-overall" aria-selected={tab === 'overall'} aria-controls="lb-panel-overall" tabIndex={tab === 'overall' ? 0 : -1} onClick={() => setTab('overall')} onKeyDown={moveTab}>OVERALL STATS</button>
          <button ref={advancedTab} type="button" role="tab" id="lb-tab-advanced" aria-selected={tab === 'advanced'} aria-controls="lb-panel-advanced" tabIndex={tab === 'advanced' ? 0 : -1} onClick={() => setTab('advanced')} onKeyDown={moveTab}>ADVANCED ANALYTICS</button>
        </div>

        {tab === 'overall' ? <section role="tabpanel" id="lb-panel-overall" aria-labelledby="lb-tab-overall" className="lb-panel">
          <div className="lb-table-wrap"><table className="lb-table lb-overall-table">
            <thead><tr><th className="lb-rank-head">RANK</th><th>MODEL</th>
              <SortHeader label="ACCOUNT VALUE" sortKey="equity" active={sortKey} descending={descending} onSort={changeSort} />
              <SortHeader label="RETURN" sortKey="roi_pct" active={sortKey} descending={descending} onSort={changeSort} />
              <SortHeader label="TOTAL P&amp;L" sortKey="total_pnl" active={sortKey} descending={descending} onSort={changeSort} />
              <SortHeader label="FEES" sortKey="fees" active={sortKey} descending={descending} onSort={changeSort} />
              <SortHeader label="WIN RATE" sortKey="win_rate_pct" active={sortKey} descending={descending} onSort={changeSort} />
              <th title="Not published by this API">BIGGEST WIN</th><th title="Not published by this API">BIGGEST LOSS</th>
              <SortHeader label="SHARPE" sortKey="sharpe_ratio" active={sortKey} descending={descending} onSort={changeSort} />
              <SortHeader label="ORDERS" sortKey="trade_count" active={sortKey} descending={descending} onSort={changeSort} />
            </tr></thead>
            <tbody>{rows.map((row, index) => <OverallRow key={row.key} row={row} index={index} competition={selected} average={average} />)}</tbody>
          </table></div>
          <details className="lb-details"><summary>OTHER REPORTED ACCOUNT METRICS</summary><div className="lb-table-wrap"><table className="lb-table lb-detail-table"><thead><tr><th>MODEL</th><th>REALIZED P&amp;L</th><th>UNREALIZED P&amp;L</th><th>FUNDING</th><th>PROFIT FACTOR</th><th>MAX DRAWDOWN</th><th>AVG. LEVERAGE</th><th>MARGIN USED</th><th>GROSS EXPOSURE</th><th>CLOSED TRADES</th></tr></thead><tbody>{rows.map((row) => <tr key={row.key}><td>{modelLinks(row, selected, average)}</td><td>{moneyOrNA(row.values.realized_pnl)}</td><td>{moneyOrNA(row.values.unrealized_pnl)}</td><td>{moneyOrNA(row.values.funding)}</td><td>{decimalOrNA(row.values.profit_factor)}</td><td>{percentOrNA(row.values.max_drawdown_pct)}</td><td>{decimalOrNA(row.values.average_leverage)}</td><td>{moneyOrNA(row.values.current_margin_used)}</td><td>{moneyOrNA(row.values.current_gross_exposure)}</td><td>{numberOrNA(row.values.closed_trades)}</td></tr>)}</tbody></table></div></details>
        </section> : <section role="tabpanel" id="lb-panel-advanced" aria-labelledby="lb-tab-advanced" className="lb-panel">
          <div className="lb-table-wrap"><table className="lb-table lb-advanced-table">
            <thead><tr><th className="lb-rank-head">RANK</th><th>MODEL</th><th>ACCT VALUE</th>
              <th title="Average trade size">AVG TRADE SIZE</th><th title="Median trade size">MED TRADE SIZE</th><th title="Average hold">AVG HOLD</th><th title="Median hold">MED HOLD</th><th>% LONG</th><th title="Expectancy">EXP</th><th title="Median leverage">MED LEV</th>
              <SortHeader label="AVG LEV" sortKey="average_leverage" active={sortKey} descending={descending} onSort={changeSort} />
              <th title="Average confidence">AVG CONF</th><th title="Median confidence">MED CONF</th>
            </tr></thead>
            <tbody>{rows.map((row, index) => <tr key={row.key} className={index === 0 ? 'lb-top-row' : undefined} style={rowTint(row, selected)}><td className="lb-rank">{String(index + 1).padStart(2, '0')}</td><td className="lb-model-column">{modelLinks(row, selected, average)}</td><td className="lb-num">{moneyOrNA(row.values.equity)}</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-num">{decimalOrNA(row.values.average_leverage)}</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td></tr>)}</tbody>
          </table></div>
          <details className="lb-details"><summary>OTHER REPORTED ACCOUNT METRICS</summary><div className="lb-table-wrap"><table className="lb-table lb-detail-table"><thead><tr><th>MODEL</th><th>EQUITY</th><th>RETURN</th><th>WIN RATE</th><th>SHARPE</th><th>PROFIT FACTOR</th><th>MAX DRAWDOWN</th><th>ORDERS</th></tr></thead><tbody>{rows.map((row) => <tr key={row.key}><td>{modelLinks(row, selected, average)}</td><td>{moneyOrNA(row.values.equity)}</td><td>{percentOrNA(row.values.roi_pct)}</td><td>{percentOrNA(row.values.win_rate_pct)}</td><td>{decimalOrNA(row.values.sharpe_ratio, 3)}</td><td>{decimalOrNA(row.values.profit_factor)}</td><td>{percentOrNA(row.values.max_drawdown_pct)}</td><td>{numberOrNA(row.values.trade_count)}</td></tr>)}</tbody></table></div><p className="lb-inline-note">Win rate and Sharpe averages are arithmetic means of published per-account values, not pooled metrics. Averages include only non-null returned values.</p></details>
        </section>}

        <section className="lb-lower" aria-label="Leading account and model comparison">
          <article className="lb-winner">
            {winner ? <><h2>WINNING MODEL</h2><p className="lb-winner-name">{modelLinks(winner, selected, average, true)}</p><span className="lb-stat-caption">TOTAL EQUITY</span><div className="lb-winner-equity">{moneyOrNA(winner.values.equity)}</div><div className="lb-winner-stat"><span>TOTAL P&amp;L</span><b className={signClass(winner.values.total_pnl)}>{moneyOrNA(winner.values.total_pnl)}</b></div></> : <p>No ranked accounts.</p>}
          </article>
          <article className="lb-comparison">
            <div className="lb-comparison-heading"><h2>MODEL COMPARISON</h2><span className="lb-chart-unit">MARKED EQUITY · USD</span></div>
            <div className="lb-chart" role="img" aria-label={`Marked equity comparison for ${rows.length} leaderboard rows`}>
              {rows.map((row) => <div className="lb-chart-item" key={row.key} title={`${row.provider} ${row.model}: ${moneyOrNA(row.values.equity)}`}>
                <span className="lb-chart-value">{compactMoney(row.values.equity)}</span>
                <div className="lb-chart-track"><i style={{ height: `${barHeight(row.values.equity, rows)}%`, backgroundColor: row.agentIds[0] ? modelColor(selected.agents, row.agentIds[0]) : '#333' }}><b>{row.agentIds[0] ? modelMarker(selected.agents, row.agentIds[0]) : '·'}</b></i></div>
                <span className="lb-chart-name">{row.model}</span><small>{average ? `N=${row.members}` : row.provider}</small>
              </div>)}
            </div>
            <div className="lb-chart-axis"><span>0</span><span>Starting capital {money(selected.initial_balance)}</span><span>USD</span></div>
          </article>
        </section>
        <footer className="lb-footnote"><span>NOTE:</span><span>{average ? 'Values are arithmetic means by exact provider and model within this competition; null values are excluded.' : 'One account per row.'} Total P&amp;L = marked equity − starting capital. ORDERS counts order records. N/A means the public API has no value for that metric.</span><Link to={`/simulation/${encodeURIComponent(selected.id)}`}>OPEN COMPETITION RECORD ↗</Link></footer>
      </>}
    </QueryState>
  </div>;
}

function OverallRow({ row, index, competition, average }: { row: DisplayRow; index: number; competition: Competition; average: boolean }): React.JSX.Element {
  return <tr className={index === 0 ? 'lb-top-row' : undefined} style={rowTint(row, competition)}>
    <td className="lb-rank">{String(index + 1).padStart(2, '0')}</td><td className="lb-model-column">{modelLinks(row, competition, average)}</td>
    <td className="lb-num lb-equity">{moneyOrNA(row.values.equity)}</td><td className={signClass(row.values.roi_pct)}>{percentOrNA(row.values.roi_pct)}</td><td className={signClass(row.values.total_pnl)}>{moneyOrNA(row.values.total_pnl)}</td><td className="lb-num">{moneyOrNA(row.values.fees)}</td><td className="lb-num">{percentOrNA(row.values.win_rate_pct)}</td><td className="lb-na">N/A</td><td className="lb-na">N/A</td><td className="lb-num">{decimalOrNA(row.values.sharpe_ratio, 3)}</td><td className="lb-num">{tradeCountFormat(row.values.trade_count, row.members > 1)}</td>
  </tr>;
}

function SortHeader({ label, sortKey, active, descending, onSort }: { label: string; sortKey: SortKey; active: SortKey; descending: boolean; onSort: (key: SortKey) => void }): React.JSX.Element {
  return <th aria-sort={active === sortKey ? descending ? 'descending' : 'ascending' : 'none'}><button className="lb-sort" type="button" onClick={() => onSort(sortKey)}>{label}{active === sortKey ? descending ? ' ↓' : ' ↑' : ''}</button></th>;
}

function makeRows(rows: LeaderboardRow[], metrics: AgentMetrics[] | undefined, competition: Competition | undefined): DisplayRow[] {
  if (!competition) return [];
  return rows.map((row) => {
    const agent = competition.agents.find((candidate) => candidate.id === row.agent_id);
    const metric = metrics?.find((candidate) => candidate.agent_id === row.agent_id);
    const equity = numeric(row.equity);
    const initial = numeric(competition.initial_balance);
    const values: Values = {
      equity,
      roi_pct: numeric(row.roi_pct),
      total_pnl: equity === null || initial === null ? null : equity - initial,
      fees: numeric(row.fees),
      win_rate_pct: numeric(metric?.win_rate_pct),
      sharpe_ratio: numeric(metric?.sharpe_ratio),
      trade_count: row.trade_count,
      average_leverage: numeric(metric?.average_leverage),
      realized_pnl: numeric(row.realized_pnl),
      unrealized_pnl: numeric(row.unrealized_pnl),
      funding: numeric(row.funding),
      profit_factor: numeric(metric?.profit_factor),
      max_drawdown_pct: numeric(metric?.max_drawdown_pct),
      current_margin_used: numeric(metric?.current_margin_used),
      current_gross_exposure: numeric(metric?.current_gross_exposure),
      closed_trades: metric?.closed_trades ?? null,
      winning_trades: metric?.winning_trades ?? null,
      losing_trades: metric?.losing_trades ?? null,
    };
    return { key: row.agent_id, name: agent?.name ?? row.agent_name, provider: agent?.provider ?? 'Unknown provider', model: agent?.model ?? row.model, agentIds: [row.agent_id], values, members: 1 };
  });
}

export function averageRows(rows: DisplayRow[]): DisplayRow[] {
  const groups = new Map<string, DisplayRow[]>();
  for (const row of rows) {
    const groupKey = `${row.provider}\u0000${row.model}`;
    groups.set(groupKey, [...(groups.get(groupKey) ?? []), row]);
  }
  return [...groups.entries()].map(([groupKey, members]) => {
    const template = members[0];
    if (!template) return null;
    function mean(key: keyof Values): number | null {
      const present = members.map((member) => member.values[key]).filter((value): value is number => value !== null && Number.isFinite(value));
      return present.length ? present.reduce((total, value) => total + value, 0) / present.length : null;
    }
    const values: Values = {
      equity: mean('equity'), roi_pct: mean('roi_pct'), total_pnl: mean('total_pnl'), fees: mean('fees'),
      win_rate_pct: mean('win_rate_pct'), sharpe_ratio: mean('sharpe_ratio'), trade_count: mean('trade_count'),
      average_leverage: mean('average_leverage'), realized_pnl: mean('realized_pnl'), unrealized_pnl: mean('unrealized_pnl'),
      funding: mean('funding'), profit_factor: mean('profit_factor'), max_drawdown_pct: mean('max_drawdown_pct'),
      current_margin_used: mean('current_margin_used'), current_gross_exposure: mean('current_gross_exposure'),
      closed_trades: mean('closed_trades'), winning_trades: mean('winning_trades'), losing_trades: mean('losing_trades'),
    };
    return { ...template, key: groupKey, name: template.model, agentIds: members.flatMap((member) => member.agentIds), values, members: members.length };
  }).filter((row): row is DisplayRow => row !== null);
}

export function compareRows(a: DisplayRow, b: DisplayRow, key: SortKey, descending: boolean): number {
  const left = a.values[key];
  const right = b.values[key];
  if (left === null) return right === null ? a.key.localeCompare(b.key) : 1;
  if (right === null) return -1;
  return (descending ? -1 : 1) * (left - right) || a.key.localeCompare(b.key);
}

function modelLinks(row: DisplayRow, competition: Competition, average = false, baseModelOnly = false): React.JSX.Element {
  const firstId = row.agentIds[0];
  const displayName = average || baseModelOnly ? row.model : `${row.name} · ${competition.name}`;
  return <span className="lb-model-cell">
    {firstId ? <Link title={displayName} to={`/simulation/${encodeURIComponent(competition.id)}/models/${encodeURIComponent(firstId)}`} className={`lb-model-link ${modelToneClass(competition.agents, firstId)}`}><i className="lb-model-mark" style={{ backgroundColor: modelColor(competition.agents, firstId) }} />{displayName}</Link> : <span title={displayName} className="lb-model-link">{displayName}</span>}
    {row.members > 1 && <details className="lb-members"><summary>N={row.members}</summary><span>{row.agentIds.map((id) => {
      const agent = competition.agents.find((candidate) => candidate.id === id);
      return <Link key={id} title={`Open ${agent?.name ?? id}`} to={`/simulation/${encodeURIComponent(competition.id)}/models/${encodeURIComponent(id)}`}>{agent?.name ?? id}</Link>;
    })}</span></details>}
    <small>{row.members > 1 ? row.provider : `${row.provider} · ${row.model}`}</small>
  </span>;
}

function rowTint(row: DisplayRow, competition: Competition): React.CSSProperties {
  const agentId = row.agentIds[0];
  const color = agentId ? modelColor(competition.agents, agentId) : '#aaaaaa';
  return { backgroundColor: `${color}12` };
}

function numeric(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}
function moneyOrNA(value: number | null): string { return value === null ? 'N/A' : money(value); }
function decimalOrNA(value: number | null, digits = 2): string { return value === null ? 'N/A' : decimal(value, digits); }
function percentOrNA(value: number | null): string { return value === null ? 'N/A' : percent(value); }
function numberOrNA(value: number | null): string { return value === null ? 'N/A' : decimal(value, 0); }
function tradeCountFormat(value: number | null, averaged: boolean): string { return value === null ? 'N/A' : decimal(value, averaged ? 2 : 0); }
function signClass(value: number | null): string { return `lb-num ${value === null || value === 0 ? '' : value > 0 ? 'is-positive' : 'is-negative'}`; }
function compactMoney(value: number | null): string { return value === null ? 'N/A' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value); }
function barHeight(value: number | null, rows: DisplayRow[]): number {
  const max = Math.max(0, ...rows.map((row) => row.values.equity ?? 0));
  return value === null || max <= 0 ? 0 : Math.max(3, Math.round((value / max) * 100));
}
