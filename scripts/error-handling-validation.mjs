#!/usr/bin/env node

import { createServer as createHttpServer } from 'node:http';
import { execFile } from 'node:child_process';
import { createServer as createNetServer } from 'node:net';
import react from '@vitejs/plugin-react';
import { createServer as createViteServer } from 'vite';
import path from 'node:path';
import process from 'node:process';
import { mkdir, writeFile } from 'node:fs/promises';
import { promisify } from 'node:util';

const root = process.cwd();
const session = process.env.CHROME_DEVTOOLS_AXI_SESSION ?? 'arena-error-validation-20261016';
const screenshotDir = process.env.ERROR_VALIDATION_SCREENSHOT_DIR ?? path.join(root, 'docs/screenshots');
const results = [];
const requestCounts = new Map();
const execFileAsync = promisify(execFile);
let mode = '503-transient';
let browserStarted = false;
let apiServer;
let webServer;

function record(name, passed, details = {}) {
  results.push({ name, passed, ...details });
  if (!passed) throw new Error(`Validation failed: ${name}`);
}

function response(res, status, body, contentType = 'application/json', headers = {}) {
  res.writeHead(status, { 'content-type': contentType, 'cache-control': 'no-store', ...headers });
  res.end(body);
}

async function findFreePort() {
  const server = createNetServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Could not reserve a TCP port for the browser server');
  const { port } = address;
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

function fixtureFor(pathname) {
  const route = pathname.replace(/^\/api\/v1\/public/, '') || '/';
  requestCounts.set(route, (requestCounts.get(route) ?? 0) + 1);

  if (mode === 'healthy') {
    if (route === '/status') return { status: 200, body: { demo_label: 'FIXTURE · EMPTY PUBLIC RECORD' } };
    if (route === '/competitions' || route === '/ticker') return { status: 200, body: [] };
    return { status: 200, body: {} };
  }
  if (mode === 'background-503' && route === '/ticker') return { status: 200, body: [] };
  if (mode === 'network') return { status: 0, body: null };
  if (mode === '502-html') return {
    status: 502,
    type: 'text/html; charset=utf-8',
    body: '<!doctype html><html><body><h1>Bad gateway</h1><pre>SECRET_INTERNAL_PROXY_STACK</pre></body></html>',
  };
  if (mode === '502-html-json-type') return {
    status: 502,
    type: 'application/json',
    body: '<!doctype html><html><body><pre>SECRET_MISLEADING_PROXY_STACK</pre></body></html>',
  };
  if (mode === '500-empty') return { status: 500, body: '' };
  if (mode === '500-malformed') return { status: 500, body: '{broken SECRET_MALFORMED_STACK' };
  if (mode === 'malformed') return { status: 200, type: 'application/json', body: '{"broken":' };
  if (mode === '503-not-configured') return {
    status: 503,
    body: { error: 'origin_unavailable', detail: 'The research data service is not connected yet.', retryable: false },
  };
  if (mode === '503-transient' || mode === 'background-503') return {
    status: 503,
    body: { error: 'service_unavailable', code: 'service_unavailable', detail: 'SECRET_INTERNAL_GATEWAY_DETAIL', retryable: true },
  };
  if (mode === '429') return {
    status: 429,
    headers: { 'retry-after': '1' },
    body: { error: 'rate_limited', code: 'rate_limited', detail: 'SECRET_INTERNAL_LIMIT_DETAIL', retryable: true },
  };
  if (mode === '404') return {
    status: 404,
    body: { error: 'not_found', code: 'not_found', detail: 'SECRET_INTERNAL_RECORD_DETAIL', retryable: false },
  };
  return {
    status: 500,
    body: { error: 'internal_error', code: 'internal_error', detail: 'SECRET_INTERNAL_EXCEPTION_STACK', retryable: true },
  };
}

async function axi(...args) {
  try {
    const { stdout } = await execFileAsync('chrome-devtools-axi', args, {
      cwd: root,
      env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
      encoding: 'utf8',
      timeout: 120_000,
    });
    return stdout;
  } catch (error) {
    const stdout = error instanceof Error ? error.stdout?.toString() : '';
    const stderr = error instanceof Error ? error.stderr?.toString() : '';
    throw new Error(`${error instanceof Error ? error.message : String(error)}${stdout ? `\nstdout: ${stdout}` : ''}${stderr ? `\nstderr: ${stderr}` : ''}`);
  }
}

async function evaluate(expression) {
  const output = await axi('eval', expression);
  if (/result was truncated|output truncated/i.test(output)) throw new Error('Browser evaluation was truncated');
  const line = output.split('\n').find((item) => item.startsWith('result: '));
  if (!line) throw new Error(`Browser evaluation returned no result: ${output}`);
  let value = JSON.parse(line.slice('result: '.length));
  for (let depth = 0; depth < 3 && typeof value === 'string'; depth += 1) {
    try { value = JSON.parse(value); } catch { break; }
  }
  return value;
}

async function waitFor(predicate, label, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    last = await evaluate(`() => ({
      body: document.body.innerText,
      notice: document.querySelector('.system-notice')?.innerText ?? '',
      noticeCount: document.querySelectorAll('.system-notice').length,
      staleCount: document.querySelectorAll('.query-stale').length,
      stale: [...document.querySelectorAll('.query-stale')].map((node) => node.innerText),
      retry: Boolean(document.querySelector('button[aria-label="Retry public data"]')),
      rowCount: [...document.querySelectorAll('table tbody tr')].reduce((sum, tableRow) => sum + 1, 0),
      title: document.title,
      route: location.pathname,
    })`);
    if (predicate(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(last)}`);
}

async function navigate(url) {
  await evaluate(`location.href = ${JSON.stringify(url)}`);
  await waitFor((state) => state.route === new URL(url).pathname, `route ${url}`, 10_000);
}

async function main() {
  apiServer = createHttpServer((req, res) => {
    const pathname = new URL(req.url ?? '/', 'http://fixture.local').pathname;
    const fixture = fixtureFor(pathname);
    if (fixture.status === 0) {
      req.socket.destroy();
      return;
    }
    const body = typeof fixture.body === 'string' ? fixture.body : JSON.stringify(fixture.body);
    response(res, fixture.status, body, fixture.type ?? 'application/json', fixture.headers);
  });
  await new Promise((resolve, reject) => {
    apiServer.once('error', reject);
    apiServer.listen(0, '127.0.0.1', resolve);
  });
  const apiAddress = apiServer.address();
  if (!apiAddress || typeof apiAddress === 'string') throw new Error('Fixture API did not bind to a TCP port');

  const webPort = await findFreePort();
  webServer = await createViteServer({
    configFile: false,
    root: path.join(root, 'apps/web'),
    plugins: [react()],
    clearScreen: false,
    server: {
      host: '127.0.0.1',
      port: webPort,
      strictPort: true,
      watch: null,
      proxy: { '/api/v1': { target: `http://127.0.0.1:${apiAddress.port}`, changeOrigin: true } },
    },
  });
  await webServer.listen();
  const webAddress = webServer.httpServer?.address();
  if (!webAddress || typeof webAddress === 'string') throw new Error('Vite did not bind to a TCP port');
  const origin = `http://127.0.0.1:${webAddress.port}`;

  browserStarted = true;
  await axi('open', `${origin}/`);
  await axi('resize', '1920', '1080');
  await navigate(`${origin}/simulation`);

  const scenarios = [
    ['500-json', '500', 'temporarily unavailable'],
    ['503-transient', '503-transient', 'temporarily unavailable'],
    ['503-not-configured', '503-not-configured', 'not connected yet'],
    ['502-html', '502-html', 'temporarily unavailable'],
    ['429-rate-limit', '429', 'receiving a lot of requests'],
    ['network-drop-through-vite-proxy', 'network', 'temporarily unavailable'],
    ['empty-500', '500-empty', 'temporarily unavailable'],
    ['malformed-json-500', '500-malformed', 'temporarily unavailable'],
    ['html-body-json-content-type-502', '502-html-json-type', 'temporarily unavailable'],
    ['malformed-json', 'malformed', 'unreadable response'],
  ];
  for (const [name, scenario, expectedText] of scenarios) {
    mode = scenario;
    await navigate(`${origin}/simulation`);
    const state = await waitFor((item) => item.notice.length > 0 && item.retry, `${name} notice`);
    const visibleError = `${state.notice}\n${state.body}`;
    record(name, state.noticeCount === 1
      && state.notice.toLowerCase().includes(expectedText.toLowerCase())
      && !/\b(?:500|502|503|429)\b|SECRET_INTERNAL|<html|stack/i.test(visibleError), {
      route: state.route,
      notice: state.notice,
      status_request_count: requestCounts.get('/status') ?? 0,
    });
    if (scenario === '429') {
      const countBeforeFocus = requestCounts.get('/status') ?? 0;
      await evaluate('document.dispatchEvent(new Event("visibilitychange"))');
      await new Promise((resolve) => setTimeout(resolve, 300));
      const countAfterFocus = requestCounts.get('/status') ?? 0;
      record('focus-within-retry-after-does-not-refetch-rate-limited-query', countAfterFocus === countBeforeFocus, {
        retry_after_seconds: 1,
        requests_before_focus: countBeforeFocus,
        requests_after_focus: countAfterFocus,
      });
    }
  }

  mode = '404';
  await navigate(`${origin}/simulation/unknown-public-record`);
  const scoped404 = await waitFor((item) => /could not be found/i.test(item.body), 'scoped 404 state');
  record('404-stays-in-record-scope-without-shell-banner', scoped404.noticeCount === 0
    && !scoped404.body.includes('SECRET_INTERNAL_RECORD_DETAIL'), {
    route: scoped404.route,
    notice_count: scoped404.noticeCount,
    body_excerpt: scoped404.body.slice(-800),
  });

  mode = '503-transient';
  for (const route of ['/simulation', '/simulation/fixture-run/leaderboard', '/simulation/fixture-run/models/fixture-agent']) {
    await navigate(`${origin}${route}`);
    const state = await waitFor((item) => item.notice.length > 0 && item.retry, `shell on ${route}`);
    const terminalShell = await evaluate(`() => ({header: Boolean(document.querySelector('.arena-head')), main: Boolean(document.querySelector('#arena-main')), context: Boolean(document.querySelector('.arena-context'))})`);
    record(`terminal-route-${route.split('/').at(-1) || 'directory'}`,
      state.noticeCount === 1 && terminalShell.header && terminalShell.main && terminalShell.context,
      { route, terminal_shell: terminalShell, notice: state.notice });
  }

  await axi('resize', '390', '844');
  const mobile = await waitFor((item) => item.notice.length > 0 && item.retry, 'mobile error notice');
  const mobileLayout = await evaluate(`() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, notice: document.querySelector('.system-notice').getBoundingClientRect().toJSON(), markWidth: document.querySelector('.arena-mark')?.getBoundingClientRect().width ?? null })`);
  record('mobile-terminal-shell-no-horizontal-overflow', mobileLayout.viewport === 390
    && mobileLayout.document === 390 && mobile.noticeCount === 1,
  { route: mobile.route, layout: mobileLayout });

  mode = '429';
  await navigate(`${origin}/simulation`);
  await waitFor((item) => item.notice.includes('receiving a lot of requests') && item.retry, 'rate-limit retry control');
  mode = 'healthy';
  const countBeforeRetry = requestCounts.get('/status') ?? 0;
  await evaluate(`() => { document.querySelector('button[aria-label="Retry public data"]').click(); return true; }`);
  const isHealthyEmptyCopy = (body) => /has not published a run yet|no published runs with model activity yet/i.test(body);
  const retried = await waitFor((item) => item.noticeCount === 0 && isHealthyEmptyCopy(item.body), 'manual recovery after retry');
  const countAfterRetry = requestCounts.get('/status') ?? 0;
  record('retry-requests-failed-data-again-and-recovers', countAfterRetry > countBeforeRetry
    && retried.rowCount === 0 && !/\$\s?\d|\bP&L\b/i.test(retried.body), {
    status_requests_before: countBeforeRetry,
    status_requests_after: countAfterRetry,
    remaining_table_rows: retried.rowCount,
    empty_record_message_visible: isHealthyEmptyCopy(retried.body),
  });

  const emptyStatusCalls = requestCounts.get('/status') ?? 0;
  mode = '503-not-configured';
  await navigate(`${origin}/simulation`);
  const persistent = await waitFor((item) => item.notice.includes('not connected yet') && item.retry, 'persistent configuration error');
  await new Promise((resolve) => setTimeout(resolve, 5_500));
  const emptyStatusCallsAfterWait = requestCounts.get('/status') ?? 0;
  record('missing-service-configuration-does-not-auto-retry', persistent.noticeCount === 1 && emptyStatusCallsAfterWait === emptyStatusCalls + 1, {
    notice: persistent.notice,
    status_requests: emptyStatusCallsAfterWait - emptyStatusCalls,
  });

  mode = 'healthy';
  await navigate(`${origin}/simulation`);
  await waitFor((item) => item.noticeCount === 0 && isHealthyEmptyCopy(item.body), 'healthy empty baseline');
  await new Promise((resolve) => setTimeout(resolve, 2_200));
  mode = 'background-503';
  await evaluate('document.dispatchEvent(new Event("visibilitychange"))');
  const stale = await waitFor((item) => item.notice.includes('last successful refresh'), 'stale cached data shown while refresh fails');
  mode = 'healthy';
  const competitionsBeforeFocus = requestCounts.get('/competitions') ?? 0;
  const statusBeforeFocus = requestCounts.get('/status') ?? 0;
  await evaluate('document.dispatchEvent(new Event("visibilitychange"))');
  await new Promise((resolve) => setTimeout(resolve, 1_200));
  const competitionsAfterFocus = requestCounts.get('/competitions') ?? 0;
  const statusAfterFocus = requestCounts.get('/status') ?? 0;
  record('focus-during-retry-cooldown-does-not-refetch', competitionsAfterFocus === competitionsBeforeFocus
    && statusAfterFocus === statusBeforeFocus && stale.noticeCount === 1, {
    competition_requests_before_recovery: competitionsBeforeFocus,
    competition_requests_after_recovery: competitionsAfterFocus,
    status_requests_before_recovery: statusBeforeFocus,
    status_requests_after_recovery: statusAfterFocus,
    stale_notice: stale.notice,
  });
  const failedRequestsBeforeManualRetry = {
    competitions: competitionsAfterFocus,
    status: statusAfterFocus,
  };
  await evaluate(`() => { document.querySelector('.system-notice button[aria-label="Retry public data"]')?.click(); return true; }`);
  const recovered = await waitFor((item) => item.noticeCount === 0 && isHealthyEmptyCopy(item.body), 'manual recovery after background outage');
  record('manual-retry-recovers-all-stale-query-data', (requestCounts.get('/competitions') ?? 0) > failedRequestsBeforeManualRetry.competitions
    && recovered.rowCount === 0, {
    competition_requests: requestCounts.get('/competitions') ?? 0,
    status_requests: requestCounts.get('/status') ?? 0,
    empty_state_visible: isHealthyEmptyCopy(recovered.body),
  });

  mode = '500';
  await navigate(`${origin}/simulation`);
  await waitFor((item) => item.notice.includes('temporarily unavailable'), 'final 500 state');
  await axi('resize', '1920', '1080');
  await axi('screenshot', path.join(screenshotDir, 'arena-api-error-500-desktop.png'));
  await axi('resize', '390', '844');
  await waitFor((item) => item.notice.includes('temporarily unavailable'), 'mobile 500 state');
  await axi('screenshot', path.join(screenshotDir, 'arena-api-error-500-mobile.png'));

  const evidence = { created_at: new Date().toISOString(), passed: true, origin, fixture_mode: 'local deterministic API; no financial rows', no_database_mutation: true, no_paid_provider_calls: true, checks: results };
  await mkdir(path.join(root, 'docs/evidence'), { recursive: true });
  await writeFile(path.join(root, 'docs/evidence/error-handling-validation-2026-10-16.json'), `${JSON.stringify(evidence, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
}

try {
  await main();
} catch (error) {
  const evidence = { created_at: new Date().toISOString(), passed: false, no_database_mutation: true, no_paid_provider_calls: true, checks: results, error: error instanceof Error ? error.message : String(error) };
  try {
    await mkdir(path.join(root, 'docs/evidence'), { recursive: true });
    await writeFile(path.join(root, 'docs/evidence/error-handling-validation-2026-10-16.json'), `${JSON.stringify(evidence, null, 2)}\n`);
  } catch { /* Preserve the validation failure if evidence cannot be written. */ }
  process.stderr.write(`${JSON.stringify(evidence, null, 2)}\n`);
  process.exitCode = 1;
} finally {
  if (browserStarted) {
    try { await axi('stop'); } catch { /* Leave unrelated sessions untouched. */ }
  }
  await Promise.allSettled([webServer?.close(), new Promise((resolve) => apiServer?.close(resolve))]);
}
