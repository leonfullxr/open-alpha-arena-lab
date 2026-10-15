import type { ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitions, getStatus, getTicker } from './api';

const symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP'];

export function SimulationShell({ children }: { children: ReactNode }): React.JSX.Element {
  const location = useLocation();
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions, refetchInterval: 15_000 });
  const pathCompetition = location.pathname.split('/')[2];
  const scopedCompetition = competitions.data?.find((competition) => competition.id === pathCompetition);
  const refreshMarket = scopedCompetition?.state === 'RUNNING' || scopedCompetition?.state === 'PAUSED';
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus, refetchInterval: refreshMarket ? 5_000 : false });
  const ticker = useQuery({ queryKey: ['ticker', scopedCompetition?.id], queryFn: () => getTicker(scopedCompetition?.id), refetchInterval: refreshMarket ? 5_000 : false });
  const selected = competitions.data?.find((competition) => competition.id === pathCompetition) ?? competitions.data?.[0];
  const competitionPath = selected ? `/simulation/${encodeURIComponent(selected.id)}` : '/simulation';
  const stale = ticker.data?.some((quote) => quote.stale) ?? false;
  const tickerLabel = status.isError || ticker.isError ? 'API UNAVAILABLE' : refreshMarket ? stale ? `${scopedCompetition?.source_label ?? 'MARKET DATA'} · STALE DATA` : `${scopedCompetition?.source_label ?? 'MARKET DATA'} · ${scopedCompetition?.state} · MARKET REFRESH` : scopedCompetition ? `${scopedCompetition.source_label} · ${scopedCompetition.state}` : status.data?.demo_label ?? status.data?.state ?? 'CONNECTING';

  return <div className="terminal">
    <a className="terminal-skip" href="#terminal-main">Skip to content</a>
    <header className="terminal-header">
      <div className="terminal-brand"><Link to="/" aria-label="Open Alpha Arena Lab home">OPEN ALPHA ARENA LAB</Link><span className="replay-badge">{selected?.source_label ?? status.data?.demo_label ?? 'MARKET DATA'}</span></div>
      <label className="competition-select">Competition
        <select value={selected?.id ?? ''} onChange={(event) => { if (event.target.value) window.location.assign(`/simulation/${event.target.value}`); }} disabled={!competitions.data?.length}>
          <option value="">{competitions.isLoading ? 'Loading…' : 'No competitions'}</option>
          {competitions.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <nav aria-label="Terminal navigation">
        <NavLink to="/simulation" end>SIMULATION</NavLink>
        <NavLink to={selected ? `${competitionPath}/leaderboard` : '/simulation'}>LEADERBOARD</NavLink>
        <NavLink to={selected?.agents[0] ? `${competitionPath}/models/${encodeURIComponent(selected.agents[0].id)}` : '/simulation'}>MODELS</NavLink>
        <a href="/admin/">ADMIN</a>
      </nav>
    </header>
    <div className="ticker-bar" aria-label="Market ticker">
      <span className="ticker-state"><i className={status.isError || ticker.isError ? 'state-dot state-dot--error' : ''} />{tickerLabel}</span>
      {symbols.map((symbol) => {
        const quote = ticker.data?.find((item) => item.symbol === symbol);
        return <div className="ticker-item" key={symbol}><b>{symbol}</b><span>{quote ? formatPrice(quote.mark) : '—'}</span></div>;
      })}
      {ticker.data?.[0] && <span className="ticker-source">{ticker.data[0].source} · {formatTimestamp(ticker.data[0].received_at)}</span>}
    </div>
    {status.isError && <div className="system-notice" role="status">Public API unavailable. {status.error.message} <button onClick={() => void status.refetch()}>Retry</button></div>}
    {ticker.isError && <div className="system-notice" role="alert">Market ticker unavailable. {ticker.error.message} <button onClick={() => void ticker.refetch()}>Retry ticker</button></div>}
    <main id="terminal-main" className="terminal-main">{children}</main>
    <footer className="terminal-footer"><span>Open Alpha Arena Lab</span><span>Paper trading · public evidence</span><Link to="/">Methodology</Link></footer>
  </div>;
}

function formatPrice(value: string): string {
  const price = Number(value);
  return Number.isFinite(price) ? price.toLocaleString('en-US', { maximumFractionDigits: price >= 100 ? 2 : 4 }) : value;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${date.toISOString().replace('T', ' ').slice(0, 16)} UTC`;
}
