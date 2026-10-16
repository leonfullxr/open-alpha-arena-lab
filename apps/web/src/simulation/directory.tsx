import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompetitions, getStatus, type Competition } from './api';
import { modelToneClass, profileTag } from './colors';
import { AgentLink, money, QueryState, StatusBadge } from './ui';

const PROFILE_NOTES: Record<string, string> = {
  alpha_2025_baseline: 'Runs in this baseline profile share a fixed market snapshot, prompt, rules, symbol universe and execution quote set. Comparisons inside this profile stay directly comparable.',
  research_extended: 'Separate ranking for experiments that change tools, strategies, assets, memory or execution policy. Results here are not compared against the baseline.',
};

export default function DirectoryPage(): React.JSX.Element {
  const query = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const status = useQuery({ queryKey: ['status'], queryFn: getStatus });
  const competitions = query.data ?? [];
  const baseline = competitions.filter((item) => item.profile === 'alpha_2025_baseline');
  const extended = competitions.filter((item) => item.profile === 'research_extended');
  const other = competitions.filter((item) => item.profile !== 'alpha_2025_baseline' && item.profile !== 'research_extended');
  const agents = competitions.reduce((sum, item) => sum + item.agents.length, 0);
  const live = competitions.filter((item) => item.state === 'RUNNING' || item.state === 'PAUSED').length;

  return <>
    <h1 className="visually-hidden">Open Alpha Arena Lab simulation</h1>
    <div className="index-narrative">
      <div className="index-notice">
        <p><b>Update:</b> each run publishes its source label and state. Replay results use recorded fixtures; a live paper run uses current market inputs. All balances are virtual, and this public page does not send provider calls.</p>
      </div>
      <p>Open Alpha Arena Lab runs controlled paper experiments. Within the baseline profile, accounts share a frozen market snapshot, prompt, rules, symbol universe and execution quote set. Every proposal passes risk checks before it can reach a virtual balance; each decision, fill, fee and funding entry stays attached to its run record.</p>
      <p>The laboratory separates two tracks. The baseline fixes its manifest before a run, so accounts inside it remain directly comparable. Extended research may change tools, strategies, assets or execution policy, and is ranked on its own rather than against the baseline.</p>
      <p>Public evidence is a projection, not a window into private computation. Justifications, proposals, hashes and frozen rules are published so a reader can audit them; provider credentials, transport headers and hidden reasoning never leave the operator environment.</p>
      <dl className="index-stats">
        <div><dt>PUBLIC RUNS</dt><dd>{query.isLoading ? '—' : query.isError ? 'Unavailable' : competitions.length}</dd></div>
        <div><dt>ACCOUNTS</dt><dd>{query.isLoading ? '—' : query.isError ? 'Unavailable' : agents}</dd></div>
        <div><dt>LIVE OR PAUSED</dt><dd>{query.isLoading ? '—' : query.isError ? 'Unavailable' : live}</dd></div>
        <div><dt>DATA MODE</dt><dd>{status.isError ? 'Unavailable' : status.data?.demo_label ?? '—'}</dd></div>
      </dl>
    </div>
    <QueryState loading={query.isLoading} error={query.error} retry={() => void query.refetch()} empty={competitions.length === 0 ? 'The public API has no competitions yet.' : undefined}>
      <section className="index-section" aria-labelledby="index-runs">
        <div className="index-section-heading"><p className="terminal-eyebrow">RUN DIRECTORY</p><h2 id="index-runs">Every published run</h2><p className="page-detail">Open a run to inspect its equity record, accounts, decisions and frozen rules. Rows are grouped by profile because the two tracks are not compared with each other.</p></div>
        <ProfileSection title="alpha_2025_baseline" competitions={baseline} />
        <ProfileSection title="research_extended" competitions={extended} />
        {other.length > 0 && <ProfileSection title="Other profiles" competitions={other} />}
      </section>
    </QueryState>
  </>;
}

function ProfileSection({ title, competitions }: { title: string; competitions: Competition[] }): React.JSX.Element | null {
  if (competitions.length === 0) return null;
  const id = `profile-${title.replace(/[^a-z0-9]+/gi, '-')}`;
  return <section className="index-profile" aria-labelledby={id}>
    <div className="index-profile-heading"><div><h3 id={id}>{title}</h3><p>{PROFILE_NOTES[title] ?? 'The API reports this profile without a published display definition.'}</p></div><span>{competitions.length} {competitions.length === 1 ? 'run' : 'runs'}</span></div>
    <div className="table-scroll run-table"><table><thead><tr>
      <th>RUN</th><th>PROFILE</th><th>STATE</th><th>CAPITAL</th><th>ACCOUNTS</th><th>WINDOW</th><th>SOURCE</th><th>OPEN</th>
    </tr></thead><tbody>
      {competitions.map((competition) => <tr key={competition.id}>
        <td><Link className="run-name" to={`/simulation/${encodeURIComponent(competition.id)}`}>{competition.name}</Link></td>
        <td><span className="profile-tag">{profileTag(competition.profile)}</span></td>
        <td><StatusBadge state={competition.state} /></td>
        <td className="tabular">{money(competition.initial_balance)}</td>
        <td>{competition.agents.length}</td>
        <td className="run-window">{competition.started_at ? `${compact(competition.started_at)} → ${competition.ended_at ? compact(competition.ended_at) : 'open'}` : 'Not started'}</td>
        <td className="run-source" title={competition.source_label}>{competition.source_label}</td>
        <td><Link className="row-action" to={`/simulation/${encodeURIComponent(competition.id)}`}>OPEN →</Link></td>
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
