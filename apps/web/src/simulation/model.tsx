import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Activity, BriefcaseBusiness, MessageSquareText, ReceiptText } from 'lucide-react';
import { ActivityPanel } from './activity';
import { getCompetitionMetrics, getCompetitions, getEquityChart, getLeaderboard, getModel, type EquityRange } from './api';
import { EquityChart } from './equity-chart';
import { useCompetitionStream } from './stream';
import { money, PageHeading, QueryState, StatusBadge } from './ui';

const tabs = ['Overview', 'Fills', 'Positions', 'Decisions'] as const;
const tabIcons = [Activity, ReceiptText, BriefcaseBusiness, MessageSquareText];
type ModelTab = (typeof tabs)[number];

export default function ModelPage(): React.JSX.Element {
  const { competitionId = '', agentId = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightDecisionId = searchParams.get('decision') ?? undefined;
  const requestedRound = Number(searchParams.get('round'));
  const decisionRound = Number.isSafeInteger(requestedRound) && requestedRound > 0 ? requestedRound : undefined;
  const initialTab = tabs.find((tab) => tab.toLowerCase() === searchParams.get('tab')) ?? (searchParams.has('decision') ? 'Decisions' : 'Overview');
  const [tab, setTab] = useState<ModelTab>(initialTab);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [chartRange, setChartRange] = useState<EquityRange>('ALL');
  const modelQuery = useQuery({ queryKey: ['model', agentId], queryFn: () => getModel(agentId), enabled: Boolean(agentId) });
  const competitionsQuery = useQuery({ queryKey: ['competitions'], queryFn: getCompetitions });
  const model = modelQuery.data;
  const publicSettings = model ? Object.entries(model.public_settings).sort(([left], [right]) => left.localeCompare(right)) : [];
  const competition = competitionsQuery.data?.find((item) => item.id === competitionId && item.id === model?.competition_id);
  const enabled = Boolean(competition);
  const equity = useQuery({ queryKey: ['competition', competition?.id, 'chart', chartRange], queryFn: () => getEquityChart(competition!.id, chartRange), enabled });
  const leaderboard = useQuery({ queryKey: ['competition', competition?.id, 'leaderboard'], queryFn: () => getLeaderboard(competition!.id), enabled });
  const metrics = useQuery({ queryKey: ['competition', competition?.id, 'metrics'], queryFn: () => getCompetitionMetrics(competition!.id), enabled });
  const agent = competition?.agents.find((item) => item.id === agentId);
  const account = leaderboard.data?.find((row) => row.agent_id === agentId);
  const risk = metrics.data?.agents.find((row) => row.agent_id === agentId);
  useCompetitionStream(competition);

  useEffect(() => {
    const urlTab = tabs.find((item) => item.toLowerCase() === searchParams.get('tab'));
    setTab(urlTab ?? (searchParams.has('decision') ? 'Decisions' : 'Overview'));
  }, [searchParams]);

  function selectTab(next: ModelTab): void {
    setTab(next);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('tab', next.toLowerCase());
    setSearchParams(nextParams, { replace: true });
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    const nextIndex = event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0
          : event.key === 'End' ? tabs.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    selectTab(tabs[nextIndex]!);
    tabRefs.current[nextIndex]?.focus();
  }

  return <>
    <QueryState loading={modelQuery.isLoading || competitionsQuery.isLoading} error={modelQuery.error ?? competitionsQuery.error} retry={() => void (modelQuery.isError ? modelQuery.refetch() : competitionsQuery.refetch())}>
      {model && <>
        <PageHeading eyebrow="Model account / public detail" title={model.name} detail={`${model.provider} · ${model.model}`}>
          <StatusBadge state={model.status} />
        </PageHeading>
        <details className="model-record-details">
          <summary>Public record &amp; settings</summary>
          <div className="model-facts">
            <Fact label="Agent ID" value={model.id} />
            <Fact label="Competition" value={competition?.name ?? 'Not linked by the public API'} />
            <Fact label="Profile" value={competition?.profile ?? 'N/A'} />
            <Fact label="Source" value={model.source_label} />
            <Fact label="Credential reference configured" value={model.credential_reference_configured ? 'Yes' : 'No'} />
            <Fact label="Model settings SHA-256" value={model.settings_sha256} />
            <Fact label="Prompt version SHA-256" value={model.prompt_sha256} />
          </div>
          <section className="model-public-settings" aria-labelledby="public-settings-title"><h2 id="public-settings-title">Public model settings</h2>{publicSettings.length ? <dl>{publicSettings.map(([key, value]) => <div key={key}><dt>{settingLabel(key)}</dt><dd>{String(value)}</dd></div>)}</dl> : <p>No public setting values were returned.</p>}</section>
        </details>
        {!competition || !agent ? <div className="metric-availability">This model is not listed in the selected competition.</div> : <>
          <div className="model-tabs" role="tablist" aria-label="Model analysis">
            {tabs.map((item, index) => { const Icon = tabIcons[index]!; return <button key={item} ref={(element) => { tabRefs.current[index] = element; }} id={`model-tab-${item.toLowerCase()}`} type="button" role="tab" aria-selected={tab === item} aria-controls="model-tab-panel" tabIndex={tab === item ? 0 : -1} onKeyDown={(event) => handleTabKeyDown(event, index)} onClick={() => selectTab(item)}><Icon aria-hidden="true" size={15} />{item}</button>; })}
          </div>
          <section className="model-tab-panel" id="model-tab-panel" role="tabpanel" aria-labelledby={`model-tab-${tab.toLowerCase()}`}>
            {tab === 'Overview' && <>
              <section className="model-overview-metrics" aria-label="Model performance summary">
                <ModelMetric label="Portfolio equity" value={account ? money(account.equity) : leaderboard.isLoading ? 'Loading…' : 'N/A'} detail="Marked account value" />
                <ModelMetric label="Return" value={account ? signedPercent(account.roi_pct) : leaderboard.isLoading ? 'Loading…' : 'N/A'} detail="Versus starting capital" tone={account ? Number(account.roi_pct) >= 0 ? 'positive' : 'negative' : undefined} />
                <ModelMetric label="Max drawdown" value={risk?.max_drawdown_pct == null ? metrics.isLoading ? 'Loading…' : 'N/A' : `${Number(risk.max_drawdown_pct).toFixed(2)}%`} detail="Peak to trough" />
              </section>
              {(leaderboard.error || metrics.error) && <p className="metric-availability" role="status">Some performance values are unavailable: {(leaderboard.error ?? metrics.error)?.message}</p>}
              <QueryState loading={equity.isLoading} error={equity.error} retry={() => void equity.refetch()} empty={equity.data?.items.filter((row) => row.agent_id === model.id).length === 0 ? 'No account equity records are available.' : undefined}>
                {equity.data && <EquityChart agents={[agent]} rows={equity.data.items.filter((row) => row.agent_id === model.id)} initialBalance={competition.initial_balance} sampleCount={equity.data.total_raw} sampled={equity.data.sampled} range={chartRange} onRangeChange={setChartRange} />}
              </QueryState>
              <p className="model-return">Starting equity {money(competition.initial_balance)} · model status {model.status}</p>
            </>}
            {tab === 'Fills' && <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Live trades" />}
            {tab === 'Positions' && <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Positions" />}
            {tab === 'Decisions' && <ActivityPanel competitionId={competition.id} agentId={model.id} tab="Model chat" highlightDecisionId={highlightDecisionId} decisionRound={decisionRound} />}
          </section>
        </>}
      </>}
    </QueryState>
  </>;
}

function Fact({ label, value }: { label: string; value: string }): React.JSX.Element {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function ModelMetric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: 'positive' | 'negative' }): React.JSX.Element {
  return <div className="model-overview-metric"><span>{label}</span><strong className={tone ? `value-${tone}` : undefined}>{value}</strong><small>{detail}</small></div>;
}

function signedPercent(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%` : 'N/A';
}

function settingLabel(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}
