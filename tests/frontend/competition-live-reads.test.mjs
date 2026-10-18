import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { resolve } from 'node:path';
import React from 'react';
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

const vite = await createServer({
  configFile: 'vite.config.ts',
  server: { middlewareMode: true, hmr: false },
  resolve: { alias: [{ find: 'react-router-dom', replacement: resolve('node_modules/react-router-dom/dist/index.mjs') }] },
  optimizeDeps: { noDiscovery: true, include: [] },
  appType: 'custom',
  logLevel: 'error',
});

const competitionId = 'live-read-test';
const modelId = 'model-1';
const apiCalls = new Map();
let competitionRevision = 0;
const { competitionReadOptions, startCompetitionLiveUpdates } = await vite.ssrLoadModule('/src/simulation/competition-reads.ts');
const { PublicApiError } = await vite.ssrLoadModule('/src/simulation/api.ts');
const { default: ModelPage } = await vite.ssrLoadModule('/src/simulation/model.tsx');
const { MemoryRouter, Route, Routes } = await vite.ssrLoadModule('react-router-dom');
const savedGlobals = new Map();

before(() => {
  for (const key of ['fetch', 'EventSource', 'window', 'document']) {
    savedGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  }
});

after(async () => {
  await vite.close();
  for (const [key, descriptor] of savedGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

const competition = (state) => ({ id: competitionId, state });

function fakeBrowser() {
  let nextTimer = 1;
  const timers = new Map();
  const eventSources = [];
  let visibilityState = 'visible';
  let clearedTimers = 0;

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      this.onopen = null;
      this.onmessage = null;
      this.onerror = null;
      eventSources.push(this);
    }

    close() {
      this.closed = true;
    }
  }

  Object.defineProperty(globalThis, 'EventSource', { configurable: true, writable: true, value: FakeEventSource });
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    writable: true,
    value: {
      setInterval(callback, delay) {
        const id = nextTimer++;
        timers.set(id, { callback, delay });
        return id;
      },
      clearInterval(id) {
        if (timers.delete(id)) clearedTimers++;
      },
    },
  });
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    writable: true,
    value: {},
  });
  Object.defineProperty(globalThis.document, 'visibilityState', {
    configurable: true,
    get: () => visibilityState,
  });

  return {
    eventSources,
    timers,
    get clearedTimers() { return clearedTimers; },
    setVisibility(value) { visibilityState = value; },
    tick(delay) {
      for (const timer of [...timers.values()]) {
        if (timer.delay === delay) timer.callback();
      }
    },
  };
}

function mockPublicApi() {
  apiCalls.clear();
  competitionRevision = 0;
  return { calls: apiCalls };
}

async function observe(queryClient, options, calls) {
  const observer = new QueryObserver(queryClient, {
    ...options,
    queryFn: async ({ queryKey }) => {
      const key = JSON.stringify(queryKey);
      const count = (calls.get(key) ?? 0) + 1;
      calls.set(key, count);
      if (queryKey[0] === 'competition' && queryKey.length === 2) {
        return { id: competitionId, state: 'RUNNING', revision: competitionRevision++ };
      }
      if (queryKey[0] === 'competition' && queryKey[2] === 'leaderboard') return [];
      if (queryKey[0] === 'competition' && queryKey[2] === 'chart') return { items: [], total_raw: 0, sampled: false };
      if (queryKey[0] === 'competition' && ['trades', 'decisions', 'positions', 'funding'].includes(queryKey[2])) return { items: [], total: 0 };
      if (queryKey[0] === 'competition' && queryKey[2] === 'rules') return { sha256: 'rules-hash', bytes_base64: null };
      if (queryKey[0] === 'competition' && queryKey[2] === 'metrics') return { agents: [], benchmark: null };
      if (queryKey[0] === 'status') return { state: 'RUNNING', demo_label: 'Mock replay' };
      if (queryKey[0] === 'ticker') return [];
      if (queryKey[0] === 'model') return { id: modelId, competition_id: competitionId };
      return undefined;
    },
    staleTime: Infinity,
    retry: false,
  });
  const unsubscribe = observer.subscribe(() => {});
  await observer.refetch();
  assert.equal(observer.getCurrentResult().isError, false, `initial query failed: ${observer.getCurrentResult().error}`);
  return { observer, unsubscribe };
}

async function observeFailure(queryClient, options, error, calls) {
  const observer = new QueryObserver(queryClient, {
    ...options,
    queryFn: async () => {
      calls.set(JSON.stringify(options.queryKey), (calls.get(JSON.stringify(options.queryKey)) ?? 0) + 1);
      throw error;
    },
    retry: false,
  });
  const unsubscribe = observer.subscribe(() => {});
  await observer.refetch().catch(() => undefined);
  assert.equal(observer.getCurrentResult().isError, true);
  return { observer, unsubscribe };
}

async function settleQueryWork() {
  for (let count = 0; count < 8; count++) await new Promise((resolve) => setImmediate(resolve));
}

