import { Link } from 'react-router-dom';

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
  const normalized = state.toUpperCase();
  return <span className={`status-badge status-${normalized.toLowerCase()}`}>{normalized}</span>;
}

export function AgentLink({ id, name, model, competitionId }: { id: string; name: string; model?: string; competitionId: string }): React.JSX.Element {
  return <Link className="model-link" to={`/simulation/${encodeURIComponent(competitionId)}/models/${encodeURIComponent(id)}`}><span>{name}</span>{model && <small>{model}</small>}</Link>;
}

export function money(value: string | number, currency = 'USD'): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount) : 'N/A';
}

export function decimal(value: string | number, digits = 2): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : 'N/A';
}

export function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function DataStatus({ state, label }: { state: string; label: string }): React.JSX.Element {
  return <span className="data-status"><i className={`state-dot ${state === 'RUNNING' ? 'state-dot--live' : ''}`} />{label}</span>;
}
