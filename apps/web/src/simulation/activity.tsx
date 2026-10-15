import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getArtifact, getCompetitionRules, getDecisionHistory, getFundingEvidence, getFundingHistory, getPositionHistory, getTradeHistory, type Agent, type Decision, type FundingEvidence, type FundingPayment, type Position, type RulesArtifact, type Trade } from './api';
import { decimal, money, timestamp } from './ui';

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
  const [symbolDraft, setSymbolDraft] = useState('');
  const [symbol, setSymbol] = useState('');
  const [agentDraft, setAgentDraft] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('');
  const [page, setPage] = useState(0);
  useEffect(() => {
    const targetPage = decisionRound && highlightDecisionId ? Math.floor((decisionRound - 1) / PAGE_SIZE) : 0;
    setPage(targetPage);
  }, [symbol, selectedAgent, tab, competitionId, agentId, highlightDecisionId, decisionRound]);
  const effectiveAgent = agentId ?? selectedAgent;
  const query = { limit: PAGE_SIZE, offset: page * PAGE_SIZE, ...(effectiveAgent ? { agent_id: effectiveAgent } : {}), ...(symbol ? { symbol } : {}) };
  const trades = useQuery({ queryKey: ['competition', competitionId, 'trades', query], queryFn: () => getTradeHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Live Trades' });
  const decisions = useQuery({ queryKey: ['competition', competitionId, 'decisions', query], queryFn: () => getDecisionHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Model Chat' });
  const positions = useQuery({ queryKey: ['competition', competitionId, 'positions', query], queryFn: () => getPositionHistory(competitionId, query), enabled: Boolean(competitionId) && tab === 'Positions' });
  const active = tab === 'Live Trades' ? trades : tab === 'Model Chat' ? decisions : tab === 'Positions' ? positions : undefined;
  const total = active?.data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);
  useEffect(() => {
    if (active?.data) setPage((current) => Math.min(current, Math.max(0, pageCount - 1)));
  }, [active?.data, pageCount]);
  useEffect(() => {
    if (tab !== 'Model Chat' || !highlightDecisionId || !decisions.data?.items.some((item) => item.id === highlightDecisionId)) return;
    document.getElementById(`decision-${highlightDecisionId}`)?.scrollIntoView({ block: 'center' });
  }, [tab, highlightDecisionId, decisions.data]);

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
      {tab === 'README.TXT' ? <Readme competitionId={competitionId} /> : active?.isLoading ? <div className="query-state" role="status">Loading records…</div> : active?.error ? <div className="query-error" role="alert">{active.error.message} <button onClick={() => void active.refetch()}>Retry</button></div> : <>
      {tab === 'Live Trades' && <TradesTable rows={trades.data?.items ?? []} competitionId={competitionId} />}
      {tab === 'Model Chat' && <DecisionsList rows={decisions.data?.items ?? []} highlightDecisionId={highlightDecisionId} />}
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
      void crypto.subtle.digest('SHA-256', decoded.bytes).then((digest) => {
        const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
        if (current) setActualHash(hex);
      }).catch(() => { if (current) setActualHash('unavailable'); });
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

function DecisionsList({ rows, highlightDecisionId }: { rows: Decision[]; highlightDecisionId?: string }): React.JSX.Element {
  if (!rows.length) return <div className="query-state">No model decisions match this filter.</div>;
  return <div className="decision-list">{rows.map((decision) => <DecisionRecord key={decision.id} decision={decision} highlighted={decision.id === highlightDecisionId} />)}</div>;
}

function DecisionRecord({ decision, highlighted }: { decision: Decision; highlighted: boolean }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const artifact = useQuery({ queryKey: ['artifact', decision.id], queryFn: () => getArtifact(decision.id), enabled: open });
  const promptArtifact = artifact.data ? decodeBase64Safely(artifact.data.prompt_bytes_base64) : null;
  const outputArtifact = artifact.data?.output_publicly_releasable ? decodeBase64Safely(artifact.data.output_bytes_base64) : null;
  const usage = Object.entries(decision.usage).map(([name, value]) => `${name}: ${value}`).join(' · ') || 'Not reported';
  return <article id={`decision-${decision.id}`} className={`decision-record${highlighted ? ' decision-record--linked' : ''}`}>
    <button className="decision-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <span><b>{decision.agent_name}</b><small>{decision.provider} · {decision.model} · round {decision.round}</small></span>
      <span className="decision-action">{decision.action ?? 'No action'} {decision.symbol ?? ''} {decision.quantity ?? ''}</span>
      <span className="decision-hashes">Prompt {shortHash(decision.prompt_sha256)} · Output {shortHash(decision.output_sha256)}</span>
      <span aria-hidden="true">{open ? '−' : '+'}</span>
    </button>
    {decision.justification && <p className="decision-justification">{decision.justification}</p>}
    {open && <div className="decision-detail">
      <dl className="decision-evidence"><div><dt>Validation</dt><dd>{decision.validation_status}</dd></div><div><dt>Execution result</dt><dd>{decision.execution_result ?? 'Not reported'}</dd></div><div><dt>Error code</dt><dd>{decision.error_code ?? 'None reported'}</dd></div><div><dt>Provider HTTP status</dt><dd>{decision.provider_status_code ?? 'Not reported'}</dd></div><div><dt>Latency</dt><dd>{decision.latency_ms === null || decision.latency_ms === undefined ? 'Not reported' : `${decision.latency_ms} ms`}</dd></div><div><dt>Estimated provider cost</dt><dd>{decision.estimated_cost_usd ? money(decision.estimated_cost_usd) : 'Not reported'}</dd></div><div><dt>Provider usage</dt><dd>{usage}</dd></div></dl>
      {decision.validation_errors.length > 0 && <section className="proposal-evidence"><h3>Validation details</h3><ul>{decision.validation_errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}</ul></section>}
      {decision.proposals.length > 0 && <section className="proposal-evidence"><h3>Recorded proposals</h3>{decision.proposals.map((proposal, index) => <article key={`${proposal.symbol}-${index}`}><header><strong>{proposal.action} {proposal.symbol}</strong><span>Risk: {proposal.risk_decision ?? 'Not evaluated'}</span></header><p>{proposal.justification}</p><dl className="decision-evidence"><div><dt>Quantity</dt><dd>{proposal.quantity}</dd></div><div><dt>Confidence</dt><dd>{proposal.confidence ?? 'Not reported'}</dd></div><div><dt>Leverage</dt><dd>{proposal.leverage ?? 'Not reported'}</dd></div><div><dt>Stop / take profit</dt><dd>{proposal.stop_loss ?? '—'} / {proposal.take_profit ?? '—'}</dd></div><div><dt>Invalidation</dt><dd>{proposal.invalidation ?? 'Not reported'}</dd></div></dl>{proposal.risk_reasons.length > 0 && <ul>{proposal.risk_reasons.map((reason, reasonIndex) => <li key={`${reasonIndex}-${reason}`}>{reason}</li>)}</ul>}</article>)}</section>}
      {artifact.isLoading && <p role="status">Loading exact artifact bytes…</p>}
      {artifact.error && <div className="query-error" role="alert">{artifact.error.message} <button onClick={() => void artifact.refetch()}>Retry</button></div>}
      {(promptArtifact?.bytes || outputArtifact?.bytes) && <div className="artifact-grid">
        {promptArtifact?.bytes && artifact.data && <ArtifactText title="Prompt bytes" bytes={promptArtifact.bytes} hash={artifact.data.prompt_sha256} />}
        {outputArtifact?.bytes && artifact.data && <ArtifactText title="Provider output bytes" bytes={outputArtifact.bytes} hash={artifact.data.output_sha256} />}
      </div>}
      {promptArtifact?.error && <p className="query-error" role="alert">Prompt artifact could not be decoded: {promptArtifact.error}</p>}
      {outputArtifact?.error && <p className="query-error" role="alert">Provider output could not be decoded: {outputArtifact.error}</p>}
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

function decodeBase64Safely(value: string): { bytes: Uint8Array | null; error: string | null } {
  try {
    const binary = atob(value);
    return { bytes: Uint8Array.from(binary, (character) => character.charCodeAt(0)), error: null };
  } catch (error) {
    return { bytes: null, error: error instanceof Error ? error.message : 'Invalid base64 data' };
  }
}

function shortHash(value: string | null): string {
  return value ? `${value.slice(0, 12)}…` : 'Not stored';
}

function Readme({ competitionId }: { competitionId: string }): React.JSX.Element {
  const rules = useQuery({ queryKey: ['competition', competitionId, 'rules'], queryFn: () => getCompetitionRules(competitionId), enabled: Boolean(competitionId) });
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

function RulesEvidence({ artifact }: { artifact: RulesArtifact }): React.JSX.Element {
  const decoded = useMemo(() => artifact.bytes_base64 ? decodeBase64Safely(artifact.bytes_base64) : { bytes: null, error: null }, [artifact.bytes_base64]);
  const [actualHash, setActualHash] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setActualHash(null);
    if (decoded.bytes) {
      void crypto.subtle.digest('SHA-256', decoded.bytes).then((digest) => {
        const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
        if (current) setActualHash(hex);
      }).catch(() => { if (current) setActualHash('unavailable'); });
    }
    return () => { current = false; };
  }, [decoded.bytes]);
  const hashMatches = actualHash === artifact.sha256;

  function download(): void {
    if (!decoded.bytes || !hashMatches || artifact.bytes_withheld) return;
    const blob = new Blob([decoded.bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `competition-rules-${artifact.sha256}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  const policy = artifact.public;
  const facts: Array<[string, string]> = [
    ['Profile', policy.profile],
    ['Symbols', policy.symbols.join(', ')],
    ['Starting virtual capital', money(policy.initial_balance)],
    ['Round / response deadline', `${policy.round_seconds}s / ${policy.response_deadline_seconds}s`],
    ['Quote age / set skew limits', `${policy.quote_max_age_seconds}s / ${policy.quote_set_max_skew_seconds}s`],
    ['Maximum leverage', `${policy.leverage_max}×`],
    ['Commission / slippage', `${decimal(Number(policy.commission_rate) * 100, 3)}% / ${policy.slippage_bps} bps`],
    ['Daily loss / drawdown limits', `${money(policy.max_daily_loss)} / ${decimal(Number(policy.max_drawdown_fraction) * 100, 2)}%`],
    ['Maintenance margin / liquidation fee', `${decimal(Number(policy.maintenance_margin_rate) * 100, 2)}% / ${decimal(Number(policy.liquidation_fee_rate) * 100, 2)}%`],
    ['Funding method', `${policy.funding_mode} · ${policy.funding_rate_basis} · ${policy.funding_price_basis}`],
    ['Risk policy', policy.risk_policy_version],
    ['Evidence schemas', `snapshot ${policy.snapshot_schema_version} · proposal ${policy.proposal_schema_version} · public ${policy.public_evidence_schema_version} · ${policy.market_window_candles} candles`],
  ];
  if (policy.inference_budget_usd !== null) facts.push(['Inference budget', money(policy.inference_budget_usd)]);
  if (policy.fixture_source) facts.push(['Fixture source', policy.fixture_source]);

  return <section className="rules-evidence" aria-label="Public rules evidence">
    <div className="rules-evidence-heading"><strong>SHA-256</strong><code>{artifact.sha256}</code></div>
    {actualHash !== null && <p className={hashMatches ? 'evidence-hash-ok' : 'query-error'} role={hashMatches ? 'status' : 'alert'}>{hashMatches ? 'Exact stored rules bytes verified.' : actualHash === 'unavailable' ? 'Rules hash verification is unavailable.' : 'Stored rules bytes do not match the reported SHA-256.'}</p>}
    <dl>{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    {artifact.withheld_fields && <p className="availability-note">The API omitted fields outside the safe public projection.</p>}
    {artifact.bytes_withheld ? <p className="availability-note">Exact rules bytes are withheld because the stored record contains fields the public contract does not recognize.</p>
      : decoded.error ? <p className="query-error" role="alert">Exact rules bytes could not be decoded: {decoded.error}</p>
        : decoded.bytes ? <button className="small-button" onClick={download} disabled={!hashMatches}>Download exact frozen rules bytes</button>
          : <p className="availability-note">The API did not return exact frozen rule bytes.</p>}
  </section>;
}
