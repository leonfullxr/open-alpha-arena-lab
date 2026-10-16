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
export type RulesArtifact = PublicSchema['RulesArtifactDTO'];
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
type PositionHistoryQuery = HistoryQuery & { include_closed?: boolean };

const client = createClient<paths>({ baseUrl: '/api/v1/public' });

export type PublicApiFailureKind = 'service' | 'rate-limit' | 'not-found' | 'domain' | 'offline' | 'invalid-response' | 'unknown';

export class PublicApiError extends Error {
  constructor(
    message: string,
    readonly kind: PublicApiFailureKind,
    readonly status?: number,
    readonly code?: string,
    readonly retryable = false,
    readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = 'PublicApiError';
  }
}

export function isPublicApiError(error: unknown): error is PublicApiError {
  return error instanceof PublicApiError;
}

export function nextPollInterval(defaultMs: number, error: unknown): number | false {
  if (!isPublicApiError(error)) return defaultMs;
  if (!error.retryable) return false;
  if (error.kind === 'service' || error.kind === 'rate-limit') return retryCooldownMs(error);
  return Math.max(defaultMs, error.retryAfterMs ?? 0);
}

export function canAutomaticallyRetry(error: unknown, errorUpdatedAt: number): boolean {
  if (!isPublicApiError(error)) return true;
  if (!error.retryable) return false;
  return Date.now() - errorUpdatedAt >= retryCooldownMs(error);
}

function retryCooldownMs(error: PublicApiError): number {
  return error.kind === 'service' || error.kind === 'rate-limit'
    ? Math.max(30_000, error.retryAfterMs ?? 0)
    : error.retryAfterMs ?? 0;
}

type ApiResult<T> = { data?: T; error?: unknown; response: Response };

async function requireData<T>(request: Promise<ApiResult<T>>): Promise<T> {
  let result: ApiResult<T>;
  try {
    result = await request;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new PublicApiError('The public service returned an unreadable response. Please try again shortly.', 'invalid-response', undefined, undefined, false);
    }
    if (error instanceof TypeError) {
      throw new PublicApiError('The public service could not be reached. Check your connection and retry.', 'offline', undefined, undefined, true);
    }
    throw new PublicApiError('The public request could not be completed. Please try again.', 'unknown');
  }

  if (result.error !== undefined || !result.response.ok) {
    const status = result.response.status;
    const body = parseErrorBody(result.error);
    const retryAfterMs = readRetryAfter(result.response.headers.get('retry-after'));
    const retryable = body.retryable ?? (status === 429 || status >= 500);
    const kind = failureKind(status);
    const message = failureMessage({ status, code: body.code, retryable, kind });
    throw new PublicApiError(message, kind, status, body.code, retryable, retryAfterMs);
  }
  if (result.data === undefined) {
    throw new PublicApiError('The public service returned an empty response. Please retry.', 'invalid-response');
  }
  return result.data;
}

function parseErrorBody(value: unknown): { code?: string; retryable?: boolean } {
  if (typeof value !== 'object' || value === null) return {};
  const errorCode = 'error' in value && typeof value.error === 'string' ? value.error : undefined;
  const legacyCode = 'code' in value && typeof value.code === 'string' ? value.code : undefined;
  const retryable = 'retryable' in value && typeof value.retryable === 'boolean' ? value.retryable : undefined;
  const code = errorCode ?? legacyCode;
  return {
    code: code && /^[a-z0-9_]{1,64}$/i.test(code) ? code : undefined,
    retryable,
  };
}

function failureKind(status: number): PublicApiFailureKind {
  if (status === 429) return 'rate-limit';
  if (status === 404) return 'not-found';
  if (status >= 500) return 'service';
  return 'domain';
}

