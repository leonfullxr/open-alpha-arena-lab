import { createContext, useContext, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { isPublicApiError, type PublicApiError } from './api';

const ApiAvailabilityContext = createContext<{ error?: PublicApiError; hasStaleData: boolean }>({ hasStaleData: false });

export function ApiAvailabilityProvider({ error, hasStaleData, children }: { error?: PublicApiError; hasStaleData: boolean; children: ReactNode }): React.JSX.Element {
  return <ApiAvailabilityContext.Provider value={{ error, hasStaleData }}>{children}</ApiAvailabilityContext.Provider>;
}

export function useApiAvailability(): { error?: PublicApiError; hasStaleData: boolean } {
  return useContext(ApiAvailabilityContext);
}

export function QueryState({ loading, error, retry, empty, stale, children }: {
  loading?: boolean;
  error?: Error | null;
  retry?: () => void;
  empty?: string;
  stale?: boolean;
  children?: React.ReactNode;
}): React.JSX.Element {
  const availability = useApiAvailability();
  if (loading) return <div className="query-state" role="status">Loading public records…</div>;
  if (error && availability.error && isPublicApiError(error) && isOutageKind(error)) return stale ? <>{children}</> : <></>;
  if (error && !stale) return <div className="query-error" role="status"><span>{error.message}</span>{retry && <button aria-label="Retry public data" onClick={retry}>Retry</button>}</div>;
  if (error && stale) return <><div className="query-stale" role="status"><span>Showing the last available data. {error.message}</span>{retry && <button aria-label="Retry public data" onClick={retry}>Retry</button>}</div>{children}</>;
  if (empty) return <div className="query-state">{empty}</div>;
  return <>{children}</>;
}

function isOutageKind(error: PublicApiError): boolean {
  return error.kind === 'service' || error.kind === 'rate-limit' || error.kind === 'offline' || error.kind === 'invalid-response';
}

export function StatusBadge({ state }: { state: string }): React.JSX.Element {
  const normalized = state.toUpperCase();
  return <span className={`status-badge status-${normalized.toLowerCase()}`}>{normalized}</span>;
}

export function DataStatus({ state, label }: { state: string; label: string }): React.JSX.Element {
  return <span className="data-status"><i className={`state-dot ${state === 'RUNNING' ? 'state-dot--live' : ''}`} />{label}</span>;
}

export function AgentLink({ id, name, model, competitionId, toneClass }: { id: string; name: string; model?: string; competitionId: string; toneClass: string }): React.JSX.Element {
  return <Link className={`model-link ${toneClass}`} to={`/simulation/${encodeURIComponent(competitionId)}/models/${encodeURIComponent(id)}`}><i className="model-swatch" aria-hidden="true" /><span>{name}</span>{model && <small>{model}</small>}</Link>;
}

export function money(value: string | number, currency = 'USD'): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount) : 'N/A';
}

export function decimal(value: string | number, digits = 2): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : 'N/A';
}

export function percent(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return 'N/A';
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}%` : 'N/A';
}

export function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function shortTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const month = `${date.getUTCMonth() + 1}`.padStart(2, '0');
  const day = `${date.getUTCDate()}`.padStart(2, '0');
  return `${month}/${day} ${`${date.getUTCHours()}`.padStart(2, '0')}:${`${date.getUTCMinutes()}`.padStart(2, '0')}`;
}

export function decodeBase64Safely(value: string): { bytes: Uint8Array | null; error: string | null } {
  try {
    const binary = atob(value);
    return { bytes: Uint8Array.from(binary, (character) => character.charCodeAt(0)), error: null };
  } catch (error) {
    return { bytes: null, error: error instanceof Error ? error.message : 'Invalid base64 data' };
  }
}

export function shortHash(value: string | null | undefined): string {
  return value ? `${value.slice(0, 12)}…` : 'Not stored';
}

export async function sha256Hex(bytes: Uint8Array): Promise<string | 'unavailable'> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  } catch {
    return 'unavailable';
  }
}
