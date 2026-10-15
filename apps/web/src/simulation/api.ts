import createClient from 'openapi-fetch';
import type { components, paths } from '../api/public.generated';

export type PublicSchema = components['schemas'];
export type Competition = PublicSchema['CompetitionSummary'];
export type Agent = PublicSchema['AgentSummary'];
export type EquityPoint = PublicSchema['EquityPoint'];
export type LeaderboardRow = PublicSchema['LeaderboardRow'];
export type Trade = PublicSchema['TradeDTO'];
export type Position = PublicSchema['PositionDTO'];
export type FundingPayment = PublicSchema['FundingPaymentDTO'];
export type FundingEvidence = PublicSchema['FundingEvidenceArtifactDTO'];
export type FundingPage = PublicSchema['PageDTO_FundingPaymentDTO_'];
export type Decision = PublicSchema['DecisionDTO'];
export type Artifact = PublicSchema['ArtifactDTO'];
export type EventPage = PublicSchema['EventPageDTO'];
export type Model = PublicSchema['ModelDTO'];
export type TickerItem = PublicSchema['TickerItem'];
export type Status = PublicSchema['StatusDTO'];
export type CompetitionMetrics = PublicSchema['CompetitionMetricsDTO'];
export type AgentMetrics = PublicSchema['AgentMetricsDTO'];
export type Benchmark = PublicSchema['BenchmarkDTO'];
export type TradePage = PublicSchema['PageDTO_TradeDTO_'];
export type PositionPage = PublicSchema['PageDTO_PositionDTO_'];
export type DecisionPage = PublicSchema['PageDTO_DecisionDTO_'];
export type EquityChartData = PublicSchema['EquityChartDTO'];
export type EquityRange = 'ALL' | '72H' | '24H';

export type HistoryQuery = { limit: number; offset: number; agent_id?: string; symbol?: string };

const client = createClient<paths>({ baseUrl: '/api/v1/public' });

async function requireData<T>(result: { data?: T; error?: unknown; response: Response }): Promise<T> {
  if (result.error !== undefined) {
    const message = typeof result.error === 'object' && result.error !== null && 'detail' in result.error
      ? String(result.error.detail)
      : `${result.response.status} ${result.response.statusText}`;
    throw new Error(message || 'The public API request failed');
  }
  if (result.data === undefined) throw new Error('The API returned an empty response');
  return result.data;
}

export async function getStatus(): Promise<Status> {
  return requireData(await client.GET('/status'));
}

export async function getTicker(competitionId?: string): Promise<TickerItem[]> {
  return requireData(await client.GET('/ticker', { params: { query: competitionId ? { competition_id: competitionId } : {} } }));
}

export async function getCompetitions(): Promise<Competition[]> {
  return requireData(await client.GET('/competitions'));
}

export async function getCompetition(id: string): Promise<Competition> {
  return requireData(await client.GET('/competitions/{competition_id}', { params: { path: { competition_id: id } } }));
}

export async function getLeaderboard(id: string): Promise<LeaderboardRow[]> {
  return requireData(await client.GET('/competitions/{competition_id}/leaderboard', { params: { path: { competition_id: id } } }));
}

export async function getCompetitionMetrics(id: string): Promise<CompetitionMetrics> {
  return requireData(await client.GET('/competitions/{competition_id}/metrics', { params: { path: { competition_id: id } } }));
}

export async function getModel(id: string): Promise<Model> {
  return requireData(await client.GET('/models/{agent_id}', { params: { path: { agent_id: id } } }));
}

export async function getArtifact(id: string): Promise<Artifact> {
  return requireData(await client.GET('/decisions/{decision_id}/artifact', { params: { path: { decision_id: id } } }));
}

export async function getEquityChart(id: string, range: EquityRange): Promise<EquityChartData> {
  return requireData(await client.GET('/competitions/{competition_id}/chart', {
    params: { path: { competition_id: id }, query: { range, points: 400 } },
  }));
}

export function getTradeHistory(id: string, query: HistoryQuery): Promise<TradePage> {
  return client.GET('/competitions/{competition_id}/trades', {
    params: { path: { competition_id: id }, query },
  }).then(requireData);
}

export function getPositionHistory(id: string, query: HistoryQuery): Promise<PositionPage> {
  return client.GET('/competitions/{competition_id}/positions', {
    params: { path: { competition_id: id }, query: { ...query, include_closed: true } },
  }).then(requireData);
}

export function getFundingHistory(id: string, query: HistoryQuery): Promise<FundingPage> {
  return client.GET('/competitions/{competition_id}/funding', {
    params: { path: { competition_id: id }, query },
  }).then(requireData);
}

export async function getFundingEvidence(id: string): Promise<FundingEvidence> {
  return requireData(await client.GET('/funding/evidence/{evidence_id}', {
    params: { path: { evidence_id: id } },
  }));
}

export function getDecisionHistory(id: string, query: HistoryQuery): Promise<DecisionPage> {
  return client.GET('/competitions/{competition_id}/decisions', {
    params: { path: { competition_id: id }, query },
  }).then(requireData);
}

export async function getEvents(id: string, after = 0): Promise<EventPage> {
  return requireData(await client.GET('/competitions/{competition_id}/events', {
    params: { path: { competition_id: id }, query: { after, limit: 100 } },
  }));
}