test('read options share the competition keys used by live invalidation', () => {
  const history = { limit: 20, offset: 0, agent_id: modelId, symbol: 'BTC' };
  const prefix = ['competition', competitionId];
  const underCompetition = [
    competitionReadOptions.competition(competitionId),
    competitionReadOptions.liveCompetition(competitionId),
    competitionReadOptions.leaderboard(competitionId),
    competitionReadOptions.chart(competitionId, 'ALL'),
    competitionReadOptions.metrics(competitionId),
    competitionReadOptions.trades(competitionId, history),
    competitionReadOptions.decisions(competitionId, history),
    competitionReadOptions.positions(competitionId, history),
    competitionReadOptions.funding(competitionId, history),
    competitionReadOptions.rules(competitionId),
  ];

  assert.deepEqual(competitionReadOptions.competition(competitionId).queryKey, competitionReadOptions.liveCompetition(competitionId).queryKey);
  assert.ok(underCompetition.every(({ queryKey }) => prefix.every((segment, index) => queryKey[index] === segment)));
  assert.deepEqual(competitionReadOptions.ticker(competitionId).queryKey, ['ticker', competitionId]);
  assert.deepEqual(competitionReadOptions.model(modelId).queryKey, ['model', modelId]);
});

test('live competition polling recovers missing detail and stops for permanent or finished results', () => {
  const queryClient = new QueryClient();
  const options = competitionReadOptions.liveCompetition(competitionId);
  const query = queryClient.getQueryCache().build(queryClient, options);

  query.setState({ ...query.state, error: new PublicApiError('Unavailable', 'server-error', 503, undefined, true) });
  assert.equal(options.refetchInterval(query), 30_000);

  query.setState({ ...query.state, error: new PublicApiError('Missing', 'not-found', 404, 'not_found', false) });
  assert.equal(options.refetchInterval(query), false);

  query.setState({ ...query.state, data: competition('FINISHED'), error: null });
  assert.equal(options.refetchInterval(query), false);

  query.setState({ ...query.state, data: competition('RUNNING') });
  assert.equal(options.refetchInterval(query), 5_000);
  queryClient.clear();
});

test('a cached selected-competition error does not hide a valid model from another competition', async () => {
  const missingCompetitionId = 'missing-selected-competition';
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  queryClient.setQueryData(competitionReadOptions.model(modelId).queryKey, {
    id: modelId,
    competition_id: 'other-competition',
    name: 'Cached Valid Model',
    provider: 'Local',
    model: 'fixture-v1',
    profile: 'alpha_2025_baseline',
    source_label: 'Offline fixture',
    status: 'ACTIVE',
    credential_reference_configured: false,
    settings_sha256: 'a'.repeat(64),
    prompt_sha256: 'b'.repeat(64),
    public_settings: {},
  });
  queryClient.setQueryData(competitionReadOptions.competitions().queryKey, [
    { id: 'other-competition', state: 'FINISHED', agents: [] },
  ]);
  await queryClient.fetchQuery({
    ...competitionReadOptions.competition(missingCompetitionId),
    queryFn: async () => { throw new Error('404 Competition not found'); },
    retry: false,
  }).catch(() => undefined);

  const html = renderToString(
    React.createElement(QueryClientProvider, { client: queryClient },
      React.createElement(MemoryRouter, { initialEntries: [`/simulation/${missingCompetitionId}/models/${modelId}`] },
        React.createElement(Routes, null,
          React.createElement(Route, {
            path: '/simulation/:competitionId/models/:agentId',
            element: React.createElement(ModelPage),
          }),
        ),
      ),
    ),
  );

  assert.match(html, /Cached Valid Model/);
  assert.match(html, /Model settings SHA-256/);
  assert.match(html, /This model is not listed in the selected competition/);
  queryClient.clear();
});

