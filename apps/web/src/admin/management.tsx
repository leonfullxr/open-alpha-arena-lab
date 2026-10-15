import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { addPrompt, addProvider, createCompetition, getPrompts, getProviders, validateProvider, type CompetitionInput, type ProviderProfileInput } from './api';

type AgentDraft = { name: string; provider_profile_id: string; prompt_version_id: string };

export function AdminManagement(): React.JSX.Element {
  const queryClient = useQueryClient();
  const providers = useQuery({ queryKey: ['admin-providers'], queryFn: getProviders });
  const prompts = useQuery({ queryKey: ['admin-prompts'], queryFn: getPrompts });
  const providerMutation = useMutation({ mutationFn: addProvider, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-providers'] }) });
  const promptMutation = useMutation({ mutationFn: addPrompt, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-prompts'] }) });
  const createMutation = useMutation({ mutationFn: createCompetition, onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-status'] }) });
  const validateMutation = useMutation({ mutationFn: validateProvider });
  const [agents, setAgents] = useState<AgentDraft[]>([{ name: 'Account 1', provider_profile_id: '', prompt_version_id: '' }]);

  function submitProvider(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    providerMutation.mutate({
      name: text(values, 'name'), version: number(values, 'version'), adapter: text(values, 'adapter'), model: text(values, 'model'),
      api_key_env: text(values, 'api_key_env'), input_cost_per_million: text(values, 'input_cost_per_million'),
      output_cost_per_million: text(values, 'output_cost_per_million'), max_cost_per_request_usd: text(values, 'max_cost_per_request_usd'),
      max_input_body_bytes: number(values, 'max_input_body_bytes'), max_output_tokens: number(values, 'max_output_tokens'), temperature: text(values, 'temperature'),
    } satisfies ProviderProfileInput);
  }

  function submitPrompt(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    promptMutation.mutate({ name: text(values, 'name'), version: number(values, 'version'), template: text(values, 'template') });
  }

  function submitCompetition(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    createMutation.mutate({
      name: text(values, 'name'), profile: text(values, 'profile'), initial_balance: text(values, 'initial_balance'),
      inference_budget_usd: text(values, 'inference_budget_usd'), agents,
    } satisfies CompetitionInput);
  }

  return <section className="admin-management">
    <div className="section-title"><div><h2>Provider profiles</h2><p>Store configuration and an environment variable reference. Provider keys are not entered or read here.</p></div><span>{providers.data?.length ?? '—'} profiles</span></div>
    <QueryError error={providers.error} retry={() => void providers.refetch()} />
    <div className="admin-record-list">{providers.data?.map((provider) => <article className="admin-record" key={provider.id}>
      <div><strong>{provider.name} · v{provider.version}</strong><small>{provider.adapter} / {provider.model} · {provider.active ? 'active' : 'inactive'}</small></div>
      <div><small>Key reference</small><code>{provider.api_key_env}</code></div>
      <div><small>Settings SHA-256</small><code>{provider.settings_sha256}</code></div>
      <button onClick={() => validateMutation.mutate(provider.id)} disabled={validateMutation.isPending}>Check configuration</button>
      <p className="admin-help">Checks whether the configured environment variable is present. It does not contact the provider or verify the credential.</p>
      {validateMutation.error && validateMutation.variables === provider.id && <p className="form-error" role="alert">{validateMutation.error.message}</p>}
      {validateMutation.data && validateMutation.variables === provider.id && <p role="status">{validateMutation.data.status}: {validateMutation.data.credential_env} · provider network call: {validateMutation.data.network_call}</p>}
    </article>)}</div>
    <form className="admin-editor" onSubmit={submitProvider}>
      <h3>Add provider profile</h3>
      <div className="admin-form-grid">
        <Field label="Name" name="name" defaultValue="OpenAI paper" required />
        <Field label="Version" name="version" type="number" min="1" defaultValue="1" required />
        <label>Adapter<select name="adapter" defaultValue="openai_chat"><option value="openai_chat">OpenAI chat</option><option value="openai_responses">OpenAI responses</option><option value="opencode_go">OpenCode Go</option></select></label>
        <Field label="Model identifier" name="model" defaultValue="gpt-4.1-mini" required />
        <Field label="API key environment variable" name="api_key_env" defaultValue="OPENAI_API_KEY" pattern="[A-Z][A-Z0-9_]{0,79}" required />
        <Field label="Input cost / million" name="input_cost_per_million" defaultValue="1" required />
        <Field label="Output cost / million" name="output_cost_per_million" defaultValue="5" required />
        <Field label="Request cost ceiling (USD)" name="max_cost_per_request_usd" defaultValue="1" required />
        <Field label="Maximum input body bytes" name="max_input_body_bytes" type="number" min="1" max="250000" defaultValue="250000" required />
        <Field label="Maximum output tokens" name="max_output_tokens" type="number" min="1" max="2000" defaultValue="512" required />
        <Field label="Temperature" name="temperature" defaultValue="0" required />
      </div>
      {providerMutation.error && <p className="form-error" role="alert">{providerMutation.error.message}</p>}
      {providerMutation.data && <p className="admin-feedback" role="status">Added {providerMutation.data.name} with settings SHA-256 {providerMutation.data.settings_sha256}.</p>}
      <button type="submit" disabled={providerMutation.isPending}>{providerMutation.isPending ? 'Saving…' : 'Add provider profile'}</button>
    </form>

    <div className="section-title"><div><h2>Prompt versions</h2><p>Prompt templates are immutable once added and identified by their content hash.</p></div><span>{prompts.data?.length ?? '—'} versions</span></div>
    <QueryError error={prompts.error} retry={() => void prompts.refetch()} />
    <div className="admin-record-list">{prompts.data?.map((prompt) => <article className="admin-record" key={prompt.id}><div><strong>{prompt.name} · v{prompt.version}</strong><small>{prompt.id}</small></div><code>SHA-256 {prompt.sha256}</code></article>)}</div>
    <form className="admin-editor" onSubmit={submitPrompt}>
      <h3>Add prompt version</h3>
      <div className="admin-form-grid"><Field label="Prompt name" name="name" required /><Field label="Version" name="version" type="number" min="1" defaultValue="1" required /></div>
      <label>Exact prompt template<textarea name="template" rows={8} maxLength={100000} required /></label>
      <p className="admin-help">The text sent here is stored as a new version. Provider credentials are never included.</p>
      {promptMutation.error && <p className="form-error" role="alert">{promptMutation.error.message}</p>}
      {promptMutation.data && <p className="admin-feedback" role="status">Added {promptMutation.data.name} v{promptMutation.data.version}: SHA-256 {promptMutation.data.sha256}.</p>}
      <button type="submit" disabled={promptMutation.isPending}>{promptMutation.isPending ? 'Saving…' : 'Add prompt version'}</button>
    </form>

    <div className="section-title"><div><h2>Create a draft competition</h2><p>Creation freezes the profile, initial capital, inference budget, provider profiles, and prompt versions as a draft.</p></div></div>
    {providers.isLoading || prompts.isLoading ? <p className="admin-help" role="status">Loading available providers and prompts…</p> : <form className="admin-editor" onSubmit={submitCompetition}>
      <div className="admin-form-grid"><Field label="Competition name" name="name" required /><label>Profile<select name="profile" defaultValue="alpha_2025_baseline"><option value="alpha_2025_baseline">alpha_2025_baseline</option><option value="research_extended">research_extended</option></select></label><Field label="Initial account capital (USD)" name="initial_balance" defaultValue="10000" required /><Field label="Total inference budget (USD)" name="inference_budget_usd" defaultValue="10" required /></div>
      <div className="admin-agent-builder"><h3>Model accounts ({agents.length} of 6)</h3>{agents.map((agent, index) => <fieldset key={index}><legend>Account {index + 1}</legend><Field label="Account name" name={`agent-name-${index}`} value={agent.name} onChange={(value) => updateAgent(index, { name: value })} required /><label>Provider profile<select value={agent.provider_profile_id} onChange={(event) => updateAgent(index, { provider_profile_id: event.target.value })} required><option value="">Select profile</option>{providers.data?.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version} · {item.model}</option>)}</select></label><label>Prompt version<select value={agent.prompt_version_id} onChange={(event) => updateAgent(index, { prompt_version_id: event.target.value })} required><option value="">Select prompt</option>{prompts.data?.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></label>{agents.length > 1 && <button type="button" onClick={() => setAgents((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove account</button>}</fieldset>)}</div>
      {agents.length < 6 && <button type="button" onClick={() => setAgents((current) => [...current, { name: `Account ${current.length + 1}`, provider_profile_id: '', prompt_version_id: '' }])}>Add model account</button>}
      {createMutation.error && <p className="form-error" role="alert">{createMutation.error.message}</p>}
      {createMutation.data && <p className="admin-feedback" role="status">Created draft {createMutation.data.name} ({createMutation.data.id}) with rules SHA-256 {createMutation.data.rules_sha256}.</p>}
      <button type="submit" disabled={createMutation.isPending || !providers.data?.length || !prompts.data?.length}>{createMutation.isPending ? 'Creating…' : 'Create draft competition'}</button>
    </form>}
  </section>;

  function updateAgent(index: number, update: Partial<AgentDraft>): void {
    setAgents((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...update } : item));
  }
}

function Field({ label, name, type = 'text', defaultValue, value, onChange, ...attributes }: {
  label: string;
  name: string;
  type?: string;
  defaultValue?: string;
  value?: string;
  onChange?: (value: string) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'name' | 'type' | 'value' | 'defaultValue' | 'onChange'>): React.JSX.Element {
  return <label>{label}<input name={name} type={type} defaultValue={defaultValue} value={value} onChange={onChange ? (event) => onChange(event.target.value) : undefined} {...attributes} /></label>;
}

function QueryError({ error, retry }: { error: Error | null; retry: () => void }): React.JSX.Element | null {
  return error ? <p className="form-error" role="alert">{error.message} <button onClick={retry}>Retry</button></p> : null;
}

function text(values: FormData, key: string): string { return String(values.get(key) ?? '').trim(); }
function number(values: FormData, key: string): number { return Number(values.get(key)); }