function failureMessage({ status, code, retryable, kind }: {
  status: number;
  code?: string;
  retryable: boolean;
  kind: PublicApiFailureKind;
}): string {
  if (kind === 'rate-limit') return 'The public service is receiving a lot of requests. Please wait a moment and retry.';
  if (kind === 'service') {
    if (status === 503 && !retryable && (code === 'origin_unavailable' || code === 'rate_limit_unavailable')) return 'The research data service is not connected yet.';
    return 'The public simulation service is temporarily unavailable. Please try again shortly.';
  }
  if (kind === 'not-found') return 'This public record could not be found.';
  switch (code) {
    case 'invalid_request': return 'One or more request values are invalid.';
    case 'query_limit_exceeded': return 'One or more requested values exceed the supported limits.';
    case 'conflict': return 'This request conflicts with the current public record.';
    case 'method_not_allowed': return 'This method is not available for this public record.';
  }
  if (status === 401 || status === 403 || code === 'admin_access_required') return 'This public request is not available.';
  return 'The public request could not be completed. Please check the request and retry.';
}

function readRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, 5 * 60_000);
  const date = Date.parse(value);
  return Number.isNaN(date) ? undefined : Math.min(Math.max(date - Date.now(), 0), 5 * 60_000);
}

export async function getStatus(): Promise<Status> {
  return requireData(client.GET('/status'));
}

export async function getTicker(competitionId?: string): Promise<TickerItem[]> {
  return requireData(client.GET('/ticker', { params: { query: competitionId ? { competition_id: competitionId } : {} } }));
}

export async function getCompetitions(): Promise<Competition[]> {
  return requireData(client.GET('/competitions'));
}

export async function getCompetition(id: string): Promise<Competition> {
  return requireData(client.GET('/competitions/{competition_id}', { params: { path: { competition_id: id } } }));
}

export async function getLeaderboard(id: string): Promise<LeaderboardRow[]> {
  return requireData(client.GET('/competitions/{competition_id}/leaderboard', { params: { path: { competition_id: id } } }));
}

export async function getCompetitionMetrics(id: string): Promise<CompetitionMetrics> {
  return requireData(client.GET('/competitions/{competition_id}/metrics', { params: { path: { competition_id: id } } }));
}

export async function getModel(id: string): Promise<Model> {
  return requireData(client.GET('/models/{agent_id}', { params: { path: { agent_id: id } } }));
}

export async function getArtifact(id: string): Promise<Artifact> {
  return requireData(client.GET('/decisions/{decision_id}/artifact', { params: { path: { decision_id: id } } }));
}

export async function getEquityChart(id: string, range: EquityRange): Promise<EquityChartData> {
  return requireData(client.GET('/competitions/{competition_id}/chart', {
    params: { path: { competition_id: id }, query: { range, points: 400 } },
  }));
}

export function getTradeHistory(id: string, query: HistoryQuery): Promise<TradePage> {
  return requireData(client.GET('/competitions/{competition_id}/trades', {
    params: { path: { competition_id: id }, query },
  }));
}

export function getPositionHistory(id: string, query: PositionHistoryQuery): Promise<PositionPage> {
  return requireData(client.GET('/competitions/{competition_id}/positions', {
    params: { path: { competition_id: id }, query: { ...query, include_closed: query.include_closed ?? true } },
  }));
}

export function getFundingHistory(id: string, query: HistoryQuery): Promise<FundingPage> {
  return requireData(client.GET('/competitions/{competition_id}/funding', {
    params: { path: { competition_id: id }, query },
  }));
}

export async function getFundingEvidence(id: string): Promise<FundingEvidence> {
  return requireData(client.GET('/funding/evidence/{evidence_id}', {
    params: { path: { evidence_id: id } },
  }));
}

export async function getCompetitionRules(id: string): Promise<RulesArtifact> {
  return requireData(client.GET('/competitions/{competition_id}/rules', {
    params: { path: { competition_id: id } },
  }));
}

export function getDecisionHistory(id: string, query: HistoryQuery): Promise<DecisionPage> {
  return requireData(client.GET('/competitions/{competition_id}/decisions', {
    params: { path: { competition_id: id }, query },
  }));
}

export async function getEvents(id: string, after = 0): Promise<EventPage> {
  return requireData(client.GET('/competitions/{competition_id}/events', {
    params: { path: { competition_id: id }, query: { after, limit: 100 } },
  }));
}
