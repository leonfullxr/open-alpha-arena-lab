import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitions, getStatus, type Competition } from './api';
import { modelToneClass, profileTag } from './colors';
import { AgentLink, money, QueryState, StatusBadge, timestamp, useApiAvailability } from './ui';

const PROFILE_NOTES: Record<string, string> = {
  alpha_2025_baseline: 'Runs in this baseline profile share a fixed market snapshot, prompt, rules, symbol universe and execution quote set. Comparisons inside this profile stay directly comparable.',
  research_extended: 'Separate ranking for experiments that change tools, strategies, assets, memory or execution policy. Results here are not compared against the baseline.',
};

export default function DirectoryPage(): React.JSX.Element {
  const location = useLocation();
  const query = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus });
  const availability = useApiAvailability();
  const competitions = [...(query.data ?? [])].sort((left, right) => Number(isTestFixture(left.source_label)) - Number(isTestFixture(right.source_label)));
  const baseline = competitions.filter((item) => item.profile === 'alpha_2025_baseline');
  const extended = competitions.filter((item) => item.profile === 'research_extended');
  const other = competitions.filter((item) => item.profile !== 'alpha_2025_baseline' && item.profile !== 'research_extended');
  const agents = competitions.reduce((sum, item) => sum + item.agents.length, 0);
  const live = competitions.filter((item) => item.state === 'RUNNING' || item.state === 'PAUSED').length;
  const requestedRunId = new URLSearchParams(location.search).get('run');
  const selectedRun = requestedRunId ? competitions.find((item) => item.id === requestedRunId) : undefined;
  const exampleRun = selectedRun ?? competitions[0];

  return <>
    <h1 className="visually-hidden">Open Alpha Arena Lab live research notes</h1>
    <div className="index-narrative">
      {!(query.isError && availability.error && !exampleRun && !selectedRun) && <div className="index-notice" role="status">
        {selectedRun
          ? <p><b>RUN STATUS · {selectedRun.state}:</b> {selectedRun.name} · {selectedRun.profile} · {selectedRun.source_label} · {selectedRun.agents.length} {selectedRun.agents.length === 1 ? 'account' : 'accounts'}. All balances are virtual.</p>
          : exampleRun
            ? <p><b>PUBLIC RUN STATUS:</b> The API returns {competitions.length} published runs across {new Set(competitions.map((item) => item.profile)).size} profiles. Example: {exampleRun.name} · {exampleRun.state} · {exampleRun.profile} · {exampleRun.source_label}. All balances are virtual.</p>
            : query.isLoading
              ? <p><b>PUBLIC RUN STATUS:</b> Loading run records from the public API.</p>
              : query.isError
                ? availability.error ? null : <p><b>PUBLIC RUN STATUS:</b> Run records could not be loaded. Retry from the directory below.</p>
                : <p><b>PUBLIC RUN STATUS:</b> The public API has not published a run yet. All balances in this lab are virtual.</p>}
      </div>}
      <article className="index-prose">
        <p>Open Alpha Arena Lab runs controlled paper experiments. Within the baseline profile, accounts share a frozen market snapshot, prompt, rules, symbol universe and execution quote set. Every proposal passes risk checks before it can reach a virtual balance; decisions, fills, fees and funding entries stay attached to their run record.</p>
        <p>The laboratory separates two tracks. The baseline fixes its manifest before a run, so accounts inside it remain directly comparable. Extended research may change tools, strategies, assets or execution policy, and is reported separately from the baseline.</p>
        <p>Public evidence is a projection, not a window into private computation. Justifications, proposals, hashes and frozen rules are published when available, so a reader can audit the record without exposing provider credentials or hidden reasoning.</p>
      </article>
      <div className="index-narrative-cta">{exampleRun && <Link to={`/simulation/${encodeURIComponent(exampleRun.id)}`}>OPEN {selectedRun ? 'THIS RUN' : 'THE AVAILABLE RUN'} CHART →</Link>}</div>
    </div>
    <details className="index-directory-details">
      <summary>RUN DATA AND PUBLIC DIRECTORY{query.data !== undefined ? ` · ${competitions.length} RECORDS` : ''}</summary>
      <QueryState loading={query.isLoading} error={query.error} stale={Boolean(query.data)} retry={() => void query.refetch()} empty={competitions.length === 0 ? 'The public API has no competitions yet.' : undefined}>
        {selectedRun && <section className="selected-run-data" aria-labelledby="selected-run-title">
          <div><p className="terminal-eyebrow">SELECTED PUBLIC RUN</p><h2 id="selected-run-title">{selectedRun.name}</h2></div><StatusBadge state={selectedRun.state} />
          <dl><div><dt>Profile</dt><dd><code>{selectedRun.profile}</code></dd></div><div><dt>Source</dt><dd>{selectedRun.source_label}</dd></div><div><dt>Window</dt><dd>{selectedRun.started_at ? `${timestamp(selectedRun.started_at)} → ${selectedRun.ended_at ? timestamp(selectedRun.ended_at) : 'open'}` : 'Not started'}</dd></div><div><dt>Accounts</dt><dd>{selectedRun.agents.map((agent) => agent.name).join(' · ') || 'None listed'}</dd></div></dl>
          <Link className="row-action" to={`/simulation/${encodeURIComponent(selectedRun.id)}`}>OPEN THIS RUN CHART →</Link>
        </section>}
        <dl className="index-stats">
          <div><dt>PUBLIC RUNS</dt><dd>{query.isLoading && query.data === undefined ? '—' : query.data === undefined ? 'Unavailable' : competitions.length}</dd></div>
          <div><dt>ACCOUNTS</dt><dd>{query.isLoading && query.data === undefined ? '—' : query.data === undefined ? 'Unavailable' : agents}</dd></div>
          <div><dt>LIVE OR PAUSED</dt><dd>{query.isLoading && query.data === undefined ? '—' : query.data === undefined ? 'Unavailable' : live}</dd></div>
          <div><dt>DATA MODE</dt><dd>{status.isLoading && status.data === undefined ? '—' : status.data === undefined ? 'Unavailable' : status.data.demo_label}</dd></div>
        </dl>
      <section className="index-section" aria-labelledby="index-runs">
        <div className="index-section-heading"><p className="terminal-eyebrow">RUN DIRECTORY</p><h2 id="index-runs">Every published run</h2><p className="page-detail">Choose a run to read its public entry, then open the chart and full evidence record.</p></div>
        <ProfileSection title="alpha_2025_baseline" competitions={baseline} />
        <ProfileSection title="research_extended" competitions={extended} />
        {other.length > 0 && <ProfileSection title="Other profiles" competitions={other} />}
      </section>
      </QueryState>
    </details>
  </>;
}

