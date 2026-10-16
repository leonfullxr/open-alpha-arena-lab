import { useEffect, useId, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getArtifact, getDecisionHistory, getEvents, type Agent, type Decision } from './api';
import { modelMarker, modelToneClass } from './colors';
import { decodeBase64Safely, money, shortHash } from './ui';

export const CHAT_PAGE_SIZE = 10;
const EVENT_PAGE_SIZE = 100;
const MAX_EVENT_PAGES = 6;

/**
 * Decisions carry a round but no wall-clock time. The public event stream
 * records when each decision happened, so the feed shows a real timestamp
 * taken from that stream instead of inventing one. Rounds with no matching
 * event fall back to the round label.
 */
export function useDecisionTimes(competitionId: string): Map<string, string> {
  const query = useQuery({
    queryKey: ['competition', competitionId, 'event-times'],
    queryFn: async () => {
      const times = new Map<string, string>();
      let after = 0;
      for (let page = 0; page < MAX_EVENT_PAGES; page += 1) {
        const batch = await getEvents(competitionId, after);
        for (const event of batch.items) {
          if (event.event_type !== 'agent.decision') continue;
          const round = Number(event.payload?.round);
          if (!Number.isSafeInteger(round)) continue;
          const key = `${event.agent_id}:${round}`;
          if (!times.has(key)) times.set(key, event.event_at);
        }
        if (batch.items.length < EVENT_PAGE_SIZE) break;
        after = batch.items[batch.items.length - 1]?.sequence ?? 0;
        if (!after) break;
      }
      return times;
    },
    enabled: Boolean(competitionId),
    staleTime: 30_000,
  });
  return useMemo(() => query.data ?? new Map<string, string>(), [query.data]);
}

function cardTime(decision: Decision, times: Map<string, string>): string {
  const value = times.get(`${decision.agent_id}:${decision.round}`);
  if (!value) return `ROUND ${decision.round}`;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return `ROUND ${decision.round}`;
  const month = `${date.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${date.getUTCDate()}`.padStart(2, '0');
  return `${month}/${day} ${`${date.getUTCHours()}`.padStart(2, '0')}:${`${date.getUTCMinutes()}`.padStart(2, '0')}:${`${date.getUTCSeconds()}`.padStart(2, '0')} UTC`;
}

export function DecisionFeed({
  competitionId,
  agents,
  agentId,
  badge,
  highlightDecisionId,
  decisionRound,
  idPrefix,
  showAgentFilter = true,
  emptyMessage = 'No model decisions match this filter.',
}: {
  competitionId: string;
  agents: Agent[];
  agentId?: string;
  badge?: string;
  highlightDecisionId?: string;
  decisionRound?: number;
  idPrefix?: string;
  showAgentFilter?: boolean;
  emptyMessage?: string;
}): React.JSX.Element {
  const generatedId = useId().replaceAll(':', '');
  const feedId = idPrefix ?? generatedId;
  const [selectedAgent, setSelectedAgent] = useState('');
  const [symbolDraft, setSymbolDraft] = useState('');
  const [symbol, setSymbol] = useState('');
  const [page, setPage] = useState(0);
  const effectiveAgent = agentId ?? selectedAgent;
  const query = useDecisionQuery(competitionId, page, effectiveAgent, symbol);
  const times = useDecisionTimes(competitionId);

  useEffect(() => {
    setSelectedAgent('');
    setSymbolDraft('');
    setSymbol('');
    setPage(0);
  }, [competitionId]);
  useEffect(() => { setPage(0); }, [effectiveAgent, symbol, agentId]);
  useEffect(() => {
    if (highlightDecisionId && decisionRound) setPage(Math.floor((decisionRound - 1) / CHAT_PAGE_SIZE));
  }, [highlightDecisionId, decisionRound, competitionId, agentId]);
  useEffect(() => {
    if (page > 0 && query.data && page * CHAT_PAGE_SIZE >= query.data.total) setPage(0);
  }, [page, query.data]);
  useEffect(() => {
    if (!highlightDecisionId) return;
    document.getElementById(`${feedId}-decision-${highlightDecisionId}`)?.scrollIntoView({ block: 'center' });
  }, [feedId, highlightDecisionId, query.data]);

  const rows = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / CHAT_PAGE_SIZE));

  return <>
    <div className="chat-filters">
      <span className="chat-filter-label">FILTER:</span>
      {showAgentFilter && !agentId && agents.length > 1 && <><label className="visually-hidden" htmlFor={`${feedId}-agent`}>Model</label>
      <select id={`${feedId}-agent`} value={selectedAgent} onChange={(event) => setSelectedAgent(event.target.value)}>
        <option value="">ALL MODELS</option>
        {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name.toUpperCase()}</option>)}
      </select></>}
      <form className="chat-symbol-form" onSubmit={(event) => { event.preventDefault(); setSymbol(symbolDraft.trim().toUpperCase()); }}>
        <label className="visually-hidden" htmlFor={`${feedId}-symbol`}>Symbol</label>
        <input id={`${feedId}-symbol`} value={symbolDraft} onChange={(event) => setSymbolDraft(event.target.value)} placeholder="SYMBOL" maxLength={24} />
        <button type="submit">GO</button>
      </form>
    </div>
    {query.isLoading ? <div className="query-state" role="status">Loading model decisions…</div>
      : query.error ? <div className="query-error" role="alert">{query.error.message} <button onClick={() => void query.refetch()}>Retry decisions</button></div>
        : rows.length === 0 ? <div className="query-state">{emptyMessage}</div>
          : <>
            <div className="chat-feed">
              {rows.map((decision) => <ChatCard key={decision.id} decision={decision} agents={agents} times={times} badge={badge} competitionId={competitionId} idPrefix={feedId} highlighted={decision.id === highlightDecisionId} />)}
            </div>
            {pageCount > 1 && <div className="history-pagination"><span>{page * CHAT_PAGE_SIZE + 1}–{Math.min((page + 1) * CHAT_PAGE_SIZE, total)} of {total}</span><div><button disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>PREV</button><button disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>NEXT</button></div></div>}
          </>}
  </>;
}

