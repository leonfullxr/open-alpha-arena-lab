import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getFundingEvidence, getFundingHistory, getPositionHistory, getTradeHistory, type Agent, type FundingEvidence, type FundingPayment, type Position, type Trade } from './api';
import { DecisionFeed } from './chat';
import { RulesEvidence, useRulesArtifact } from './rules';
import { decimal, decodeBase64Safely, money, sha256Hex, shortHash, timestamp } from './ui';

export type ActivityTab = 'Live Trades' | 'Model Chat' | 'Positions' | 'README.TXT';
const PAGE_SIZE = 20;

export function ActivityPanel({ tab, competitionId, agentId, agents = [], highlightDecisionId, decisionRound }: {
  tab: ActivityTab;
  competitionId: string;
  agentId?: string;
  agents?: Agent[];
  highlightDecisionId?: string;
  decisionRound?: number;
}): React.JSX.Element {
  const panelId = useId().replaceAll(':', '');
  const [symbolDraft, setSymbolDraft] = useState('');
  const [symbol, setSymbol] = useState('');
  const [agentDraft, setAgentDraft] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [symbol, selectedAgent, tab, competitionId, agentId]);
  const effectiveAgent = agentId ?? selectedAgent;
  const query = { limit: PAGE_SIZE, offset: page * PAGE_SIZE, ...(effectiveAgent ? { agent_id: effectiveAgent } : {}), ...(symbol ? { symbol } : {}) };
  const trades = useQuery({ queryKey: ['competition', competitionId, 'trades', query], queryFn: () => getTradeHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Live Trades' });
  const positions = useQuery({ queryKey: ['competition', competitionId, 'positions', query], queryFn: () => getPositionHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Positions' });
  const active = tab === 'Live Trades' ? trades : tab === 'Positions' ? positions : undefined;
  const total = active?.data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  useEffect(() => {
    if (active?.data) setPage((current) => Math.min(current, Math.max(0, pageCount - 1)));
  }, [active?.data, pageCount]);
  function applyFilter(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSymbol(symbolDraft.trim().toUpperCase());
  }

  return <section className="activity-panel" aria-labelledby={`${panelId}-title`}>
    <div className="panel-heading"><div><p className="terminal-eyebrow">COMPETITION RECORD</p><h2 id={`${panelId}-title`}>{tab}</h2></div>{tab !== 'README.TXT' && tab !== 'Model Chat' && <form className="filter-control" onSubmit={applyFilter}>
      {!agentId && agents.length > 0 && <><label htmlFor={`${panelId}-agent`}>Model</label><select id={`${panelId}-agent`} value={agentDraft} onChange={(event) => { setAgentDraft(event.target.value); setSelectedAgent(event.target.value); }}><option value="">All models</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></>}
      <label htmlFor={`${panelId}-symbol`}>Symbol</label><input id={`${panelId}-symbol`} value={symbolDraft} onChange={(event) => setSymbolDraft(event.target.value)} placeholder="All" maxLength={24} />
      <button type="submit">Apply</button>
    </form>}</div>
      {tab === 'README.TXT' ? <Readme competitionId={competitionId} />
        : tab === 'Model Chat' ? <DecisionFeed competitionId={competitionId} agents={agents} agentId={agentId} badge={agentId ? 'SELECTED ACCOUNT' : undefined} highlightDecisionId={highlightDecisionId} decisionRound={decisionRound} idPrefix={`${panelId}-feed`} />
          : active?.isLoading ? <div className="query-state" role="status">Loading records…</div> : active?.error ? <div className="query-error" role="alert">{active.error.message} <button onClick={() => void active.refetch()}>Retry</button></div> : <>
      {tab === 'Live Trades' && <TradesTable rows={trades.data?.items ?? []} competitionId={competitionId} />}
      {tab === 'Positions' && <><PositionsTable rows={positions.data?.items ?? []} /><FundingSection competitionId={competitionId} agentId={effectiveAgent} symbol={symbol} /></>}
      {active?.isFetching && <p className="complete-history-note" role="status">Updating this page…</p>}
      {pageCount > 1 && <div className="history-pagination"><span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</span><div><button disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button><button disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Next</button></div></div>}
      <p className="complete-history-note">Showing server-filtered records{effectiveAgent ? ` for ${agents.find((agent) => agent.id === effectiveAgent)?.name ?? 'this model'}` : ''}{symbol ? ` for ${symbol}` : ''}; {total} records match.</p>
    </>}
  </section>;
}

function TradesTable({ rows, competitionId }: { rows: Trade[]; competitionId: string }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No trade fills match this filter.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Model</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Fill price</th><th>Fee</th><th>Order status</th><th>Evidence</th></tr></thead><tbody>{rows.map((row) => <TradeRecord key={row.fill_id} row={row} competitionId={competitionId} />)}</tbody></table></div>;
}

function TradeRecord({ row, competitionId }: { row: Trade; competitionId: string }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  return <>
    <tr><td>{row.agent_name}</td><td>{row.symbol}</td><td>{row.side}</td><td>{decimal(row.quantity, 6)}</td><td>{money(row.price)}</td><td>{money(row.fee)}</td><td>{row.status}</td><td><button className="small-button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? 'Hide' : 'Inspect'}</button></td></tr>
    {open && <tr className="trade-detail-row"><td colSpan={8}><TradeEvidence row={row} competitionId={competitionId} /></td></tr>}
  </>;
}

function TradeEvidence({ row, competitionId }: { row: Trade; competitionId: string }): React.JSX.Element {
  const quote = row.execution_quote;
  return <div className="trade-evidence-detail">
    <dl className="decision-evidence">
      <div><dt>Fill ID</dt><dd>{row.fill_id}</dd></div>
      <div><dt>Order</dt><dd>{row.order_id} · {row.order_kind} · {row.status}</dd></div>
      <div><dt>Executed · pricing clock</dt><dd>{row.executed_at ? timestamp(row.executed_at) : 'Not recorded on this legacy fill'}</dd></div>
      <div><dt>Sequence · fill ordinal</dt><dd>{row.event_sequence === null ? 'Unordered legacy fill' : `${row.event_sequence} · ${row.fill_ordinal ?? 'ordinal not recorded'}`}</dd></div>
      <div><dt>Round · proposal sequence</dt><dd>{row.round ?? 'Not linked'} · {row.proposal_sequence ?? 'Not linked'}</dd></div>
      <div><dt>Quote set</dt><dd>{row.quote_set_id ?? 'Not recorded'}</dd></div>
      <div><dt>Execution quote</dt><dd>{quote ? `Bid ${money(quote.bid)} · Ask ${money(quote.ask)} · Mark ${money(quote.mark)}` : 'No recorded quote for this fill'}</dd></div>
      <div><dt>Quote source</dt><dd>{quote ? `${timestamp(quote.source_at)} · ${quote.source_at_basis}` : 'Not recorded'}</dd></div>
    </dl>
    {row.decision_id ? <p className="trade-decision-link"><Link to={`/simulation/${encodeURIComponent(competitionId)}/models/${encodeURIComponent(row.agent_id)}?decision=${encodeURIComponent(row.decision_id)}&round=${row.round ?? ''}`}>Open linked model decision</Link><a href={`/api/v1/public/decisions/${encodeURIComponent(row.decision_id)}/artifact`} target="_blank" rel="noreferrer">Open exact decision artifact</a><code>{row.decision_id}</code></p> : <p className="availability-note">No decision link was recorded for this legacy order.</p>}
  </div>;
}

function PositionsTable({ rows }: { rows: Position[] }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No positions match this filter.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Model</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Average entry</th><th>Reserved margin</th><th>Stop / take profit</th><th>State</th><th>Lifecycle</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{row.agent_name}</td><td>{row.symbol}</td><td>{row.side}</td><td>{decimal(row.quantity, 6)}</td><td>{money(row.average_entry)}</td><td>{money(row.reserved_margin)}</td><td>{row.stop_loss ? money(row.stop_loss) : '—'} / {row.take_profit ? money(row.take_profit) : '—'}</td><td>{row.state}</td><td><details className="position-lifecycle"><summary>Times and ID</summary><code>{row.id}</code><small>Opened {timestamp(row.opened_at)}</small><small>Closed {row.closed_at ? timestamp(row.closed_at) : 'Still open'}</small></details></td></tr>)}</tbody></table></div>;
}

function FundingSection({ competitionId, agentId, symbol }: { competitionId: string; agentId?: string; symbol: string }): React.JSX.Element {
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [competitionId, agentId, symbol]);
  const query = { limit: PAGE_SIZE, offset: page * PAGE_SIZE, ...(agentId ? { agent_id: agentId } : {}), ...(symbol ? { symbol } : {}) };
  const funding = useQuery({ queryKey: ['competition', competitionId, 'funding', query], queryFn: () => getFundingHistory(competitionId, query), enabled: Boolean(competitionId) });
  const total = funding.data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  useEffect(() => {
    if (funding.data) setPage((current) => Math.min(current, Math.max(0, pageCount - 1)));
  }, [funding.data, pageCount]);

  return <section className="funding-section" aria-labelledby="funding-title">
    <div className="funding-heading"><div><p className="terminal-eyebrow">ACCOUNTING EVIDENCE</p><h3 id="funding-title">Funding history</h3></div><span>{total} records</span></div>
    {funding.isLoading ? <div className="query-state" role="status">Loading funding records…</div>
      : funding.error ? <div className="query-error" role="alert">{funding.error.message} <button onClick={() => void funding.refetch()}>Retry funding</button></div>
        : <>
          <FundingTable rows={funding.data?.items ?? []} />
          {pageCount > 1 && <div className="history-pagination"><span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</span><div><button disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button><button disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Next</button></div></div>}
          <p className="complete-history-note">Funding entries are server-filtered with the model and symbol filters above. Amounts and evidence appear only when returned by the API.</p>
        </>}
  </section>;
}