function ProfileSection({ title, competitions }: { title: string; competitions: Competition[] }): React.JSX.Element | null {
  if (competitions.length === 0) return null;
  const id = `profile-${title.replace(/[^a-z0-9]+/gi, '-')}`;
  return <section className="index-profile" aria-labelledby={id}>
    <div className="index-profile-heading"><div><h3 id={id}>{title}</h3><p>{PROFILE_NOTES[title] ?? 'The API reports this profile without a published display definition.'}</p></div><span>{competitions.length} {competitions.length === 1 ? 'run' : 'runs'}</span></div>
    <div className="table-scroll run-table"><table><thead><tr>
      <th>RUN</th><th>PROFILE</th><th>STATE</th><th>CAPITAL</th><th>ACCOUNTS</th><th>WINDOW</th><th>SOURCE</th><th>LIVE NOTE</th><th>CHART</th>
    </tr></thead><tbody>
      {competitions.map((competition) => <tr key={competition.id}>
        <td><Link className="run-name" to={`/simulation?run=${encodeURIComponent(competition.id)}`}>{competition.name}</Link></td>
        <td><span className="profile-tag">{profileTag(competition.profile)}</span></td>
        <td><StatusBadge state={competition.state} /></td>
        <td className="tabular">{money(competition.initial_balance)}</td>
        <td>{competition.agents.length}</td>
        <td className="run-window">{competition.started_at ? `${compact(competition.started_at)} → ${competition.ended_at ? compact(competition.ended_at) : 'open'}` : 'Not started'}</td>
        <td className="run-source" title={competition.source_label}>{competition.source_label}</td>
        <td><Link className="row-action" to={`/simulation?run=${encodeURIComponent(competition.id)}`}>READ NOTE →</Link></td>
        <td><Link className="row-action" to={`/simulation/${encodeURIComponent(competition.id)}`}>OPEN CHART →</Link></td>
      </tr>)}
    </tbody></table></div>
    <ul className="index-account-links" aria-label="Accounts in this profile">
      {competitions.flatMap((competition) => competition.agents.map((agent) => <li key={agent.id}><AgentLink id={agent.id} name={agent.name} model={agent.model} competitionId={competition.id} toneClass={modelToneClass(competition.agents, agent.id)} /></li>))}
    </ul>
  </section>;
}

function compact(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toISOString().slice(5, 16).replace('T', ' ');
}

function isTestFixture(source: string): boolean {
  return source.toUpperCase().includes('TEST FIXTURE');
}