function useDecisionQuery(competitionId: string, page: number, agentId: string, symbol: string) {
  const query = { limit: CHAT_PAGE_SIZE, offset: page * CHAT_PAGE_SIZE, ...(agentId ? { agent_id: agentId } : {}), ...(symbol ? { symbol } : {}) };
  return useQuery({
    queryKey: ['competition', competitionId, 'decisions', query],
    queryFn: () => getDecisionHistory(competitionId, query),
    enabled: Boolean(competitionId),
  });
}

function ChatCard({ decision, agents, times, badge, competitionId, idPrefix, highlighted }: {
  decision: Decision;
  agents: Agent[];
  times: Map<string, string>;
  badge?: string;
  competitionId: string;
  idPrefix: string;
  highlighted: boolean;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const toneClass = modelToneClass(agents, decision.agent_id);
  return <article
    id={`${idPrefix}-decision-${decision.id}`}
    className={`chat-card ${toneClass}${highlighted ? ' chat-card--linked' : ''}`}
  >
    <span className="chat-marker" aria-hidden="true">{modelMarker(agents, decision.agent_id)}</span>
    <div className="chat-column">
      <button className="chat-head" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="chat-name">{decision.agent_name.toUpperCase()}</span>
        {badge && <span className="chat-badge">{badge}</span>}
        <span className="chat-time">{cardTime(decision, times)}</span>
      </button>
      <div className="chat-bubble">
        <p className="chat-body">{decision.justification ?? 'The API returned no public justification for this decision.'}</p>
        <p className="chat-action">{decision.action ?? 'NO ACTION'}{decision.symbol ? ` · ${decision.symbol}` : ''}{decision.quantity ? ` · ${decision.quantity}` : ''}</p>
        <button
          type="button"
          className="chat-expand"
          aria-expanded={open}
          aria-label={`${open ? 'Collapse' : 'Expand'} public evidence for ${decision.agent_name}, round ${decision.round}`}
          onClick={() => setOpen((value) => !value)}
        >click to {open ? 'collapse' : 'expand'}</button>
        {open && <ChatDetail decision={decision} competitionId={competitionId} />}
      </div>
    </div>
  </article>;
}

function ChatDetail({ decision, competitionId }: { decision: Decision; competitionId: string }): React.JSX.Element {
  const artifact = useQuery({ queryKey: ['artifact', decision.id], queryFn: () => getArtifact(decision.id) });
  const promptArtifact = artifact.data ? decodeBase64Safely(artifact.data.prompt_bytes_base64) : null;
  const outputArtifact = artifact.data?.output_publicly_releasable ? decodeBase64Safely(artifact.data.output_bytes_base64) : null;
  const usage = Object.entries(decision.usage).map(([name, value]) => `${name}: ${value}`).join(' · ') || 'Not reported';

  return <div className="chat-detail">
    <p className="public-evidence-scope">PUBLIC DECISION RECORD — only supplied API fields and artifacts marked for public release appear here. Hidden reasoning is not published or inferred.</p>
    <details className="chat-block chat-disclosure"><summary>PUBLIC JUSTIFICATION</summary><p className="chat-body">{decision.justification ?? 'The API returned no public justification for this decision.'}</p></details>
    <dl className="chat-facts">
      <div><dt>Round</dt><dd>{decision.round}</dd></div>
      <div><dt>Validation</dt><dd>{decision.validation_status}</dd></div>
      <div><dt>Execution</dt><dd>{decision.execution_result ?? 'Not reported'}</dd></div>
      <div><dt>Provider</dt><dd>{decision.provider} · {decision.model}</dd></div>
      <div><dt>Latency</dt><dd>{decision.latency_ms === null || decision.latency_ms === undefined ? 'Not reported' : `${decision.latency_ms} ms`}</dd></div>
      <div><dt>Error code</dt><dd>{decision.error_code ?? 'None reported'}</dd></div>
      <div><dt>Provider HTTP status</dt><dd>{decision.provider_status_code ?? 'Not reported'}</dd></div>
      <div><dt>Estimated provider cost</dt><dd>{decision.estimated_cost_usd === null || decision.estimated_cost_usd === undefined ? 'Not reported' : money(decision.estimated_cost_usd)}</dd></div>
      <div><dt>Usage</dt><dd>{usage}</dd></div>
      <div><dt>Prompt SHA-256</dt><dd className="chat-hash">{shortHash(decision.prompt_sha256)}</dd></div>
      <div><dt>Output SHA-256</dt><dd className="chat-hash">{shortHash(decision.output_sha256)}</dd></div>
    </dl>
    {decision.validation_errors.length > 0 && <section className="chat-block"><h3>Validation details</h3><ul>{decision.validation_errors.map((error, index) => <li key={`${index}-${error}`}>{error}</li>)}</ul></section>}
    {decision.proposals.length > 0 && <details className="chat-block chat-disclosure" open><summary>TRADING_DECISIONS · RECORDED PROPOSALS</summary>
      {decision.proposals.map((proposal, index) => <article className="chat-proposal" key={`${proposal.symbol}-${index}`}>
        <header><strong>{proposal.action} {proposal.symbol}</strong><span>RISK: {proposal.risk_decision ?? 'Not evaluated'}</span></header>
        <p>{proposal.justification}</p>
        <dl className="chat-facts">
          <div><dt>Quantity</dt><dd>{proposal.quantity}</dd></div>
          <div><dt>Leverage</dt><dd>{proposal.leverage ?? 'Not reported'}</dd></div>
          <div><dt>Confidence</dt><dd>{proposal.confidence ?? 'Not reported'}</dd></div>
          <div><dt>Stop / take profit</dt><dd>{proposal.stop_loss ?? '—'} / {proposal.take_profit ?? '—'}</dd></div>
          <div><dt>Invalidation</dt><dd>{proposal.invalidation ?? 'Not reported'}</dd></div>
        </dl>
        {proposal.risk_reasons.length > 0 && <ul>{proposal.risk_reasons.map((reason, reasonIndex) => <li key={`${reasonIndex}-${reason}`}>{reason}</li>)}</ul>}
      </article>)}
    </details>}
    {artifact.isLoading && <p role="status">Loading exact artifact bytes…</p>}
    {artifact.error && <div className="query-error" role="alert">{artifact.error.message} <button onClick={() => void artifact.refetch()}>Retry artifacts</button></div>}
    {(promptArtifact?.bytes || outputArtifact?.bytes) && <div className="artifact-grid">
      {promptArtifact?.bytes && artifact.data && <details className="chat-block chat-disclosure" open><summary>USER_PROMPT · EXACT ARTIFACT BYTES</summary><ArtifactText title="User prompt bytes" bytes={promptArtifact.bytes} hash={artifact.data.prompt_sha256} /></details>}
      {outputArtifact?.bytes && artifact.data && <ArtifactText title="Public provider output bytes" bytes={outputArtifact.bytes} hash={artifact.data.output_sha256} />}
    </div>}
    {promptArtifact?.error && <p className="query-error" role="alert">Prompt artifact could not be decoded: {promptArtifact.error}</p>}
    {outputArtifact?.error && <p className="query-error" role="alert">Provider output could not be decoded: {outputArtifact.error}</p>}
    {artifact.data && !artifact.data.output_publicly_releasable && <p className="availability-note">Provider output withheld from public display. SHA-256 {artifact.data.output_sha256} remains available for audit.</p>}
    <p className="chat-record"><Link to={`/simulation/${encodeURIComponent(competitionId)}`}>OPEN THE COMPETITION RECORD</Link></p>
  </div>;
}

function ArtifactText({ title, bytes, hash }: { title: string; bytes: Uint8Array; hash: string }): React.JSX.Element {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
  function download(): void {
    const blob = new Blob([bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${title.toLowerCase().replace(/\s+/g, '-')}-${hash}.bin`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }
  return <section className="artifact-block"><div><h3>{title}</h3><button className="small-button" onClick={download}>DOWNLOAD</button></div><code>SHA-256 {hash}</code><pre>{text || '[Empty artifact]'}</pre></section>;
}