function FundingTable({ rows }: { rows: FundingPayment[] }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No funding entries match this filter.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Boundary</th><th>Model</th><th>Symbol</th><th>Status / reason</th><th>Amount</th><th>Rate</th><th>Oracle price</th><th>Source</th><th>Evidence</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}>
    <td>{timestamp(row.boundary_at)}</td><td>{row.agent_name}</td><td>{row.symbol}</td><td>{row.status}{row.reason ? <small className="funding-reason">{row.reason}</small> : null}</td><td>{row.amount === null ? 'N/A' : money(row.amount)}</td><td>{row.rate ?? 'N/A'}</td><td>{row.oracle_px === null ? 'N/A' : money(row.oracle_px)}</td><td>{row.source}</td><td><FundingEvidenceDisclosure row={row} /></td>
  </tr>)}</tbody></table></div>;
}

function FundingEvidenceDisclosure({ row }: { row: FundingPayment }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const evidence = useQuery({ queryKey: ['funding-evidence', row.evidence_id], queryFn: () => getFundingEvidence(row.evidence_id!), enabled: open && Boolean(row.evidence_id) });
  if (!row.evidence_id) return <span>{row.evidence_sha256 ? `SHA ${shortHash(row.evidence_sha256)}` : 'Not supplied'}</span>;
  return <div className="funding-evidence">
    <button className="small-button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? 'Hide record' : 'Inspect record'}</button>
    {row.evidence_sha256 && <small>SHA {shortHash(row.evidence_sha256)}</small>}
    {open && <div className="funding-evidence-detail">
      {evidence.isLoading && <p role="status">Loading evidence…</p>}
      {evidence.error && <p className="query-error" role="alert">{evidence.error.message} <button onClick={() => void evidence.refetch()}>Retry</button></p>}
      {evidence.data && <FundingEvidenceRecord evidence={evidence.data} />}
    </div>}
  </div>;
}

