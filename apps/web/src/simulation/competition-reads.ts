import { queryOptions, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { createContext, createElement, useContext, useEffect, useState, type ReactElement, type ReactNode } from 'react';
import {
  getCompetition,
  getCompetitionMetrics,
  getCompetitionRules,
  getCompetitions,
  getDecisionHistory,
  getEquityChart,
  getFundingHistory,
  getLeaderboard,
  getModel,
  getPositionHistory,
  getStatus,
  getTicker,
  getTradeHistory,
  canAutomaticallyRetry,
  nextPollInterval,
  type Competition,
  type EquityRange,
  type HistoryQuery,
} from './api';

const competitionReads = {
  competitions: () => ['competitions'] as const,
  competition: (id: string) => ['competition', id] as const,
  leaderboard: (id: string) => ['competition', id, 'leaderboard'] as const,
  chart: (id: string, range: EquityRange) => ['competition', id, 'chart', range] as const,
  metrics: (id: string) => ['competition', id, 'metrics'] as const,
  trades: (id: string, query: HistoryQuery) => ['competition', id, 'trades', query] as const,
  decisions: (id: string, query: HistoryQuery) => ['competition', id, 'decisions', query] as const,
  positions: (id: string, query: HistoryQuery) => ['competition', id, 'positions', query] as const,
  funding: (id: string, query: HistoryQuery) => ['competition', id, 'funding', query] as const,
  rules: (id: string) => ['competition', id, 'rules'] as const,
  model: (id: string) => ['model', id] as const,
  models: () => ['model'] as const,
  status: () => ['status'] as const,
  ticker: (id?: string) => ['ticker', id] as const,
};

function competitionLiveReadPrefixes(id: string): readonly (readonly unknown[])[] {
  return [
    competitionReads.competition(id),
    competitionReads.leaderboard(id),
    ['competition', id, 'chart'],
    competitionReads.metrics(id),
    ['competition', id, 'trades'],
    ['competition', id, 'decisions'],
    ['competition', id, 'positions'],
    ['competition', id, 'funding'],
  ];
}

const competitionListRefreshMs = 15_000;
const liveMarketRefreshMs = 5_000;
const liveCompetitionStates = ['RUNNING', 'PAUSED', 'DRAFT'] as const;

const CompetitionLiveStatusContext = createContext<'paused' | 'connected' | 'reconnecting'>('paused');

export function CompetitionLiveStatusProvider({ state, children }: { state: 'paused' | 'connected' | 'reconnecting'; children: ReactNode }): ReactElement {
  return createElement(CompetitionLiveStatusContext.Provider, { value: state }, children);
}

export function useCompetitionLiveStatus(): 'paused' | 'connected' | 'reconnecting' {
  return useContext(CompetitionLiveStatusContext);
}

export const competitionReadOptions = {
  competitions: () => queryOptions({ queryKey: competitionReads.competitions(), queryFn: getCompetitions }),
  liveCompetitions: () => queryOptions({
    queryKey: competitionReads.competitions(),
    queryFn: getCompetitions,
    refetchInterval: (query) => nextPollInterval(competitionListRefreshMs, query.state.error),
  }),
  competition: competitionDetailOptions,
  liveCompetition: (id: string) => queryOptions({
    ...competitionDetailOptions(id),
    refetchInterval: (query) => liveCompetitionStates.some((state) => state === query.state.data?.state)
      ? nextPollInterval(liveMarketRefreshMs, query.state.error)
      : false,
  }),
  leaderboard: (id: string) => queryOptions({ queryKey: competitionReads.leaderboard(id), queryFn: () => getLeaderboard(id) }),
  chart: (id: string, range: EquityRange) => queryOptions({ queryKey: competitionReads.chart(id, range), queryFn: () => getEquityChart(id, range) }),
  metrics: (id: string) => queryOptions({ queryKey: competitionReads.metrics(id), queryFn: () => getCompetitionMetrics(id) }),
  trades: (id: string, query: HistoryQuery) => queryOptions({ queryKey: competitionReads.trades(id, query), queryFn: () => getTradeHistory(id, query) }),
  decisions: (id: string, query: HistoryQuery) => queryOptions({ queryKey: competitionReads.decisions(id, query), queryFn: () => getDecisionHistory(id, query) }),
  positions: (id: string, query: HistoryQuery) => queryOptions({ queryKey: competitionReads.positions(id, query), queryFn: () => getPositionHistory(id, query) }),
  funding: (id: string, query: HistoryQuery) => queryOptions({ queryKey: competitionReads.funding(id, query), queryFn: () => getFundingHistory(id, query) }),
  rules: (id: string) => queryOptions({ queryKey: competitionReads.rules(id), queryFn: () => getCompetitionRules(id) }),
  model: (id: string) => queryOptions({ queryKey: competitionReads.model(id), queryFn: () => getModel(id) }),
  status: () => queryOptions({ queryKey: competitionReads.status(), queryFn: getStatus }),
  ticker: (id?: string) => queryOptions({ queryKey: competitionReads.ticker(id), queryFn: () => getTicker(id) }),
};

export function useCompetitionWorkspace(competitionId?: string) {
  const competitions = useQuery(competitionReadOptions.liveCompetitions());
  const scoped = useQuery({
    ...competitionReadOptions.liveCompetition(competitionId ?? ''),
    enabled: Boolean(competitionId),
  });
  const scopedCompetition = scoped.data;
  const liveStatus = useCompetitionLiveUpdates(scopedCompetition);
  const marketRefreshing = isMarketRefreshing(scopedCompetition);
  const status = useQuery({
    ...competitionReadOptions.status(),
    refetchInterval: (query) => marketRefreshing ? nextPollInterval(liveMarketRefreshMs, query.state.error) : false,
  });
  const ticker = useQuery({
    ...competitionReadOptions.ticker(scopedCompetition?.id),
    refetchInterval: (query) => marketRefreshing ? nextPollInterval(liveMarketRefreshMs, query.state.error) : false,
  });

  return {
    competitions,
    scoped,
    scopedCompetition,
    selected: scopedCompetition ?? competitions.data?.[0],
    status,
    ticker,
    marketRefreshing,
    liveStatus,
  };
}

function competitionDetailOptions(id: string) {
  return queryOptions({
    queryKey: competitionReads.competition(id),
    queryFn: () => getCompetition(id),
  });
}

function isMarketRefreshing(competition: Competition | undefined): boolean {
  return competition?.state === 'RUNNING' || competition?.state === 'PAUSED';
}

export function useCompetitionLiveUpdates(competition: Competition | undefined): 'paused' | 'connected' | 'reconnecting' {
  const queryClient = useQueryClient();
  const [state, setState] = useState<'paused' | 'connected' | 'reconnecting'>('paused');

  useEffect(() => {
    if (!competition) {
      setState('paused');
      return undefined;
    }
    return startCompetitionLiveUpdates(competition, queryClient, setState);
  }, [competition?.id, competition?.state, queryClient]);

  return competition?.state === 'RUNNING' ? state : 'paused';
}

export function startCompetitionLiveUpdates(
  competition: Competition,
  queryClient: QueryClient,
  setState: (state: 'paused' | 'connected' | 'reconnecting') => void,
): () => void {
  const refresh = (): void => {
    const refreshPrefixes: readonly (readonly unknown[])[] = [
      ...competitionLiveReadPrefixes(competition.id),
      competitionReads.competitions(),
      competitionReads.status(),
      competitionReads.ticker(competition.id),
      competitionReads.models(),
    ];
    for (const queryKey of refreshPrefixes) {
      const queries = queryClient.getQueryCache().findAll({ queryKey, exact: queryKey.length === 2 });
      for (const query of queries) {
        if (!canAutomaticallyRetry(query.state.error, query.state.errorUpdatedAt)) continue;
        void queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true });
      }
    }
  };

  if (competition.state === 'PAUSED') {
    setState('paused');
    const refreshWhenVisible = (): void => {
      if (document.visibilityState === 'visible') refresh();
    };
    const refreshTimer = window.setInterval(refreshWhenVisible, liveMarketRefreshMs);
    return () => window.clearInterval(refreshTimer);
  }

  if (competition.state !== 'RUNNING') {
    setState('paused');
    return () => undefined;
  }

  const source = new EventSource(`/api/v1/public/competitions/${encodeURIComponent(competition.id)}/stream`);
  let fallback = 0;
  source.onopen = () => {
    setState('connected');
    window.clearInterval(fallback);
    fallback = 0;
  };
  source.onmessage = refresh;
  source.onerror = () => {
    setState('reconnecting');
    if (!fallback) fallback = window.setInterval(refresh, liveMarketRefreshMs);
  };
  return () => {
    source.close();
    window.clearInterval(fallback);
    setState('paused');
  };
}

