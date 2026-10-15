import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ActivityPanel } from './activity';
import { getCompetitions, getEquityHistory, getModel } from './api';
import { EquityChart } from './equity-chart';
import { useCompetitionStream } from './stream';
import { money, PageHeading, QueryState, StatusBadge } from './ui';

export default function ModelPage(): React.JSX.Element {
  const { competitionId = '', agentId = '' } = useParams();
  const modelQuery = useQuery({ queryKey: ['model', agentId], queryFn: () => getModel(agentId), enabled: Boolean(agentId) });
  const competitionsQuery = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const model = modelQuery.data;
  const competition = competitionsQuery.data?.find((item) => item.id === competitionId && item.id === model?.competition_id);
  const enabled = Boolean(competition);
  const equity = useQuery({ queryKey: ['competition', competition?.id, 'equity'], queryFn: () => getEquityHistory(competition!.id), enabled });
  const agent = competition?.agents.find((item) => item.id === agentId);
  useCompetitionStream(competition);

  return <>
    <QueryState loading={modelQuery.isLoading || competitionsQuery.isLoading} error={modelQuery.error ?? competitionsQuery.error} retry={() => void (modelQuery.isError ? modelQuery.refetch() : competitionsQuery.refetch())}>
      {model && <>
        <PageHeading eyebrow="MODEL ACCOUNT / PUBLIC DETAIL" title={model.name} detail={`${model.provider} · ${model.model}`}>
          <StatusBadge state={model.status} />
        </PageHeading>
        <div className="model-facts">
          <Fact label="Agent ID" value={model.id} />
          <Fact label="Competition" value={competition?.name ?? 'Not linked by the public API'} />
          <Fact label="Profile" value={competition?.profile ?? 'N/A'} />
          <Fact label="Source" value={model.source_label} />
          <Fact label="Provider credentials configured" value={model.api_key_configured ? 'Yes' : 'No'} />
          <Fact label="Model settings SHA-256" value={model.settings_sha256} />
          <Fact label="Prompt version SHA-256" value={model.prompt_sha256} />
        </div>
        {!competition || !agent ? <div className="metric-availability">This model is not listed in the selected competition.</div> : <>
          <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.filter((row) => row.agent_id === model.id).length === 0 ? 'No account equity records are available.' : undefined}>
            {equity.data && <EquityChart agents={[agent]} rows={equity.data.items.filter((row) => row.agent_id === model.id)} initialBalance={competition.initial_balance} sampleCount={equity.data.total} />}
          </QueryState>
          <section className="model-record-section"><h2>Fills</h2><ActivityPanel competitionId={competition.id} agentId={model.id} tab="Live Trades" /></section>
          <section className="model-record-section"><h2>Positions, open and closed</h2><ActivityPanel competitionId={competition.id} agentId={model.id} tab="Positions" /></section>
          <section className="model-record-section"><h2>Decisions and artifacts</h2><ActivityPanel competitionId={competition.id} agentId={model.id} tab="Model Chat" /></section>
          <p className="model-return">Starting equity {money(competition.initial_balance)} · model status {model.status}</p>
        </>}
      </>}
    </QueryState>
  </>;
}

function Fact({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
