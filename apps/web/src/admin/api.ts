import createClient from 'openapi-fetch';
import type { components, paths } from './admin.generated';

export type AdminSchema = components['schemas'];
export type AdminStatus = AdminSchema['AdminStatus'];
export type AdminCompetition = AdminSchema['AdminCompetition'];
export type LoginOut = AdminSchema['LoginOut'];
export type ProviderProfile = AdminSchema['ProviderProfileOut'];
export type ProviderProfileInput = AdminSchema['ProviderProfileIn'];
export type PromptVersion = AdminSchema['PromptVersionOut'];
export type PromptVersionInput = AdminSchema['PromptVersionIn'];
export type CompetitionInput = AdminSchema['CompetitionIn'];
export type CompetitionCreated = AdminSchema['CompetitionCreated'];
export type CompetitionAction = 'start' | 'pause' | 'resume' | 'finish';

export class AdminApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'AdminApiError'; }
}

const client = createClient<paths>({ baseUrl: '/api/v1/admin', credentials: 'include' });

async function data<T>(result: { data?: T; error?: unknown; response: Response }): Promise<T> {
  if (result.error !== undefined) {
    const detail = typeof result.error === 'object' && result.error !== null && 'detail' in result.error ? String(result.error.detail) : result.response.statusText;
    throw new AdminApiError(detail || 'Admin request failed', result.response.status);
  }
  if (result.data === undefined) throw new AdminApiError('The admin API returned an empty response', result.response.status);
  return result.data;
}

export async function getAdminStatus(): Promise<AdminStatus> { return data(await client.GET('/status')); }
export async function login(username: string, password: string): Promise<LoginOut> { return data(await client.POST('/login', { body: { username, password } })); }
export async function logout(): Promise<void> { await data(await client.POST('/logout')); }

export async function getProviders(): Promise<ProviderProfile[]> { return data(await client.GET('/providers')); }
export async function addProvider(input: ProviderProfileInput): Promise<ProviderProfile> { return data(await client.POST('/providers', { body: input })); }
export async function validateProvider(id: string): Promise<Record<string, string>> {
  return data(await client.POST('/providers/{provider_id}/test', { params: { path: { provider_id: id } } }));
}
export async function getPrompts(): Promise<PromptVersion[]> { return data(await client.GET('/prompts')); }
export async function addPrompt(input: PromptVersionInput): Promise<PromptVersion> { return data(await client.POST('/prompts', { body: input })); }
export async function createCompetition(input: CompetitionInput): Promise<CompetitionCreated> { return data(await client.POST('/competitions', { body: input })); }

export async function changeCompetition(id: string, action: CompetitionAction): Promise<Record<string, string>> {
  return data(await client.POST('/competitions/{competition_id}/{action}', { params: { path: { competition_id: id, action } } }));
}
