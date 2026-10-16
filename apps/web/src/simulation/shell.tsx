import { useMemo, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BrandMark } from '../branding';
import { getCompetition, getCompetitions, getStatus, getTicker } from './api';
import { ActivityRail } from './rail';
import { profileTag } from './colors';
import { CompetitionStreamProvider, useCompetitionStream } from './stream';
import { shortTimestamp } from './ui';

/** Display order preference only: the symbol list itself always comes from the API. */
const LEAD_SYMBOLS = ['BTC', 'ETH'];

export function SimulationShell({ children }: { children: ReactNode }): React.JSX.Element {
  const location = useLocation();
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions, refetchInterval: 15_000 });
  const pathCompetition = decodePathSegment(location.pathname.split('/')[2]);
  const requestedRun = pathCompetition ?? new URLSearchParams(location.search).get('run') ?? undefined;
  const scoped = useQuery({
    queryKey: ['competition', requestedRun ?? ''],
    queryFn: () => getCompetition(requestedRun ?? ''),
    enabled: Boolean(requestedRun),
    refetchInterval: (query) => ['RUNNING', 'PAUSED', 'DRAFT'].includes(query.state.data?.state ?? '') ? 5_000 : false,
  });
  const scopedCompetition = scoped.data;
  const selected = requestedRun ? scopedCompetition : competitions.data?.[0];
  const refreshMarket = selected?.state === 'RUNNING' || selected?.state === 'PAUSED';
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus, refetchInterval: refreshMarket ? 5_000 : false });
  const ticker = useQuery({ queryKey: ['ticker', selected?.id], queryFn: () => getTicker(selected?.id), enabled: !requestedRun || Boolean(selected), refetchInterval: refreshMarket ? 5_000 : false });
  const streamState = useCompetitionStream(selected);
  const routeCompetitionPath = pathCompetition ? `/simulation/${encodeURIComponent(pathCompetition)}` : undefined;
  const competitionPath = routeCompetitionPath ?? (selected ? `/simulation/${encodeURIComponent(selected.id)}` : '/simulation');
  const leaderboardPath = selected ? `${competitionPath}/leaderboard` : '/simulation';
  const requestedAgent = decodePathSegment(location.pathname.split('/')[4]);
  const focusedAgent = selected?.agents.find((agent) => agent.id === requestedAgent) ?? selected?.agents[0];
  const modelsPath = focusedAgent ? `${competitionPath}/models/${encodeURIComponent(focusedAgent.id)}` : '/simulation';
  const showRail = location.pathname.startsWith('/simulation');

  const symbols = useMemo(() => {
    const listed = ticker.data?.map((quote) => quote.symbol) ?? [];
    const unique = [...new Set(listed)];
    const lead = LEAD_SYMBOLS.filter((symbol) => unique.includes(symbol));
    const rest = unique.filter((symbol) => !lead.includes(symbol)).sort();
    return [...lead, ...rest];
  }, [ticker.data]);

  const stale = ticker.data?.some((quote) => quote.stale) ?? false;
  const contextLabel = pathCompetition && selected
    ? `${selected.name} · ${profileTag(selected.profile)} · ${selected.state} · ${selected.source_label}`
    : selected
      ? `RUN INDEX · CHAT PREVIEW: ${selected.name} · ${profileTag(selected.profile)} · ${selected.source_label}`
      : requestedRun ? `RUN UNAVAILABLE · ${requestedRun}`
    : competitions.data
      ? `RUN INDEX · ${competitions.data.length} PUBLIC PAPER ${competitions.data.length === 1 ? 'RUN' : 'RUNS'} · ${status.data?.demo_label ?? 'PUBLIC API'}`
      : status.isError ? 'PUBLIC API UNAVAILABLE' : 'CONNECTING TO THE PUBLIC API';

  return <div className={`arena${showRail ? '' : ' arena--wide'}`}>
    <a className="arena-skip" href="#arena-main">Skip to content</a>
    <header className="arena-head">
      <div className="arena-head-row">
        <a className="arena-brand" href="/" aria-label="Open Alpha Arena Lab home">
          <BrandMark className="arena-mark" monochrome />
          <span className="arena-brand-text">OPEN ALPHA ARENA<i className="arena-brand-sub">PAPER TRADING LAB</i></span>
        </a>
        <nav className="arena-nav" aria-label="Arena navigation">
          <NavLink to={competitionPath} end>LIVE</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <NavLink to={leaderboardPath} end>LEADERBOARD</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <NavLink to={modelsPath} end>MODELS</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <NavLink to={selected ? `/simulation?run=${encodeURIComponent(selected.id)}` : '/simulation'} end>ABOUT</NavLink>
        </nav>
        <a className="arena-utility" href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">GITHUB ↗</a>
      </div>
      <div className="arena-band">
        <div className="arena-runs" role="group" aria-label="Competitions">
          <NavLink to={selected ? `/simulation?run=${encodeURIComponent(selected.id)}` : '/simulation'} className="arena-run-tab arena-run-tab--index" end>RUN INDEX</NavLink>
          {(competitions.data ?? []).map((competition) => <NavLink key={competition.id} title={competition.name} to={`/simulation/${encodeURIComponent(competition.id)}`} className={`arena-run-tab ${competition.profile === 'alpha_2025_baseline' ? 'arena-run-tab--baseline' : 'arena-run-tab--extended'}`}>{competition.name}</NavLink>)}
        </div>
        <div className="arena-ticker" aria-label="Market ticker">
          {symbols.map((symbol) => {
            const quote = ticker.data?.find((item) => item.symbol === symbol);
            return <div className="ticker-cell" key={symbol} title={quote ? `${symbol} · mark ${quote.mark} · bid ${quote.bid} / ask ${quote.ask} · ${quote.source} · ${shortTimestamp(quote.received_at)} UTC` : symbol}>
              <b>{symbol}</b>
              <span className={quote?.stale ? 'ticker-mark ticker-mark--stale' : 'ticker-mark'}>{quote ? formatMark(quote.mark) : '—'}</span>
            </div>;
          })}
          <div className="ticker-source" title={ticker.data?.[0]?.source}>
            <span>{status.isError || ticker.isError ? 'API UNAVAILABLE' : ticker.data?.length ? `${status.data?.demo_label ?? 'MARKET DATA'} · ${shortTimestamp(ticker.data[0]!.received_at)} UTC` : status.data?.demo_label ?? 'CONNECTING'}</span>
            {stale && !status.isError && !ticker.isError && <b className="ticker-stale">STALE</b>}
          </div>
        </div>
      </div>
    </header>
    {status.isError && <div className="system-notice" role="status"><b>PUBLIC API UNAVAILABLE.</b><span>{status.error.message} The page shell remains usable; run records cannot load.</span><button onClick={() => void status.refetch()}>RETRY</button></div>}
    {ticker.isError && !status.isError && <div className="system-notice" role="alert"><b>MARKET TICKER UNAVAILABLE.</b><span>{ticker.error.message}</span><button onClick={() => void ticker.refetch()}>RETRY</button></div>}
    <CompetitionStreamProvider state={streamState}><div className="arena-body">
      <div className="arena-workspace">
        <p className="arena-context" title={contextLabel}>{contextLabel}</p>
        <a className="mobile-activity-jump" href="#model-activity">MODEL CHAT ↓</a>
        <main id="arena-main" className="arena-main">{children}</main>
      </div>
      {showRail && <ActivityRail competition={selected} loading={competitions.isLoading || scoped.isLoading} error={requestedRun ? scoped.error : competitions.error} />}
    </div></CompetitionStreamProvider>
    <footer className="arena-foot">
      <BrandMark className="arena-mark" monochrome />
      <span>OPEN ALPHA ARENA LAB</span>
      <span className="arena-foot-note">Paper trading only · public evidence · no live orders</span>
      <nav aria-label="Footer navigation">
        <a href="/#methodology">METHODOLOGY</a>
        <a href="/admin/">ADMIN</a>
        <a href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">GITHUB ↗</a>
      </nav>
    </footer>
  </div>;
}

function formatMark(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: amount >= 100 ? 2 : 4 })
    : value;
}

function decodePathSegment(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
