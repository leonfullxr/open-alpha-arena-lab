import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { getCompetition, getLeaderboard } from './api';
import { AgentLink, money, PageHeading, QueryState } from './ui';

export default function ModelsDirectoryPage(): React.JSX.Element {
  const { competitionId = '' } = useParams();
  const competition = useQuery({ queryKey: ['competition', competitionId], queryFn: () => getCompetition(competitionId), enabled: Boolean(competitionId) });
  const rankings = useQuery({ queryKey: ['competition', competitionId, 'leaderboard'], queryFn: () => getLeaderboard(competitionId), enabled: Boolean(competitionId) });

  return <QueryState loading={competition.isLoading} error={competition.error} retry={() => void competition.refetch()}>
    {competition.data && <>
      <PageHeading eyebrow={`${competition.data.profile.replaceAll('_', ' ')} · ${competition.data.name}`} title="Models & agents" detail="Browse every account in this simulation and open its performance, positions, fills, and decision history." />
      {rankings.error && <div className="metric-availability" role="status">Performance data is unavailable. Model profiles are still available: {rankings.error.message}</div>}
      {competition.data.agents.length === 0 ? <div className="query-state">This simulation has no registered model accounts.</div> : <div className="table-scroll model-directory-table" role="region" tabIndex={0} aria-label="Models and agents, scroll horizontally for more details"><table>
        <thead><tr><th>Rank</th><th>Model</th><th>Provider</th><th>Marked equity</th><th>Return</th><th>Fills</th></tr></thead>
        <tbody>{[...competition.data.agents].sort((left, right) => {
          const leftRank = rankings.data?.find((item) => item.agent_id === left.id)?.rank ?? Number.MAX_SAFE_INTEGER;
          const rightRank = rankings.data?.find((item) => item.agent_id === right.id)?.rank ?? Number.MAX_SAFE_INTEGER;
          return leftRank - rightRank;
        }).map((agent) => {
          const row = rankings.data?.find((item) => item.agent_id === agent.id);
          const returnPct = row ? Number(row.roi_pct) : null;
          return <tr key={agent.id}>
            <td>{row?.rank ?? '—'}</td>
            <td><AgentLink id={agent.id} name={agent.name} model={agent.model} competitionId={competition.data.id} /></td>
            <td>{agent.provider}</td>
            <td>{row ? money(row.equity) : rankings.isLoading ? 'Loading…' : '—'}</td>
            <td className={returnPct === null ? undefined : returnPct >= 0 ? 'value-positive' : 'value-negative'}>{returnPct === null ? '—' : `${returnPct > 0 ? '+' : ''}${returnPct.toFixed(2)}%`}</td>
            <td>{row?.trade_count.toLocaleString() ?? '—'}</td>
          </tr>;
        })}</tbody>
      </table></div>}
    </>}
  </QueryState>;
}
