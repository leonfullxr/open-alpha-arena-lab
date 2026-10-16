import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const workerDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryDirectory = resolve(workerDirectory, '../..');
const assetRoot = resolve(repositoryDirectory, 'dist/web');
const configPath = resolve(workerDirectory, 'wrangler.jsonc');
const wranglerPath = resolve(workerDirectory, 'node_modules/wrangler/bin/wrangler.js');

await Promise.all([
  readFile(resolve(assetRoot, 'index.html')),
  readFile(resolve(assetRoot, 'admin/index.html')),
  readFile(configPath),
  readFile(wranglerPath),
]);

const portServer = createServer();
await new Promise((resolveListen, reject) => {
  portServer.once('error', reject);
  portServer.listen(0, '127.0.0.1', resolveListen);
});
const address = portServer.address();
if (address === null || typeof address === 'string') throw new Error('Could not select a local port');
const port = address.port;
await new Promise((resolveClose, reject) => portServer.close((error) => error ? reject(error) : resolveClose()));

const persistence = await mkdtemp(resolve(tmpdir(), 'arena-worker-routing-'));
const child = spawn(process.execPath, [
  wranglerPath,
  'dev',
  '--local',
  '--config', configPath,
  '--env', 'landing',
  '--ip', '127.0.0.1',
  '--port', String(port),
  '--persist-to', persistence,
  '--log-level', 'error',
], {
  cwd: workerDirectory,
  env: { ...process.env, NO_COLOR: '1' },
  stdio: ['ignore', 'pipe', 'pipe'],
});

let logs = '';
child.stdout.setEncoding('utf8').on('data', (chunk) => { logs += chunk; });
child.stderr.setEncoding('utf8').on('data', (chunk) => { logs += chunk; });
const origin = `http://127.0.0.1:${port}`;

async function waitForWorker() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Wrangler exited before serving requests.\n${logs}`);
    try {
      return await fetch(`${origin}/`, { signal: AbortSignal.timeout(1_000), redirect: 'manual' });
    } catch {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
    }
  }
  throw new Error(`Timed out waiting for Wrangler.\n${logs}`);
}

async function request(pathname) {
  return fetch(`${origin}${pathname}`, { redirect: 'manual', signal: AbortSignal.timeout(5_000) });
}

try {
  const root = await waitForWorker();
  assert.equal(root.status, 200, 'root document should be served by the asset binding');
  assert.equal(root.headers.get('location'), null, 'root document should not redirect');
  assert.match(root.headers.get('content-type') ?? '', /text\/html/i);

  for (const path of ['/simulation', '/simulation/competition/c1']) {
    const response = await request(path);
    assert.equal(response.status, 200, `${path} should directly serve the landing HTML`);
    assert.equal(response.headers.get('location'), null, `${path} should not be canonicalized elsewhere`);
    assert.match(response.headers.get('content-type') ?? '', /text\/html/i);
  }

  for (const path of ['/admin', '/admin/', '/admin/competitions', '/api/v1/admin/status']) {
    const response = await request(path);
    assert.equal(response.status, 403, `${path} should remain behind Access`);
  }

  const unknownApi = await request('/api/v1/public/private');
  assert.equal(unknownApi.status, 404, 'unlisted public APIs should remain hidden');
  const unconfiguredApi = await request('/api/v1/public/status');
  assert.equal(unconfiguredApi.status, 503, 'public APIs should fail closed without the rate-limit binding');
  assert.deepEqual(await unconfiguredApi.json(), {
    error: 'rate_limit_unavailable',
    detail: 'The research data service is not connected yet.',
    retryable: false,
  });

  console.log(`Wrangler asset-runtime routing checks passed on ${origin}.`);
} finally {
  child.kill('SIGTERM');
  await new Promise((resolveExit) => {
    if (child.exitCode !== null) resolveExit();
    else {
      child.once('exit', resolveExit);
      setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGKILL');
        resolveExit();
      }, 5_000).unref();
    }
  });
  await rm(persistence, { recursive: true, force: true });
}
