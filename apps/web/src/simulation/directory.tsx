import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight } from 'lucide-react';
import { getCompetitions, type Competition } from './api';
import { money, PageHeading, QueryState, StatusBadge } from './ui';

export default function DirectoryPage(): React.JSX.Element {
  const query = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const baseline = query.data?.filter((item) => item.profile === 'alpha_2025_baseline') ?? [];
  const extended = query.data?.filter((item) => item.profile === 'research_extended') ?? [];
  const other = query.data?.filter((item) => item.profile !== 'alpha_2025_baseline' && item.profile !== 'research_extended') ?? [];

  return <>
    <PageHeading eyebrow="Public runs / index" title="Simulation directory" detail="Deterministic paper competitions and their inspectable records." />
    <QueryState loading={query.isLoading} error={query.error} retry={() => void query.refetch()} empty={query.data?.length === 0 ? 'The public API has no competitions yet.' : undefined}>
      {query.data && <>
        <ProfileSection title="Baseline" description="Shared symbols, market inputs, prompt, rules, and execution quote set." competitions={baseline} />
        <ProfileSection title="Extended research" description="Separate comparisons for experiments that change tools, strategies, assets, memory, or execution policy." competitions={extended} />
        {other.length > 0 && <ProfileSection title="Other profiles" description="The API reports these profiles without a published display definition." competitions={other} />}
      </>}
    </QueryState>
  </>;
}

function ProfileSection({ title, description, competitions }: { title: string; description: string; competitions: Competition[] }): React.JSX.Element {
  const id = `profile-${title.replace(/[^a-z0-9]+/gi, '-')}`;
  return <section className="directory-section" aria-labelledby={id}>
    <div className="section-heading"><div><p className="terminal-eyebrow">Public profile</p><h2 id={id}>{title}</h2><p className="page-detail">{description}</p></div><span className="record-count">{competitions.length} {competitions.length === 1 ? 'competition' : 'competitions'}</span></div>
    {competitions.length === 0 ? <div className="empty-profile">No competitions for this profile.</div> : <div className="competition-list">
      {competitions.map((competition) => <article className="competition-row" key={competition.id}>
        <div><Link className="competition-name" to={`/simulation/${encodeURIComponent(competition.id)}`}>{competition.name}<ArrowUpRight aria-hidden="true" size={14} /></Link><p>{competition.source_label}</p></div>
        <div className="competition-meta"><span>{competition.agents.length} accounts</span><span>{money(competition.initial_balance)} starting capital</span><StatusBadge state={competition.state} /></div>
        <div className="competition-agents" aria-label="Accounts">{competition.agents.map((agent) => <Link key={agent.id} to={`/simulation/${encodeURIComponent(competition.id)}/models/${encodeURIComponent(agent.id)}`}>{agent.name}<ArrowUpRight aria-hidden="true" size={12} /></Link>)}</div>
        <Link className="row-action" to={`/simulation/${encodeURIComponent(competition.id)}`} aria-label={`Open ${competition.name}`}>Open <ArrowUpRight aria-hidden="true" size={15} /></Link>
      </article>)}
    </div>}
  </section>;
}
