import { useMemo, useState } from 'react';
import type { Agent, Benchmark, EquityPoint, EquityRange } from './api';
import { money, timestamp } from './ui';

type ChartPoint = { round: number; timestamp: string; values: Map<string, number> };
const colors = ['#2e7db5', '#e5484d', '#46a758', '#f26a2e', '#9b72cf', '#c8961d'];
const plot = { left: 78, right: 976, top: 28, bottom: 316 };

export function EquityChart({ agents, rows, initialBalance, sampleCount, sampled, range, onRangeChange, benchmark }: { agents: Agent[]; rows: EquityPoint[]; initialBalance: string; sampleCount: number; sampled: boolean; range: EquityRange; onRangeChange: (range: EquityRange) => void; benchmark?: Benchmark | null }): React.JSX.Element {
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [activePoint, setActivePoint] = useState<number | null>(null);
  const allPoints = useMemo(() => mergeEquity(rows), [rows]);
  const points = allPoints;
  const visibleAgents = agents.filter((agent) => enabled[agent.id] !== false);
  const values = visibleAgents.flatMap((agent) => points.flatMap((point) => {
    const value = point.values.get(agent.id);
    return value === undefined ? [] : [value];
  }));
  const baseline = Number(initialBalance);
  const min = Math.min(baseline, ...values);
  const max = Math.max(baseline, ...values);
  const padding = Math.max(1, (max - min) * .08);
  const low = min - padding;
  const high = max + padding;
  const y = (value: number): number => plot.bottom - (value - low) / Math.max(1, high - low) * (plot.bottom - plot.top);
  const x = (index: number): number => points.length < 2 ? (plot.left + plot.right) / 2 : plot.left + index / (points.length - 1) * (plot.right - plot.left);
  const selectedIndex = activePoint === null ? null : Math.min(points.length - 1, Math.max(0, activePoint));
  const selected = selectedIndex === null ? undefined : points[selectedIndex];

  function hoverAt(clientX: number, rect: DOMRect): void {
    if (points.length < 2) { setActivePoint(points.length ? 0 : null); return; }
    const svgRatio = (clientX - rect.left) / rect.width * 1000;
    const ratio = Math.min(1, Math.max(0, (svgRatio - plot.left) / (plot.right - plot.left)));
    setActivePoint(Math.round(ratio * (points.length - 1)));
  }

  return <section className="equity-panel" aria-labelledby="equity-title">
    <div className="panel-heading"><div><p className="terminal-eyebrow">ACCOUNT VALUE · USD</p><h2 id="equity-title">Total equity</h2></div><div className="range-control" role="group" aria-label="Chart time range">
      {(['ALL', '72H', '24H'] as const).map((item) => <button key={item} className={range === item ? 'is-selected' : ''} aria-pressed={range === item} onClick={() => { onRangeChange(item); setActivePoint(null); }}>{item}</button>)}
    </div></div>
    <div className="chart-meta"><span>{sampled ? `Sampled view · ${rows.length} plotted points from ${sampleCount} raw equity rows` : `${sampleCount} equity rows in ${range}`}</span><span>Initial account capital: {money(initialBalance)}</span></div>
    <div className="equity-plot-wrap">
      {points.length === 0 ? <div className="query-state">This competition has no equity samples.</div> : <svg className="equity-plot" viewBox="0 0 1000 360" role="img" aria-label="Account equity by recorded round. Use the arrow keys to inspect values." tabIndex={0}
        onPointerMove={(event) => hoverAt(event.clientX, event.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setActivePoint(null)}
        onKeyDown={(event) => { if (event.key === 'ArrowRight') { event.preventDefault(); setActivePoint((current) => Math.min(points.length - 1, (current ?? 0) + 1)); } if (event.key === 'ArrowLeft') { event.preventDefault(); setActivePoint((current) => Math.max(0, (current ?? points.length - 1) - 1)); } }}>
        {[0, 1, 2, 3, 4].map((tick) => {
          const amount = high - (high - low) * tick / 4;
          const yy = plot.top + (plot.bottom - plot.top) * tick / 4;
          return <g key={tick}><line x1={plot.left} x2={plot.right} y1={yy} y2={yy} className="chart-gridline" /><text x={plot.left - 12} y={yy + 4} textAnchor="end" className="chart-axis-label">{money(amount)}</text></g>;
        })}
        <line x1={plot.left} x2={plot.right} y1={y(baseline)} y2={y(baseline)} className="chart-baseline" />
        {visibleAgents.map((agent) => {
          const coordinates = points.flatMap((point, index) => {
            const value = point.values.get(agent.id);
            return value === undefined ? [] : [{ x: x(index), y: y(value) }];
          });
          const path = coordinates.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ');
          return path ? <path key={agent.id} d={path} className="equity-line" style={{ stroke: colors[agents.findIndex((entry) => entry.id === agent.id) % colors.length] }} /> : null;
        })}
        {selected && selectedIndex !== null && <>
          <line x1={x(selectedIndex)} x2={x(selectedIndex)} y1={plot.top} y2={plot.bottom} className="chart-crosshair" />
          {visibleAgents.map((agent) => {
            const value = selected.values.get(agent.id);
            if (value === undefined) return null;
            return <circle key={agent.id} cx={x(selectedIndex)} cy={y(value)} r="4.5" className="chart-point" style={{ fill: colors[agents.findIndex((entry) => entry.id === agent.id) % colors.length] }} />;
          })}
        </>}
        <text x={plot.left} y="346" className="chart-axis-label">{points[0] ? `ROUND ${points[0].round} · ${shortDate(points[0].timestamp)}` : ''}</text>
        <text x={plot.right} y="346" textAnchor="end" className="chart-axis-label">{points.at(-1) ? `ROUND ${points.at(-1)!.round} · ${shortDate(points.at(-1)!.timestamp)}` : ''}</text>
      </svg>}
      {selected && <div className="equity-tooltip" aria-live="polite"><b>{timestamp(selected.timestamp)} · round {selected.round}</b>{visibleAgents.map((agent) => <span key={agent.id}><i style={{ backgroundColor: colors[agents.findIndex((entry) => entry.id === agent.id) % colors.length] }} />{agent.name}<strong>{money(selected.values.get(agent.id) ?? NaN)}</strong></span>)}{benchmark && <span><i className="benchmark-swatch" />BTC period-end<strong>{money(benchmark.equity)}</strong></span>}</div>}
    </div>
    <div className="equity-legend" aria-label="Toggle account series">
      {agents.map((agent, index) => <label key={agent.id}><input type="checkbox" checked={enabled[agent.id] !== false} onChange={(event) => setEnabled((current) => ({ ...current, [agent.id]: event.target.checked }))} /><i style={{ backgroundColor: colors[index % colors.length] }} />{agent.name}<span>{money(points.at(-1)?.values.get(agent.id) ?? NaN)}</span></label>)}
    </div>
    <p className="chart-note">{benchmark ? `BTC buy & hold finished at ${money(benchmark.equity)} (${Number(benchmark.roi_pct).toFixed(2)}%) after ${(Number(benchmark.fee_rate) * 100).toFixed(2)}% fees and ${Number(benchmark.slippage_bps).toFixed(1)} bps slippage. The API provides a summary, not an intraperiod benchmark series.` : 'BTC buy-and-hold summary is unavailable for this competition.'}</p>
    <table className="visually-hidden"><caption>Latest returned account equity</caption><thead><tr><th>Account</th><th>Equity</th></tr></thead><tbody>{agents.map((agent) => <tr key={agent.id}><th>{agent.name}</th><td>{money(points.at(-1)?.values.get(agent.id) ?? NaN)}</td></tr>)}</tbody></table>
  </section>;
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

function shortDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}