function FundingEvidenceRecord({ evidence }: { evidence: FundingEvidence }): React.JSX.Element {
  const decoded = useMemo(() => evidence.exact_record_base64 ? decodeBase64Safely(evidence.exact_record_base64) : null, [evidence.exact_record_base64]);
  const [actualHash, setActualHash] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setActualHash(null);
    if (decoded?.bytes) {
      void sha256Hex(decoded.bytes).then((hash) => { if (current) setActualHash(hash); });
    }
    return () => { current = false; };
  }, [decoded?.bytes]);
  const hashMatches = evidence.sha256 === null || actualHash === evidence.sha256;

  function download(): void {
    if (!decoded?.bytes || !hashMatches) return;
    const blob = new Blob([decoded.bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `funding-evidence-${evidence.id}.bin`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  return <div className="funding-record-detail">
    <dl><div><dt>Recorded boundary</dt><dd>{timestamp(evidence.boundary_at)}</dd></div><div><dt>Evidence status</dt><dd>{evidence.status}</dd></div><div><dt>Historical event</dt><dd>{evidence.history_event_at ? timestamp(evidence.history_event_at) : 'Not reported'}</dd></div><div><dt>Record SHA-256</dt><dd>{evidence.sha256 ?? 'Not supplied'}</dd></div></dl>
    {decoded?.error && <p className="query-error" role="alert">Projected record could not be decoded: {decoded.error}</p>}
    {decoded?.bytes && <>
      {evidence.sha256 && actualHash !== null && <p className={hashMatches ? 'evidence-hash-ok' : 'query-error'} role={hashMatches ? 'status' : 'alert'}>{hashMatches ? 'Projected record SHA-256 verified.' : actualHash === 'unavailable' ? 'Record hash verification is unavailable.' : 'Projected record does not match the returned SHA-256.'}</p>}
      <p className="complete-history-note">Canonical public evidence projection; raw upstream response bytes are not included.</p>
      <button className="small-button" onClick={download} disabled={!hashMatches || actualHash === 'unavailable'}>Download exact projected bytes</button>
      <pre>{new TextDecoder('utf-8', { fatal: false }).decode(decoded.bytes) || '[Empty record]'}</pre>
    </>}
    {!decoded?.bytes && !decoded?.error && <p className="availability-note">No projected record bytes were returned. The evidence reference and metadata remain available.</p>}
  </div>;
}

function Readme({ competitionId }: { competitionId: string }): React.JSX.Element {
  const rules = useRulesArtifact(competitionId);
  return <div className="readme-content">
    <h3>Reading this competition</h3>
    <p>Records are served by the public API. Finished paper runs use saved market and account records; their source label identifies the run. They are not a live trading session.</p>
    <h3>Profiles</h3>
    <p><code>alpha_2025_baseline</code> uses a shared market snapshot, prompt, rules, six-symbol universe, and execution quote set. Each account starts with $10,000 virtual capital and the baseline uses 180-second rounds. <code>research_extended</code> ranks changed methods separately.</p>
    <h3>Equity and benchmark</h3>
    <p>Account equity comes from recorded samples. The benchmark summary uses the API's BTC start and end quotes, fee rate, and slippage assumption; the API does not expose an intraperiod BTC series for charting. Account fees come directly from the API.</p>
    <h3>Fills and execution evidence</h3>
    <p>Fill details link to the recorded decision and show order kind, round and proposal sequence, fill ordinal, execution quote set, and quote values when stored. “Executed” is the pricing clock; event sequence and fill ordinal provide order. Null fields mean that older records did not store that evidence.</p>
    <h3>Metrics and invocation evidence</h3>
    <p>Win rate, profit factor, drawdown, Sharpe, leverage, margin, usage, cost, latency, and execution result are shown only when the metrics and decision records provide them. The public decision explanation is not hidden provider reasoning.</p>
    <h3>Artifacts</h3>
    <p>Prompt downloads preserve exact bytes. Provider output is downloadable only when the API marks it publicly releasable; withheld output retains its SHA-256 for audit.</p>
    <h3>Frozen competition rules</h3>
    <p>The rules record describes the limits, execution assumptions, funding policy, and evidence schema applied to this competition. The SHA-256 is checked against the exact stored bytes. Unrecorded rule fields stay identified as withheld by the API.</p>
    {rules.isLoading ? <div className="query-state" role="status">Loading frozen rules…</div>
      : rules.error ? <div className="query-error" role="alert">{rules.error.message} <button onClick={() => void rules.refetch()}>Retry rules</button></div>
        : rules.data ? <RulesEvidence artifact={rules.data} /> : null}
  </div>;
}
