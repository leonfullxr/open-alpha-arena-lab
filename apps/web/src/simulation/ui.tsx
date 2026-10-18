import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';

export function QueryState({ loading, error, retry, empty, children }: {
  loading?: boolean;
  error?: Error | null;
  retry?: () => void;
  empty?: string;
  children?: React.ReactNode;
}): React.JSX.Element {
  if (loading) return <div className="query-state" role="status">Loading public records…</div>;
  if (error) return <div className="query-error" role="alert"><span>{error.message}</span>{retry && <button onClick={retry}>Retry</button>}</div>;
  if (empty) return <div className="query-state">{empty}</div>;
  return <>{children}</>;
}

export function PageHeading({ eyebrow, title, detail, children }: {
  eyebrow: string;
  title: string;
  detail?: string;
  children?: React.ReactNode;
}): React.JSX.Element {
  return <div className="page-heading"><div><p className="terminal-eyebrow">{eyebrow}</p><h1>{title}</h1>{detail && <p className="page-detail">{detail}</p>}</div>{children && <div className="heading-actions">{children}</div>}</div>;
}

export function StatusBadge({ state }: { state: string }): React.JSX.Element {
  const normalized = state.toLowerCase();
  const label = state.toLocaleLowerCase().replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase());
  return <span className={`status-badge status-${normalized}`}>{label}</span>;
}

export function profileLabel(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\p{L}/gu, (letter) => letter.toLocaleUpperCase());
}

export function AgentLink({ id, name, model, competitionId }: { id: string; name: string; model?: string; competitionId: string }): React.JSX.Element {
  return <Link className="model-link" to={`/simulation/${encodeURIComponent(competitionId)}/models/${encodeURIComponent(id)}`}><span className="model-link-name">{name}<ArrowUpRight aria-hidden="true" size={13} /></span>{model && <small>{model}</small>}</Link>;
}

export function money(value: string | number, currency = 'USD'): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? new Intl.NumberFormat(undefined, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount) : 'N/A';
}

export function marketPrice(value: string | number, currency = 'USD'): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'N/A';
  const minimumFractionDigits = amount >= 100 ? 0 : 2;
  const maximumFractionDigits = amount >= 100 ? 2 : amount >= 1 ? 4 : 6;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits,
    maximumFractionDigits,
  }).format(amount);
}

export function decimal(value: string | number, digits = 2): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }) : 'N/A';
}

export function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date)} UTC`;
}

export function DataStatus({ state, label }: { state: string; label: string }): React.JSX.Element {
  const sentence = label.toLocaleLowerCase().replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase());
  return <span className="data-status"><i className={`state-dot ${state === 'RUNNING' ? 'state-dot--live' : ''}`} />{sentence}</span>;
}
