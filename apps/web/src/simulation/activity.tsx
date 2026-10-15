import { useEffect, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getArtifact, getDecisionHistory, getPositionHistory, getTradeHistory, type Agent, type Decision, type Position, type Trade } from './api';
import { decimal, money } from './ui';

export type ActivityTab = 'Live Trades' | 'Model Chat' | 'Positions' | 'README.TXT';
const PAGE_SIZE = 20;

export function ActivityPanel({ tab, competitionId, agentId, agents = [] }: {
  tab: ActivityTab;
  competitionId: string;
  agentId?: string;
  agents?: Agent[];
}): React.JSX.Element {
  const [symbolDraft, setSymbolDraft] = useState('');
  const [symbol, setSymbol] = useState('');
  const [agentDraft, setAgentDraft] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [symbol, selectedAgent, tab, competitionId, agentId]);
  const effectiveAgent = agentId ?? selectedAgent;
  const query = { limit: PAGE_SIZE, offset: page * PAGE_SIZE, ...(effectiveAgent ? { agent_id: effectiveAgent } : {}), ...(symbol ? { symbol } : {}) };
  const trades = useQuery({ queryKey: ['competition', competitionId, 'trades', query], queryFn: () => getTradeHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Live Trades' });
  const decisions = useQuery({ queryKey: ['competition', competitionId, 'decisions', query], queryFn: () => getDecisionHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Model Chat' });
  const positions = useQuery({ queryKey: ['competition', competitionId, 'positions', query], queryFn: () => getPositionHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Positions' });
  const active = tab === 'Live Trades' ? trades : tab === 'Model Chat' ? decisions : tab === 'Positions' ? positions : undefined;
  const total = active?.data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  function applyFilter(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSymbol(symbolDraft.trim().toUpperCase());
  }

  return <section className="activity-panel" aria-labelledby="activity-title">
    <div className="panel-heading"><div><p className="terminal-eyebrow">COMPETITION RECORD</p><h2 id="activity-title">{tab}</h2></div>{tab !== 'README.TXT' && <form className="filter-control" onSubmit={applyFilter}>
      {!agentId && agents.length > 0 && <><label htmlFor="activity-agent">Model</label><select id="activity-agent" value={agentDraft} onChange={(event) => { setAgentDraft(event.target.value); setSelectedAgent(event.target.value); }}><option value="">All models</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></>}
      <label htmlFor="activity-symbol">Symbol</label><input id="activity-symbol" value={symbolDraft} onChange={(event) => setSymbolDraft(event.target.value)} placeholder="All" maxLength={24} />
      <button type="submit">Apply</button>
    </form>}</div>
    {tab === 'README.TXT' ? <Readme /> : active?.isLoading ? <div className="query-state" role="status">Loading records…</div> : active?.error ? <div className="query-error" role="alert">{active.error.message} <button onClick={() => void active.refetch()}>Retry</button></div> : <>
      {tab === 'Live Trades' && <TradesTable rows={trades.data?.items ?? []} />}
      {tab === 'Model Chat' && <DecisionsList rows={decisions.data?.items ?? []} />}
      {tab === 'Positions' && <PositionsTable rows={positions.data?.items ?? []} />}
      {active?.isFetching && <p className="complete-history-note" role="status">Updating this page…</p>}
      {pageCount > 1 && <div className="history-pagination"><span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</span><div><button disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button><button disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Next</button></div></div>}
      <p className="complete-history-note">Showing server-filtered records{effectiveAgent ? ` for ${agents.find((agent) => agent.id === effectiveAgent)?.name ?? 'this model'}` : ''}{symbol ? ` for ${symbol}` : ''}; {total} records match.</p>
    </>}
  </section>;
}

function TradesTable({ rows }: { rows: Trade[] }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No trade fills match this filter.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Model</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Fill price</th><th>Fee</th><th>Order status</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.order_id}-${index}`}><td>{row.agent_name}</td><td>{row.symbol}</td><td>{row.side}</td><td>{decimal(row.quantity, 6)}</td><td>{money(row.price)}</td><td>{money(row.fee)}</td><td>{row.status}</td></tr>)}</tbody></table></div>;
}

function PositionsTable({ rows }: { rows: Position[] }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No positions match this filter.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Model</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Average entry</th><th>Reserved margin</th><th>Stop / take profit</th><th>State</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.agent_id}-${row.symbol}-${index}`}><td>{row.agent_name}</td><td>{row.symbol}</td><td>{row.side}</td><td>{decimal(row.quantity, 6)}</td><td>{money(row.average_entry)}</td><td>{money(row.reserved_margin)}</td><td>{row.stop_loss ? money(row.stop_loss) : '—'} / {row.take_profit ? money(row.take_profit) : '—'}</td><td>{row.state}</td></tr>)}</tbody></table></div>;
}

function DecisionsList({ rows }: { rows: Decision[] }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No model decisions match this filter.</div>;
  return <div className="decision-list">{rows.map((decision) => <DecisionRecord key={decision.id} decision={decision} />)}</div>;
}

function DecisionRecord({ decision }: { decision: Decision }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const artifact = useQuery({ queryKey: ['artifact', decision.id], queryFn: () => getArtifact(decision.id), enabled: open });
  const promptBytes = artifact.data ? decodeBase64(artifact.data.prompt_bytes_base64) : null;
  const outputBytes = artifact.data?.output_publicly_releasable ? decodeBase64(artifact.data.output_bytes_base64) : null;
  const usage = Object.entries(decision.usage).map(([name, value]) => `${name}: ${value}`).join(' · ') || 'Not reported';
  return <article className="decision-record">
    <button className="decision-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span><b>{decision.agent_name}</b><small>{decision.provider} · {decision.model} · round {decision.round}</small></span>
      <span className="decision-action">{decision.action ?? 'No action'} {decision.symbol ?? ''} {decision.quantity ?? ''}</span>
      <span className="decision-hashes">Prompt {shortHash(decision.prompt_sha256)} · Output {shortHash(decision.output_sha256)}</span>
      <span aria-hidden="true">{open ? '−' : '+'}</span>
    </button>
    {decision.justification && <p className="decision-justification">{decision.justification}</p>}
    {open && <div className="decision-detail">
      {decision.market_summary && <p><b>Visible market summary</b><br />{decision.market_summary}</p>}
      <dl className="decision-evidence"><div><dt>Validation</dt><dd>{decision.validation_status}</dd></div><div><dt>Execution result</dt><dd>{decision.execution_result ?? 'Not reported'}</dd></div><div><dt>Error code</dt><dd>{decision.error_code ?? 'None reported'}</dd></div><div><dt>Latency</dt><dd>{decision.latency_ms === null || decision.latency_ms === undefined ? 'Not reported' : `${decision.latency_ms} ms`}</dd></div><div><dt>Estimated provider cost</dt><dd>{decision.estimated_cost_usd ? money(decision.estimated_cost_usd) : 'Not reported'}</dd></div><div><dt>Provider usage</dt><dd>{usage}</dd></div></dl>
      {decision.validation_errors.length > 0 && <section className="proposal-evidence"><h3>Validation details</h3><ul>{decision.validation_errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}</ul></section>}
      {decision.proposals.length > 0 && <section className="proposal-evidence"><h3>Recorded proposals</h3>{decision.proposals.map((proposal, index) => <article key={`${proposal.symbol}-${index}`}><header><strong>{proposal.action} {proposal.symbol}</strong><span>Risk: {proposal.risk_decision ?? 'Not evaluated'}</span></header><p>{proposal.justification}</p><dl className="decision-evidence"><div><dt>Quantity</dt><dd>{proposal.quantity}</dd></div><div><dt>Confidence</dt><dd>{proposal.confidence ?? 'Not reported'}</dd></div><div><dt>Leverage</dt><dd>{proposal.leverage ?? 'Not reported'}</dd></div><div><dt>Stop / take profit</dt><dd>{proposal.stop_loss ?? '—'} / {proposal.take_profit ?? '—'}</dd></div><div><dt>Invalidation</dt><dd>{proposal.invalidation ?? 'Not reported'}</dd></div></dl>{proposal.risk_reasons.length > 0 && <ul>{proposal.risk_reasons.map((reason, reasonIndex) => <li key={`${reasonIndex}-${reason}`}>{reason}</li>)}</ul>}</article>)}</section>}
      {artifact.isLoading && <p role="status">Loading exact artifact bytes…</p>}
      {artifact.error && <div className="query-error" role="alert">{artifact.error.message} <button onClick={() => void artifact.refetch()}>Retry</button></div>}
      {promptBytes && <div className="artifact-grid">
        <ArtifactText title="Prompt bytes" bytes={promptBytes} hash={artifact.data?.prompt_sha256 ?? 'unknown'} />
        {outputBytes && artifact.data && <ArtifactText title="Provider output bytes" bytes={outputBytes} hash={artifact.data.output_sha256} />}
      </div>}
      {artifact.data && !artifact.data.output_publicly_releasable && <p className="availability-note">Provider output withheld from public display. SHA-256 {artifact.data.output_sha256} remains available for audit.</p>}
    </div>}
  </article>;
}

function ArtifactText({ title, bytes, hash }: { title: string; bytes: Uint8Array; hash: string }): React.JSX.Element {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  function download(): void {
    const blob = new Blob([bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = `${title.toLowerCase().replace(/\s+/g, '-')}-${hash}.bin`;
    anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }
  return <section className="artifact-block"><div><h3>{title}</h3><button className="small-button" onClick={download}>Download original bytes</button></div><code>SHA-256 {hash}</code><pre>{text || '[Empty artifact]'}</pre></section>;
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function shortHash(value: string | null): string {
  return value ? `${value.slice(0, 12)}…` : 'Not stored';
}

function Readme(): React.JSX.Element {
  return <div className="readme-content">
    <h3>Reading this competition</h3>
    <p>Records are served by the public API. Finished paper runs use saved market and account records; their source label identifies the run. They are not a live trading session.</p>
    <h3>Profiles</h3>
    <p><code>alpha_2025_baseline</code> uses a shared market snapshot, prompt, rules, six-symbol universe, and execution quote set. Each account starts with $10,000 virtual capital and the baseline uses 180-second rounds. <code>research_extended</code> ranks changed methods separately.</p>
    <h3>Equity and benchmark</h3>
    <p>Account equity comes from recorded samples. The benchmark summary uses the API's BTC start and end quotes, fee rate, and slippage assumption; the API does not expose an intraperiod BTC series for charting. Account fees come directly from the API.</p>
    <h3>Metrics and invocation evidence</h3>
    <p>Win rate, profit factor, drawdown, Sharpe, leverage, margin, usage, cost, latency, and execution result are shown only when the metrics and decision records provide them. The public decision explanation is not hidden provider reasoning.</p>
    <h3>Artifacts</h3>
    <p>Prompt downloads preserve exact bytes. Provider output is downloadable only when the API marks it publicly releasable; withheld output retains its SHA-256 for audit.</p>
  </div>;
}
