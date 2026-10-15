import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AdminApiError, changeCompetition, getAdminStatus, login, logout, type CompetitionAction } from './api';
import { AdminManagement } from './management';

export function AdminApp(): React.JSX.Element {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['admin-status'], queryFn: getAdminStatus, retry: false });
  const logoutMutation = useMutation({ mutationFn: logout, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-status'] }) });
  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: CompetitionAction }) => changeCompetition(id, action),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-status'] }),
  });
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<Error | null>(null);
  const accessDenied = status.error instanceof AdminApiError && (status.error.status === 403 || status.error.status === 404);
  const loginAccessDenied = loginError instanceof AdminApiError && loginError.status === 404;
  const unauthenticated = status.error instanceof AdminApiError && status.error.status === 401;

  function submitLogin(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const credentials = { username: String(data.get('username') ?? ''), password: String(data.get('password') ?? '') };
    form.reset();
    setLoginBusy(true); setLoginError(null);
    void login(credentials.username, credentials.password)
      .then(() => queryClient.invalidateQueries({ queryKey: ['admin-status'] }))
      .catch((error: unknown) => setLoginError(error instanceof Error ? error : new Error('Sign-in failed')))
      .finally(() => setLoginBusy(false));
  }

  function runAction(id: string, action: CompetitionAction): void {
    actionMutation.mutate({ id, action });
  }

  return <div className="admin-shell">
    <header className="admin-header"><a href="/" className="admin-brand">OPEN ALPHA ARENA LAB <span>/ ADMIN</span></a><a href="/simulation">Public simulation</a></header>
    <main className="admin-main">
      <p className="admin-kicker">CONTROL PLANE</p><h1>Competition administration</h1>
      <p className="admin-lede">Access is checked by the platform and the API. This page never stores provider credentials.</p>
      {status.isLoading && <div className="admin-state" role="status">Checking admin identity…</div>}
      {accessDenied && <div className="admin-state admin-warning" role="alert"><h2>Access identity required</h2><p>The admin API did not authorize this request. Sign in through the configured Access identity provider, then reload this page.</p><button onClick={() => void status.refetch()}>Check access again</button></div>}
      {loginAccessDenied && <div className="admin-state admin-warning" role="alert"><h2>Access identity required</h2><p>The API does not accept local passwords in Access mode. Sign in through the configured identity provider.</p><button onClick={() => { setLoginError(null); void status.refetch(); }}>Check access again</button></div>}
      {status.error && !accessDenied && !unauthenticated && !status.isLoading && <div className="admin-state admin-error" role="alert"><h2>Admin API unavailable</h2><p>{status.error.message}</p><button onClick={() => void status.refetch()}>Retry status request</button></div>}
      {unauthenticated && !loginAccessDenied && <form className="login-form" onSubmit={submitLogin}>
        <h2>Local operator sign-in</h2><p>The API rejected the current session. Local credentials are sent to the API over this origin.</p>
        <label>Username<input name="username" type="text" autoComplete="username" required /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
        {loginError && <p className="form-error" role="alert">{loginError.message}</p>}
        <button type="submit" disabled={loginBusy}>{loginBusy ? 'Signing in…' : 'Sign in'}</button>
      </form>}
      {status.data?.authenticated && <section className="admin-console">
        <div className="identity-bar"><span>Signed in as <strong>{status.data.identity}</strong></span><span>Auth mode {status.data.auth_mode}</span>{status.data.auth_mode === 'local' && <button onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending}>{logoutMutation.isPending ? 'Signing out…' : 'Sign out'}</button>}</div>
        {logoutMutation.error && <p className="form-error" role="alert">{logoutMutation.error.message}</p>}
        <div className="section-title"><div><h2>Competitions</h2><p>Create draft runs and apply the state transitions exposed by the admin API.</p></div><span>{status.data.competitions.length} records</span></div>
        {actionMutation.error && <p className="form-error" role="alert">{actionMutation.error.message}</p>}
        <div className="admin-competition-list">{status.data.competitions.map((competition) => <article className="admin-competition" key={competition.id}>
          <div><p className="admin-kicker">{competition.profile} · {competition.source_label}</p><h3>{competition.name}</h3><code>{competition.id}</code></div>
          <span className={`admin-state-tag tag-${competition.state.toLowerCase()}`}>{competition.state}</span>
          <div className="admin-actions">{actionsFor(competition.state).map((action) => <button key={action} onClick={() => runAction(competition.id, action)} disabled={actionMutation.isPending}>{action}</button>)}</div>
        </article>)}</div>
        {status.data.competitions.length === 0 && <p className="admin-state">No competitions are registered.</p>}
        <AdminManagement />
      </section>}
      {actionMutation.data && actionMutation.variables && <p className="admin-feedback" role="status">The {actionMutation.variables.action} request was accepted for {actionMutation.variables.id}. The competition list has been refreshed.</p>}
    </main>
    <footer className="admin-footer"><span>Admin API contract · public and admin schemas are generated separately</span><a href="/">Open Alpha Arena Lab</a></footer>
  </div>;
}

function actionsFor(state: string): CompetitionAction[] {
  if (state === 'DRAFT') return ['start'];
  if (state === 'RUNNING') return ['pause', 'finish'];
  if (state === 'PAUSED') return ['resume', 'finish'];
  return [];
}
