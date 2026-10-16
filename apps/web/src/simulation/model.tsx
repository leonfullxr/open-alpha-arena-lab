import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ActivityPanel } from './activity';
import { getCompetitions, getEquityChart, getLeaderboard, getModel, type EquityRange } from './api';
import { modelToneClass, profileTag } from './colors';
import { EquityChart } from './equity-chart';
import { money, percent, QueryState, StatusBadge, timestamp } from './ui';

export default function ModelPage(): React.JSX.Element {
  const { competitionId = '', agentId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const highlightDecisionId = searchParams.get('decision') ?? undefined;
  const requestedRound = Number(searchParams.get('round'));
  const decisionRound = Number.isSafeInteger(requestedRound) && requestedRound > 0 ? requestedRound : undefined;
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const modelQuery = useQuery({ queryKey: ['model', agentId], queryFn: () => getModel(agentId), enabled: Boolean(agentId) });
  const competitionsQuery = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const rowQuery = useQuery({
    queryKey: ['competition', competitionId, 'leaderboard'],
    queryFn: () => getLeaderboard(competitionId),
    enabled: Boolean(competitionId),
  });
  const model = modelQuery.data;
  const publicSettings = model ? Object.entries(model.public_settings).sort(([left], [right]) => left.localeCompare(right)) : [];
  const competition = competitionsQuery.data?.find((item) => item.id === competitionId && item.id === model?.competition_id);
  const enabled = Boolean(competition);
  const equity = useQuery({ queryKey: ['competition', competition?.id, 'chart', chartRange], queryFn: () => getEquityChart(competition!.id, chartRange), enabled });
  const agent = competition?.agents.find((item) => item.id === agentId);
  const row = rowQuery.data?.find((item) => item.agent_id === agentId);

  return <>
    <QueryState loading={modelQuery.isLoading || competitionsQuery.isLoading} error={modelQuery.error ?? competitionsQuery.error} retry={() => void (modelQuery.isError ? modelQuery.refetch() : competitionsQuery.refetch())}>
      {model && <>
        <header className="run-header">
          <div className="run-title">
            <p className="terminal-eyebrow">MODEL ACCOUNT / PUBLIC DETAIL · {model.provider} · {model.model}</p>
            <h1>{model.name.toUpperCase()}</h1>
          </div>
          <div className="run-header-side">
            <span className={`model-tag ${modelToneClass(competition?.agents ?? [], model.id)}`}>{model.name.toUpperCase()}</span>
            <StatusBadge state={model.status} />
            {row && <span className="run-header-meta">EQUITY {money(row.equity)} · RETURN <span className={Number(row.roi_pct) >= 0 ? 'value-positive' : 'value-negative'}>{percent(row.roi_pct)}</span></span>}
            <span className="run-header-meta">{model.source_label}</span>
          </div>
        </header>
        <section className="model-facts" aria-label="Model facts">
          <Fact label="Agent ID" value={model.id} />
          <Fact label="Competition" value={competition?.name ?? 'Not linked by the public API'} />
          <Fact label="Profile" value={competition ? `${profileTag(competition.profile)} · ${competition.profile}` : model.profile} />
          <Fact label="Source" value={model.source_label} />
          <Fact label="Credential reference configured" value={model.credential_reference_configured ? 'Yes' : 'No'} />
          <Fact label="Model settings SHA-256" value={model.settings_sha256} />
          <Fact label="Prompt version SHA-256" value={model.prompt_sha256} />
          <Fact label="Run window" value={competition?.started_at ? `${timestamp(competition.started_at)} → ${competition.ended_at ? timestamp(competition.ended_at) : 'open'}` : 'Not started'} />
          <Fact label="Starting capital" value={competition ? money(competition.initial_balance) : 'N/A'} />
        </section>
        <section className="model-settings" aria-labelledby="public-settings-title">
          <div className="panel-heading"><div><p className="terminal-eyebrow">PUBLISHED BY THE API</p><h2 id="public-settings-title">PUBLIC MODEL SETTINGS</h2></div></div>
          {publicSettings.length ? <dl>{publicSettings.map(([key, value]) => <div key={key}><dt>{settingLabel(key)}</dt><dd>{String(value)}</dd></div>)}</dl> : <p className="query-state">No public setting values were returned.</p>}
        </section>
        {!competition || !agent ? <div className="metric-availability">This model is not listed in the selected competition.</div> : <>
          <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.filter((record) => record.agent_id === model.id).length === 0 ? 'No account equity records are available.' : undefined}>
            <div className="model-chart">
              {equity.data && <EquityChart agents={[agent]} colorAgents={competition.agents} rows={equity.data.items.filter((record) => record.agent_id === model.id)} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} />}
            </div>
          </QueryState>
          <section className="model-record-section">
            <div className="panel-heading"><div><p className="terminal-eyebrow">PAPER EXECUTION</p><h2>FILLS</h2></div></div>
            <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Live Trades" />
          </section>
          <section className="model-record-section">
            <div className="panel-heading"><div><p className="terminal-eyebrow">PAPER POSITIONS</p><h2>POSITIONS, OPEN AND CLOSED</h2></div></div>
            <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Positions" />
          </section>
          <section className="model-record-section">
            <div className="panel-heading"><div><p className="terminal-eyebrow">PUBLIC DECISION RECORD</p><h2>DECISIONS AND ARTIFACTS</h2></div></div>
            <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Model Chat" highlightDecisionId={highlightDecisionId} decisionRound={decisionRound} />
          </section>
          <p className="model-return">Starting equity {money(competition.initial_balance)} · model status {model.status} · {model.provider} {model.model}</p>
        </>}
      </>}
    </QueryState>
  </>;
}

function Fact({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function settingLabel(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}
