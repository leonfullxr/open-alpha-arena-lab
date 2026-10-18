import { useMemo, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { FAMILY_COLORS } from '../geometry';
import { AssetIcon } from './asset-action-icons';
import type { Agent, Benchmark, EquityPoint, EquityRange } from './api';
import { money, timestamp } from './ui';

type ChartPoint = { round: number; timestamp: string; values: Map<string, number> };
type ChartRow = { round: number; timestamp: string; [agentId: string]: string | number };
type TooltipEntry = { dataKey?: string; value?: string | number; color?: string; payload?: ChartRow };
type EquityTooltipProps = { active?: boolean; payload?: TooltipEntry[]; agents: Agent[]; benchmark?: Benchmark | null };
const colors = FAMILY_COLORS;

export function EquityChart({ agents, rows, initialBalance, sampleCount, sampled, range, onRangeChange, benchmark }: { agents: Agent[]; rows: EquityPoint[]; initialBalance: string; sampleCount: number; sampled: boolean; range: EquityRange; onRangeChange: (range: EquityRange) => void; benchmark?: Benchmark | null }): React.JSX.Element {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const allPoints = useMemo(() => mergeEquity(rows), [rows]);
  const points = allPoints;
  const visibleAgents = agents.filter((agent) => enabled[agent.id] !== false);
  const chartRows = useMemo<ChartRow[]>(() => points.map((point) => ({ round: point.round, timestamp: point.timestamp, ...Object.fromEntries(point.values) })), [points]);
  const values = visibleAgents.flatMap((agent) => chartRows.flatMap((point) => {
    const value = point[agent.id];
    return typeof value === 'number' ? [value] : [];
  }));
  const baseline = Number(initialBalance);
  const min = Math.min(baseline, ...values);
  const max = Math.max(baseline, ...values);
  const padding = Math.max(1, (max - min) * .08);
  const low = min - padding;
  const high = max + padding;

  return <section className="equity-panel" aria-labelledby="equity-title">
    <div className="panel-heading"><div><p className="terminal-eyebrow">Account value · USD</p><h2 id="equity-title">Total equity</h2></div><div className="range-control" role="group" aria-label="Chart time range">
      {(['ALL', '72H', '24H'] as const).map((item) => <button key={item} className={range === item ? 'is-selected' : ''} aria-pressed={range === item} onClick={() => onRangeChange(item)}>{item === 'ALL' ? 'All time' : item === '72H' ? '72 hours' : '24 hours'}</button>)}
    </div></div>
    <div className="chart-meta"><span>{sampled ? `Sampled view · ${rows.length} plotted points from ${sampleCount} raw equity rows` : `${sampleCount} equity rows · ${range}`}</span><span>Initial account capital: {money(initialBalance)}</span></div>
    <div className="equity-plot-wrap">
      {points.length === 0 ? <div className="query-state">This competition has no equity samples.</div> : <div className="equity-chart-canvas" role="group" aria-label="Equity comparison chart. Use arrow keys to inspect values.">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartRows} margin={{ top: 14, right: 12, left: 4, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="var(--line-soft)" />
            <XAxis dataKey="round" tickFormatter={(round: number) => `R${round}`} tick={{ fill: 'var(--ink-label)', fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis domain={[low, high]} tickFormatter={(value: number) => money(value)} tick={{ fill: 'var(--ink-label)', fontSize: 11 }} tickLine={false} axisLine={false} width={78} />
            <ReferenceLine y={baseline} stroke="var(--ink-label)" strokeDasharray="4 4" />
            <Tooltip content={<EquityTooltip agents={visibleAgents} benchmark={benchmark} />} cursor={{ stroke: 'var(--ink-label)', strokeDasharray: '3 3' }} />
            {visibleAgents.map((agent) => <Line key={agent.id} type="linear" dataKey={agent.id} name={agent.name} stroke={colors[agents.findIndex((entry) => entry.id === agent.id) % colors.length]} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 1 }} connectNulls={false} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>}
    </div>
    <div className="equity-legend" role="group" aria-label="Toggle account series">
      {agents.map((agent, index) => <label key={agent.id}><input type="checkbox" checked={enabled[agent.id] !== false} onChange={(event) => setEnabled((current) => ({ ...current, [agent.id]: event.target.checked }))} /><i style={{ backgroundColor: colors[index % colors.length] }} />{agent.name}<span>{money(points.at(-1)?.values.get(agent.id) ?? NaN)}</span></label>)}
    </div>
    <p className="chart-note">{benchmark ? `${benchmark.label} is reported as a period-end value; no intraperiod benchmark series is available.` : 'Benchmark data is unavailable for this competition.'}</p>
    <table className="visually-hidden"><caption>Latest returned account equity</caption><thead><tr><th>Account</th><th>Equity</th></tr></thead><tbody>{agents.map((agent) => <tr key={agent.id}><th>{agent.name}</th><td>{money(points.at(-1)?.values.get(agent.id) ?? NaN)}</td></tr>)}</tbody></table>
  </section>;
}

function EquityTooltip({ active, payload, agents, benchmark }: EquityTooltipProps): React.JSX.Element | null {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return <div className="equity-tooltip"><b>{timestamp(point.timestamp)} · round {point.round}</b>{payload?.map((entry) => {
    if (entry.value === undefined || entry.dataKey === undefined) return null;
    const agent = agents.find((item) => item.id === entry.dataKey);
    if (!agent) return null;
    return <span key={entry.dataKey}><i style={{ backgroundColor: entry.color }} />{agent.name}<strong>{money(entry.value)}</strong></span>;
  })}{benchmark && <span><i className="benchmark-swatch" /><AssetIcon symbol={benchmark.symbol} size={14} /> period-end<strong>{money(benchmark.equity)}</strong></span>}</div>;
}

function mergeEquity(rows: EquityPoint[]): ChartPoint[] {
  const byRound = new Map<number, ChartPoint>();
  for (const row of rows) {
    const point = byRound.get(row.round) ?? { round: row.round, timestamp: row.timestamp, values: new Map<string, number>() };
    point.values.set(row.agent_id, Number(row.equity));
    byRound.set(row.round, point);
  }
  return [...byRound.values()].sort((a, b) => a.round - b.round);
}
