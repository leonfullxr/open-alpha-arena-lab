import { useCallback, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BrandMark } from '../branding';
import { getCompetition, getCompetitions, getStatus, getTicker, isPublicApiError, nextPollInterval, retryPollInterval } from './api';
import { ActivityRail } from './rail';
import { profileTag } from './colors';
import { CompetitionStreamProvider, useCompetitionStream } from './stream';
import { ApiAvailabilityProvider, shortTimestamp } from './ui';

/** Display order preference only: the symbol list itself always comes from the API. */
const LEAD_SYMBOLS = ['BTC', 'ETH'];

export function SimulationShell({ children }: { children: ReactNode }): React.JSX.Element {
  const location = useLocation();
  const queryClient = useQueryClient();
  const subscribeToAvailability = useCallback((notify: () => void) => queryClient.getQueryCache().subscribe(() => notify()), [queryClient]);
  const getAvailabilitySnapshot = useCallback(() => {
    for (const query of queryClient.getQueryCache().getAll()) {
      if (query.getObserversCount() === 0 || query.state.status !== 'error' || !isPublicApiError(query.state.error)) continue;
      if (['service', 'rate-limit', 'offline', 'invalid-response'].includes(query.state.error.kind)) return query.state.error;
    }
    return undefined;
  }, [queryClient]);
  const availabilityError = useSyncExternalStore(subscribeToAvailability, getAvailabilitySnapshot, () => undefined);
  const getStaleSnapshot = useCallback(() => queryClient.getQueryCache().getAll().some((query) =>
    query.getObserversCount() > 0 && query.state.status === 'error' && query.state.data !== undefined && isPublicApiError(query.state.error) &&
    ['service', 'rate-limit', 'offline', 'invalid-response'].includes(query.state.error.kind)), [queryClient]);
  const hasStaleData = useSyncExternalStore(subscribeToAvailability, getStaleSnapshot, () => false);
  const competitions = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions, refetchInterval: (query) => nextPollInterval(15_000, query.state.error) });
  const competitionsInDisplayOrder = useMemo(() => [...(competitions.data ?? [])].sort((left, right) => Number(isTestFixture(left.source_label)) - Number(isTestFixture(right.source_label))), [competitions.data]);
  const pathCompetition = location.pathname === '/simulation/blog' ? undefined : decodePathSegment(location.pathname.split('/')[2]);
  const requestedRun = pathCompetition ?? new URLSearchParams(location.search).get('run') ?? undefined;
  const scoped = useQuery({
    queryKey: ['competition', requestedRun ?? ''],
    queryFn: () => getCompetition(requestedRun ?? ''),
    enabled: Boolean(requestedRun),
    refetchInterval: (query) => {
      const recoveryInterval = retryPollInterval(query.state.error);
      if (recoveryInterval !== false) return recoveryInterval;
      return ['RUNNING', 'PAUSED', 'DRAFT'].includes(query.state.data?.state ?? '') ? nextPollInterval(5_000, query.state.error) : false;
    },
  });
  const scopedCompetition = scoped.data;
  const selected = requestedRun ? scopedCompetition : competitionsInDisplayOrder[0];
  const refreshMarket = selected?.state === 'RUNNING' || selected?.state === 'PAUSED';
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus, refetchInterval: (query) => {
    const recoveryInterval = retryPollInterval(query.state.error);
    if (recoveryInterval !== false) return recoveryInterval;
    return refreshMarket ? nextPollInterval(5_000, query.state.error) : false;
  } });
  const ticker = useQuery({ queryKey: ['ticker', requestedRun ?? 'aggregate'], queryFn: () => getTicker(requestedRun ? selected?.id : undefined), enabled: !requestedRun || Boolean(selected), refetchInterval: (query) => {
    const recoveryInterval = retryPollInterval(query.state.error);
    if (recoveryInterval !== false) return recoveryInterval;
    return refreshMarket ? nextPollInterval(5_000, query.state.error) : false;
  } });
  const streamState = useCompetitionStream(requestedRun ? selected : undefined);
  const routeCompetitionPath = pathCompetition ? `/simulation/${encodeURIComponent(pathCompetition)}` : undefined;
  const narrativePath = selected ? `/simulation?run=${encodeURIComponent(selected.id)}` : '/simulation';
  const competitionPath = routeCompetitionPath ?? (selected ? `/simulation/${encodeURIComponent(selected.id)}` : '/simulation');
  const leaderboardPath = selected ? `${competitionPath}/leaderboard` : '/simulation';
  const requestedAgent = decodePathSegment(location.pathname.split('/')[4]);
  const focusedAgent = selected?.agents.find((agent) => agent.id === requestedAgent) ?? selected?.agents[0];
  const modelsPath = focusedAgent ? `${competitionPath}/models/${encodeURIComponent(focusedAgent.id)}` : '/simulation';
  const isStandalone = location.pathname.endsWith('/leaderboard') || location.pathname.includes('/models/') || location.pathname === '/simulation/blog';
  const showRail = location.pathname.startsWith('/simulation') && !isStandalone;
  const hasExplicitRun = Boolean(pathCompetition || new URLSearchParams(location.search).get('run'));

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
    : hasExplicitRun && selected
      ? `${selected.name} · ${profileTag(selected.profile)} · ${selected.state} · ${selected.source_label}`
      : selected
        ? `PUBLISHED PAPER RUNS · ${competitions.data?.length ?? 0} · PROFILES REPORTED SEPARATELY`
      : requestedRun ? `RUN UNAVAILABLE · ${requestedRun}`
    : competitions.data
      ? `RUN INDEX · ${competitions.data.length} PUBLIC PAPER ${competitions.data.length === 1 ? 'RUN' : 'RUNS'} · ${status.data?.demo_label ?? 'PUBLIC API'}`
      : availabilityError || competitions.isError || status.isError
        ? 'RUN INDEX · DATA DELAYED'
        : 'CONNECTING TO THE PUBLIC API';

  return <div className={`arena${showRail ? '' : ' arena--wide'}${hasExplicitRun && !pathCompetition ? ' arena--narrative-run' : ''}`}>
    <a className="arena-skip" href="#arena-main">Skip to content</a>
    <header className="arena-head">
      <div className="arena-head-row">
        <a className="arena-brand" href="/" aria-label="Open Alpha Arena Lab home">
          <BrandMark className="arena-mark" />
          <span className="arena-brand-text"><span>OPEN ALPHA ARENA <i className="arena-brand-inline">LAB</i></span></span>
        </a>
        <nav className="arena-nav" aria-label="Arena navigation">
          <NavLink to={narrativePath} end>LIVE</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <NavLink to={leaderboardPath} end>LEADERBOARD</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <NavLink to={modelsPath} end>MODELS</NavLink>
          <span className="arena-nav-divider" aria-hidden="true" />
          <a href="/#methodology">BLOG</a>
          <span className="arena-nav-divider" aria-hidden="true" />
          <a href="/#methodology">ABOUT</a>
        </nav>
        <div className="arena-utility-group"><span className="arena-nav-divider" aria-hidden="true" /><a className="arena-utility" href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">GITHUB ↗</a></div>
      </div>
    </header>
    <div className="arena-band">
        <div className="arena-runs" role="group" aria-label="Competitions">
          <Link to="/simulation" aria-current={!requestedRun ? 'page' : undefined} className={`arena-run-tab arena-run-tab--index${!requestedRun ? ' active' : ''}`}>AGGREGATE INDEX</Link>
          {competitionsInDisplayOrder.map((competition, index) => {
            const active = requestedRun === competition.id;
            return <Link key={competition.id} title={`${competition.name} · ${competition.source_label}`} to={`/simulation?run=${encodeURIComponent(competition.id)}`} aria-current={active ? 'page' : undefined} className={`arena-run-tab arena-run-tab--competition-${index % 4}${active ? ' active' : ''}`}><span className="arena-run-number">{index + 1}:</span><span className="arena-run-source">{isTestFixture(competition.source_label) ? 'TEST FIXTURE · ' : ''}</span>{competition.name}</Link>;
          })}
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
            <span>{status.isError || ticker.isError ? 'DATA DELAYED' : ticker.data?.length ? `${status.data?.demo_label ?? 'MARKET DATA'} · ${shortTimestamp(ticker.data[0]!.received_at)} UTC` : status.data?.demo_label ?? 'CONNECTING'}</span>
            {stale && !status.isError && !ticker.isError && <b className="ticker-stale">STALE</b>}
          </div>
        </div>
    </div>
    {availabilityError && <div className="system-notice" role="status">
      <span>{hasStaleData ? `Some displayed values are from the last successful refresh. ${availabilityError.message}` : availabilityError.message}</span>
      <button aria-label="Retry public data" onClick={() => void queryClient.refetchQueries({ type: 'active', predicate: (query) => query.state.status === 'error' })}>RETRY PUBLIC DATA</button>
    </div>}
    <CompetitionStreamProvider state={streamState}><ApiAvailabilityProvider error={availabilityError} hasStaleData={hasStaleData}><div className="arena-body">
      <div className="arena-workspace">
        <p className="arena-context" title={contextLabel}>{contextLabel}</p>
        <a className="mobile-activity-jump" href="#model-activity">MODEL CHAT ↓</a>
        <main id="arena-main" className="arena-main">{children}</main>
      </div>
      {showRail && <ActivityRail mode={hasExplicitRun ? 'run' : 'aggregate'} competition={hasExplicitRun ? selected : undefined} competitions={competitionsInDisplayOrder} loading={competitions.isLoading || scoped.isLoading} error={requestedRun ? scoped.error : competitions.error} />}
    </div></ApiAvailabilityProvider></CompetitionStreamProvider>
    <footer className="arena-foot">
      <BrandMark className="arena-mark" />
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

function isTestFixture(source: string): boolean {
  return source.toUpperCase().includes('TEST FIXTURE');
}