test('running stream messages and reconnect fallback refetch active cache observers once and clean up', async () => {
  const browser = fakeBrowser();
  const { calls } = mockPublicApi();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const competitionObserver = await observe(queryClient, competitionReadOptions.liveCompetition(competitionId), calls);
  const leaderboardObserver = await observe(queryClient, competitionReadOptions.leaderboard(competitionId), calls);
  const chartObserver = await observe(queryClient, competitionReadOptions.chart(competitionId, 'ALL'), calls);
  const history = { limit: 20, offset: 0, agent_id: modelId, symbol: 'BTC' };
  const tradesObserver = await observe(queryClient, competitionReadOptions.trades(competitionId, history), calls);
  const rulesObserver = await observe(queryClient, competitionReadOptions.rules(competitionId), calls);
  const statusObserver = await observe(queryClient, competitionReadOptions.status(), calls);
  const tickerObserver = await observe(queryClient, competitionReadOptions.ticker(competitionId), calls);
  const modelObserver = await observe(queryClient, competitionReadOptions.model(modelId), calls);
  const initialCalls = new Map(calls);
  const states = [];
  const cleanup = startCompetitionLiveUpdates(competition('RUNNING'), queryClient, (state) => states.push(state));
  const [source] = browser.eventSources;

  assert.equal(browser.eventSources.length, 1);
  assert.equal(source.url, `/api/v1/public/competitions/${competitionId}/stream`);
  source.onopen();
  assert.deepEqual(states, ['connected']);

  source.onerror();
  source.onerror();
  assert.deepEqual(states, ['connected', 'reconnecting', 'reconnecting']);
  assert.equal(browser.timers.size, 1, 'repeated errors must keep one fallback timer');
  assert.equal([...browser.timers.values()][0].delay, 5_000);

  browser.tick(5_000);
  await settleQueryWork();
  for (const path of [
    ['competition', competitionId],
    ['competition', competitionId, 'leaderboard'],
    ['competition', competitionId, 'chart', 'ALL'],
    ['competition', competitionId, 'trades', history],
    ['status'],
    ['ticker', competitionId],
    ['model', modelId],
  ]) {
    const key = JSON.stringify(path);
    assert.ok((calls.get(key) ?? 0) > (initialCalls.get(key) ?? 0), `${key} should refetch through its active query observer; calls: ${JSON.stringify([...calls])}`);
  }
  assert.equal(calls.get(JSON.stringify(competitionReadOptions.rules(competitionId).queryKey)), initialCalls.get(JSON.stringify(competitionReadOptions.rules(competitionId).queryKey)), 'immutable rule evidence stays view-owned');
  assert.equal(competitionObserver.observer.getCurrentResult().data.revision, 1);

  source.onopen();
  assert.equal(browser.timers.size, 0, 'reconnect should stop fallback polling');
  source.onmessage({ data: '{}' });
  await settleQueryWork();
  assert.equal(competitionObserver.observer.getCurrentResult().data.revision, 2);

  cleanup();
  assert.equal(source.closed, true);
  assert.equal(browser.timers.size, 0);
  assert.equal(browser.clearedTimers, 1);
  assert.equal(states.at(-1), 'paused');

  for (const item of [competitionObserver, leaderboardObserver, chartObserver, tradesObserver, rulesObserver, statusObserver, tickerObserver, modelObserver]) item.unsubscribe();
  queryClient.clear();
});

test('live refresh respects permanent errors and Retry-After cooldowns', async () => {
  const browser = fakeBrowser();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const calls = new Map();
  const missing = await observeFailure(queryClient, competitionReadOptions.leaderboard(competitionId), new PublicApiError('Missing', 'not-found', 404, 'not_found', false), calls);
  const rateLimited = await observeFailure(queryClient, competitionReadOptions.metrics(competitionId), new PublicApiError('Wait', 'rate-limit', 429, 'rate_limited', true, 120_000), calls);
  const initialCalls = new Map(calls);
  const cleanup = startCompetitionLiveUpdates(competition('RUNNING'), queryClient, () => {});
  browser.eventSources[0].onmessage({ data: '{}' });
  await settleQueryWork();

  for (const options of [competitionReadOptions.leaderboard(competitionId), competitionReadOptions.metrics(competitionId)]) {
    assert.equal(calls.get(JSON.stringify(options.queryKey)), initialCalls.get(JSON.stringify(options.queryKey)));
  }

  cleanup();
  missing.unsubscribe();
  rateLimited.unsubscribe();
  queryClient.clear();
});

test('paused runs refresh only while visible and finished runs allocate no live resources', async () => {
  const browser = fakeBrowser();
  const { calls } = mockPublicApi();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const competitionObserver = await observe(queryClient, competitionReadOptions.competition(competitionId), calls);
  const key = JSON.stringify(['competition', competitionId]);
  const initialCalls = calls.get(key);
  const states = [];
  const cleanupPaused = startCompetitionLiveUpdates(competition('PAUSED'), queryClient, (state) => states.push(state));

  assert.equal(browser.eventSources.length, 0);
  assert.equal(browser.timers.size, 1);
  browser.setVisibility('hidden');
  browser.tick(5_000);
  await settleQueryWork();
  assert.equal(calls.get(key), initialCalls);

  browser.setVisibility('visible');
  browser.tick(5_000);
  await settleQueryWork();
  assert.ok(calls.get(key) > initialCalls, `visible pause should refetch; calls: ${JSON.stringify([...calls])}`);
  cleanupPaused();
  assert.equal(browser.timers.size, 0);

  const finishedCleanup = startCompetitionLiveUpdates(competition('FINISHED'), queryClient, (state) => states.push(state));
  assert.equal(states.at(-1), 'paused');
  assert.equal(browser.eventSources.length, 0);
  assert.equal(browser.timers.size, 0);
  finishedCleanup();
  assert.equal(browser.timers.size, 0);

  competitionObserver.unsubscribe();
  queryClient.clear();
});
