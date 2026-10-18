import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight, Bot, LayoutDashboard, Moon, PanelLeftClose, PanelLeftOpen, Sun, Trophy } from 'lucide-react';
import { getCompetition, getCompetitions, getStatus, getTicker } from './api';
import { AssetIcon } from './asset-action-icons';
import { marketPrice } from './ui';

const symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP'];

export function SimulationShell({ children }: { children: ReactNode }): React.JSX.Element {
  const location = useLocation();
  const [dark, setDark] = useState(() => window.localStorage.getItem('oaal-theme') === 'dark');
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem('oaal-sidebar') === 'collapsed');
  useEffect(() => { window.localStorage.setItem('oaal-theme', dark ? 'dark' : 'light'); }, [dark]);
  useEffect(() => { window.localStorage.setItem('oaal-sidebar', collapsed ? 'collapsed' : 'expanded'); }, [collapsed]);
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions, refetchInterval: 15_000 });
  const pathCompetition = location.pathname.split('/')[2];
  const scoped = useQuery({
    queryKey: ['competition', pathCompetition ?? ''],
    queryFn: () => getCompetition(pathCompetition ?? ''),
    enabled: Boolean(pathCompetition),
    refetchInterval: (query) => ['RUNNING', 'PAUSED', 'DRAFT'].includes(query.state.data?.state ?? '') ? 5_000 : false,
  });
  const scopedCompetition = scoped.data;
  const refreshMarket = scopedCompetition?.state === 'RUNNING' || scopedCompetition?.state === 'PAUSED';
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus, refetchInterval: refreshMarket ? 5_000 : false });
  const ticker = useQuery({ queryKey: ['ticker', scopedCompetition?.id], queryFn: () => getTicker(scopedCompetition?.id), refetchInterval: refreshMarket ? 5_000 : false });
  const selected = scopedCompetition ?? competitions.data?.[0];
  const competitionPath = selected ? `/simulation/${encodeURIComponent(selected.id)}` : '/simulation';
  const stale = ticker.data?.some((quote) => quote.stale) ?? false;
  const tickerLabel = status.isError || ticker.isError ? 'API unavailable' : refreshMarket ? stale ? 'Stale market data' : 'Refreshing market data' : scopedCompetition ? 'Market refresh stopped' : 'Market data idle';

  return <div className="terminal" data-theme={dark ? 'dark' : 'light'}>
    <a className="terminal-skip" href="#terminal-main">Skip to content</a>
    <div className={`terminal-shell${collapsed ? ' is-collapsed' : ''}`}>
      <aside className="terminal-sidebar">
        <div className="terminal-brand"><a href="/" aria-label="Open Alpha Arena Lab home">
          <img className="terminal-lockup" src="/brand/oaal-lockup-light.svg" alt="" />
          <img className="terminal-compact-mark terminal-mark-light" src="/brand/oaal-mark-light.svg" alt="" />
          <img className="terminal-compact-mark terminal-mark-dark" src="/brand/oaal-mark-dark.svg" alt="" />
          <span className="terminal-brand-label">Open Alpha Arena Lab</span>
        </a><button className="sidebar-collapse" type="button" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}</button></div>
        <nav className="terminal-nav" aria-label="Workspace navigation">
          <div className="terminal-nav-group">
            <span className="terminal-nav-label">Research</span>
            <NavLink to="/simulation" end aria-label="Simulation" title="Simulation"><LayoutDashboard aria-hidden="true" /><span className="nav-link-label">Simulation</span></NavLink>
            <NavLink to={selected ? `${competitionPath}/leaderboard` : '/simulation'} aria-label="Leaderboard" title="Leaderboard"><Trophy aria-hidden="true" /><span className="nav-link-label">Leaderboard</span></NavLink>
            <NavLink to={selected ? `${competitionPath}/models` : '/simulation'} aria-label="Models" title="Models"><Bot aria-hidden="true" /><span className="nav-link-label">Models</span></NavLink>
          </div>
        </nav>
        <div className="terminal-sidebar-footer"><span>Paper trading · public evidence</span><a href="/#methodology">Methodology <ArrowUpRight aria-hidden="true" size={13} /></a></div>
      </aside>
      <div className="terminal-workspace">
        <header className="terminal-header">
          <label className="competition-select">Competition
            <select value={selected?.id ?? ''} onChange={(event) => { if (event.target.value) window.location.assign(`/simulation/${encodeURIComponent(event.target.value)}`); }} disabled={!competitions.data?.length}>
              <option value="">{competitions.isLoading ? 'Loading…' : 'No competitions'}</option>
              {competitions.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          {selected && <span className={`workspace-state status-${selected.state.toLowerCase()}`}>{selected.state.toLocaleLowerCase().replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase())}</span>}
          <span className="replay-badge" title={selected?.source_label ?? status.data?.demo_label ?? 'Market data'}>{selected?.source_label ?? status.data?.demo_label ?? 'Market data'}</span>
          <button className="theme-toggle" type="button" aria-pressed={dark} onClick={() => setDark((value) => !value)}>{dark ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}<span>{dark ? 'Light mode' : 'Dark mode'}</span></button>
        </header>
        <div className="ticker-bar" role="region" tabIndex={0} aria-label="Market ticker, scroll horizontally for more symbols">
      <span className="ticker-state"><i className={status.isError || ticker.isError ? 'state-dot state-dot--error' : ''} />{tickerLabel}</span>
      {symbols.map((symbol) => {
        const quote = ticker.data?.find((item) => item.symbol === symbol);
        return <div className="ticker-item" key={symbol} role="group" aria-label={`${symbol} ${quote ? marketPrice(quote.mark) : 'price unavailable'}`}><AssetIcon symbol={symbol} size={19} /><span>{quote ? marketPrice(quote.mark) : '—'}</span></div>;
      })}
      {ticker.data?.[0] && <span className="ticker-source">{ticker.data[0].source} · {formatTimestamp(ticker.data[0].received_at)}</span>}
        </div>
        {status.isError && <div className="system-notice" role="status">Public API unavailable. {status.error.message} <button onClick={() => void status.refetch()}>Retry</button></div>}
        {ticker.isError && <div className="system-notice" role="alert">Market ticker unavailable. {ticker.error.message} <button onClick={() => void ticker.refetch()}>Retry ticker</button></div>}
        <main id="terminal-main" className="terminal-main" tabIndex={-1}>{children}</main>
        <footer className="terminal-footer"><span>Open Alpha Arena Lab</span><span>Paper trading · public evidence</span><a href="/#methodology">Methodology <ArrowUpRight aria-hidden="true" size={13} /></a></footer>
      </div>
    </div>
  </div>;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`;
}
