#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const api = new URL(
  process.env.SIMULATION_API_BASE_URL ?? 'http://127.0.0.1:8026/api/v1/public',
);
if (!api.pathname.endsWith('/')) api.pathname += '/';
const web = new URL(process.env.SIMULATION_BASE_URL ?? 'http://127.0.0.1:5186');
const session = process.env.CHROME_DEVTOOLS_AXI_SESSION ?? 'arena-sim-validation-20261016';
const evidencePath = path.join(
  root,
  'docs/evidence/simulation-browser-validation-2026-10-16.json',
);
const screenshotDir = path.join(root, 'docs/screenshots');
const apiOnly = process.argv.includes('--api-only');
const includeFixtures = process.argv.includes('--fixtures');
const functionalOnly = process.argv.includes('--functional-only');
const focusedReviewFixes = process.argv.includes('--focused-review-fixes');
const checks = [];
let browserSessionStarted = false;

function record(name, passed, details = {}) {
  checks.push({ name, passed, ...details });
  if (!passed) throw new Error(`Validation failed: ${name}`);
}

async function getJson(route, expectedStatus = 200) {
  const target = route.startsWith('/api/v1/public/')
    ? new URL(route, api.origin)
    : new URL(route.replace(/^\/+/, ''), api);
  const response = await fetch(target);
  if (response.status !== expectedStatus) {
    throw new Error(`${route}: expected HTTP ${expectedStatus}, got ${response.status}`);
  }
  return { response, body: expectedStatus === 200 ? await response.json() : null };
}

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function axi(...args) {
  return execFileSync('chrome-devtools-axi', args, {
    cwd: root,
    env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 120_000,
  });
}

function evaluate(expression) {
  const output = axi('eval', expression);
  if (/result was truncated|output truncated/i.test(output)) {
    throw new Error('AXI truncated a browser evaluation result; return a smaller value');
  }
  const line = output.split('\n').find((item) => item.startsWith('result: '));
  if (!line) throw new Error(`Browser evaluation did not return a result: ${output}`);
  let decoded = JSON.parse(line.slice('result: '.length));
  for (let depth = 0; depth < 3 && typeof decoded === 'string'; depth += 1) {
    try {
      decoded = JSON.parse(decoded);
    } catch {
      break;
    }
  }
  return decoded;
}

async function waitFor(expression, predicate, name, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    last = evaluate(expression);
    if (predicate(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Timed out waiting for ${name}: ${JSON.stringify(last)}`);
}

async function apiChecks() {
  const { body: competitions } = await getJson('/competitions');
  const baseline = competitions.find(
    (item) => item.source_label.startsWith('DEMO REPLAY') && item.profile === 'alpha_2025_baseline',
  );
  if (!baseline) throw new Error('No source-labeled DEMO REPLAY baseline competition is available');
  record('real-demo-baseline-discovered', true, {
    id: baseline.id,
    state: baseline.state,
    profile: baseline.profile,
    source_label: baseline.source_label,
    model_count: baseline.agents.length,
  });

  const [firstPage, secondPage, btcPage] = await Promise.all([
    getJson(`/competitions/${baseline.id}/decisions?limit=20&offset=0`),
    getJson(`/competitions/${baseline.id}/decisions?limit=20&offset=20`),
    getJson(`/competitions/${baseline.id}/decisions?limit=200&symbol=BTC`),
  ]).then((items) => items.map((item) => item.body));
  const allIds = [...firstPage.items, ...secondPage.items].map((item) => item.id);
  record('decision-pagination-and-count',
    firstPage.total > firstPage.items.length
      && secondPage.items.length > 0
      && new Set(allIds).size === allIds.length
      && allIds.length === firstPage.total,
    { total: firstPage.total, page_sizes: [firstPage.items.length, secondPage.items.length] },
  );
  record('symbol-filter-uses-real-proposals',
    btcPage.items.length > 0 && btcPage.items.every((item) =>
      item.proposals.some((proposal) => proposal.symbol === 'BTC')),
    { matching_decisions: btcPage.items.length },
  );

  const decision = firstPage.items[0];
  const { body: modelProfile } = await getJson(`/models/${baseline.agents[0].id}`);
  record('model-profile-is-same-run', modelProfile.competition_id === baseline.id, {
    model_id: modelProfile.id,
    model_name: modelProfile.name,
    competition_id: modelProfile.competition_id,
  });

  const { body: artifact } = await getJson(decision.artifact_url);
  const promptBytes = Buffer.from(artifact.prompt_bytes_base64, 'base64');
  const outputBytes = Buffer.from(artifact.output_bytes_base64, 'base64');
  let expectedUserPromptHash = null;
  try {
    const request = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(promptBytes));
    if (Array.isArray(request.messages) && request.messages.every((message) => message && typeof message.role === 'string')) {
      const userMessages = request.messages.filter((message) => message.role === 'user');
      const content = [];
      const representable = userMessages.length > 0 && userMessages.every((message) => {
        if (typeof message.content === 'string') {
          content.push(message.content);
          return true;
        }
        if (!Array.isArray(message.content) || !message.content.length || !message.content.every((part) => part && part.type === 'text' && typeof part.text === 'string')) return false;
        content.push(...message.content.map((part) => part.text));
        return true;
      });
      if (representable) expectedUserPromptHash = sha256(Buffer.from(content.join('\n'), 'utf8'));
    }
  } catch {
    expectedUserPromptHash = null;
  }
  const promptHash = sha256(promptBytes);
  const outputHash = sha256(outputBytes);
  record('artifact-download-hashes-match',
    artifact.prompt_sha256 === decision.prompt_sha256
      && artifact.output_sha256 === decision.output_sha256
      && promptHash === decision.prompt_sha256
      && outputHash === decision.output_sha256,
    {
      decision_id: decision.id,
      prompt_sha256: promptHash,
      output_sha256: outputHash,
      download_bytes: { prompt: promptBytes.length, output: outputBytes.length },
    },
  );

  const chartRanges = {};
  for (const range of ['ALL', '72H', '24H']) {
    const { body } = await getJson(`/competitions/${baseline.id}/chart?range=${range}&points=400`);
    chartRanges[range] = { count: body.items.length, raw: body.total_raw, sampled: body.sampled };
    record(`chart-range-${range.toLowerCase()}`, body.items.length > 0 && body.total_raw > 0, chartRanges[range]);
  }

  const { body: trades } = await getJson(`/competitions/${baseline.id}/trades?limit=200`);
  const { body: leaderboard } = await getJson(`/competitions/${baseline.id}/leaderboard`);
  const { body: exported } = await getJson(`/competitions/${baseline.id}/export?limit=200`);
  record('trades-and-leaderboard-available',
    trades.items.length > 0 && leaderboard.length === baseline.agents.length,
    { trades: trades.items.length, leaderboard_rows: leaderboard.length },
  );
  record('competition-export-download-counts',
    exported.exported_decisions === firstPage.total
      && exported.decisions.length === firstPage.total
      && exported.exported_trades === trades.items.length,
    {
      exported_decisions: exported.exported_decisions,
      exported_trades: exported.exported_trades,
      truncated: exported.truncated,
    },
  );

  const fixtures = [];
  if (includeFixtures) {
    const fixtureItems = competitions.filter((item) => item.source_label.startsWith('TEST FIXTURE'));
    const byName = new Map(fixtureItems.map((item) => [item.name, item]));
    const expectedFixtures = [
      ['SIMULATION UI VALIDATION · extended empty evidence', 'research_extended', 'DRAFT'],
      ['SIMULATION UI VALIDATION · running stream state', 'alpha_2025_baseline', 'RUNNING'],
      ['SIMULATION UI VALIDATION · paused lifecycle state', 'alpha_2025_baseline', 'PAUSED'],
      ['SIMULATION UI VALIDATION · rules evidence unavailable', 'alpha_2025_baseline', 'DRAFT'],
    ];
    for (const [name, profile, state] of expectedFixtures) {
      const item = byName.get(name);
      if (!item || item.profile !== profile || item.state !== state) {
        throw new Error(`Missing or incorrect isolated UI fixture: ${name}`);
      }
      const [decisions, chart, rulesResponse] = await Promise.all([
        getJson(`/competitions/${item.id}/decisions?limit=200`),
        getJson(`/competitions/${item.id}/chart?range=ALL&points=400`),
        getJson(`/competitions/${item.id}/rules`, name.endsWith('rules evidence unavailable') ? 503 : 200),
      ]);
      if (decisions.body.items.length !== 0 || chart.body.items.length !== 0) {
        throw new Error(`${name} should remain an empty-history lifecycle fixture`);
      }
      fixtures.push({
        id: item.id,
        name,
        profile,
        state,
        source_label: item.source_label,
        decisions: 0,
        chart_points: 0,
        rules_status: rulesResponse.response.status,
      });
    }
    record('isolated-empty-extended-and-lifecycle-fixtures', true, { fixtures });
  }

  const state = await getJson('/status');
  return {
    api_base: api.origin,
    web_base: web.origin,
    baseline: {
      id: baseline.id,
      name: baseline.name,
      source_label: baseline.source_label,
      state: baseline.state,
      profile: baseline.profile,
      decisions: firstPage.total,
      trades: trades.items.length,
      chart_ranges: chartRanges,
      model_ids: baseline.agents.map((agent) => agent.id),
      model_names: baseline.agents.map((agent) => agent.name),
      artifact: {
        decision_id: decision.id,
        prompt_sha256: promptHash,
        output_sha256: outputHash,
        user_prompt_sha256: expectedUserPromptHash,
      },
    },
    api_status: state.body,
    fixtures,
  };
}

async function browserChecks(apiEvidence) {
  await mkdir(screenshotDir, { recursive: true });
  const competitionId = apiEvidence.baseline.id;
  const modelId = apiEvidence.baseline.model_ids[0];
  const routes = [
    { route: '/simulation', name: 'run-index' },
    { route: `/simulation/${competitionId}`, name: 'competition' },
    { route: `/simulation/${competitionId}/leaderboard`, name: 'leaderboard' },
    { route: `/simulation/${competitionId}/models/${modelId}`, name: 'model-profile' },
  ];
  axi('open', new URL('/simulation', web).href);
  browserSessionStarted = true;
  await waitFor(
    `JSON.stringify({url:location.pathname,runLink:[...document.querySelectorAll("a[href]")].some(a=>a.href.includes(${JSON.stringify(competitionId)}))})`,
    (value) => value.url === '/simulation' && value.runLink,
    'real baseline run link on the simulation index',
  );

  const viewports = [
    [1920, 1080],
    [1363, 936],
    [1440, 900],
    [1024, 768],
    [768, 1024],
    [390, 844],
  ];
  if (!functionalOnly) {
    axi('resize', '1920', '1080');
    axi('screenshot', path.join('docs/screenshots', 'simulation-directory-1920x1080.png'));
  }

  const narrativeRoute = `/simulation?run=${encodeURIComponent(competitionId)}`;
  axi('open', new URL(narrativeRoute, web).href);
  await waitFor(
    `JSON.stringify({url:location.pathname,search:location.search,heading:document.querySelector("main h1")?.textContent.trim(),chatCards:document.querySelectorAll("aside .chat-card").length})`,
    (value) => value.url === '/simulation'
      && value.search.includes(competitionId)
      && value.heading === 'Open Alpha Arena Lab live research notes'
      && value.chatCards === 10,
    'selected-run narrative and model chat rail',
  );
  for (const [width, height] of viewports) {
    if (focusedReviewFixes) break;
    if (functionalOnly) break;
    axi('resize', String(width), String(height));
    const metrics = evaluate('JSON.stringify({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,context:(()=>{const r=document.querySelector(".arena-context")?.getBoundingClientRect();return r?{top:r.top,bottom:r.bottom,height:r.height}:null})(),tabs:(()=>{const r=document.querySelector(".arena-rail-tabs")?.getBoundingClientRect();return r?{top:r.top,bottom:r.bottom,height:r.height}:null})()})');
    record(`narrative-viewport-${width}x${height}-no-document-overflow`,
      metrics.documentWidth <= metrics.width + 1,
      metrics,
    );
    if (width >= 1024) record(`narrative-viewport-${width}x${height}-context-aligns-with-rail-tabs`, metrics.context && metrics.tabs && Math.abs(metrics.context.height - 30) <= 1 && Math.abs(metrics.context.top - metrics.tabs.top) <= 1 && Math.abs(metrics.context.bottom - metrics.tabs.bottom) <= 1, metrics);
    axi('screenshot', path.join('docs/screenshots', `simulation-narrative-${width}x${height}.png`));
  }

  const competitionRoute = `/simulation/${competitionId}`;
  axi('open', new URL(competitionRoute, web).href);
  await waitFor(
    `JSON.stringify({url:location.pathname,heading:document.querySelector("main h1")?.textContent.trim(),chartRows:document.querySelectorAll(".equity-line").length,accountRows:document.querySelectorAll(".accounts-panel tbody tr").length})`,
    (value) => value.url === competitionRoute
      && value.heading.toLowerCase() === apiEvidence.baseline.name.toLowerCase()
      && value.chartRows === apiEvidence.baseline.model_names.length
      && value.accountRows === apiEvidence.baseline.model_names.length,
    'selected baseline competition data',
  );
  const screenshots = [];
  for (const [width, height] of viewports) {
    if (functionalOnly || focusedReviewFixes) break;
    axi('resize', String(width), String(height));
    const metrics = evaluate('JSON.stringify({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,context:(()=>{const r=document.querySelector(".arena-context")?.getBoundingClientRect();return r?{top:r.top,bottom:r.bottom,height:r.height}:null})(),tabs:(()=>{const r=document.querySelector(".arena-rail-tabs")?.getBoundingClientRect();return r?{top:r.top,bottom:r.bottom,height:r.height}:null})()})');
    record(`competition-viewport-${width}x${height}-no-document-overflow`,
      metrics.documentWidth <= metrics.width + 1,
      metrics,
    );
    if (width >= 1024) record(`competition-viewport-${width}x${height}-context-aligns-with-rail-tabs`, metrics.context && metrics.tabs && Math.abs(metrics.context.height - 30) <= 1 && Math.abs(metrics.context.top - metrics.tabs.top) <= 1 && Math.abs(metrics.context.bottom - metrics.tabs.bottom) <= 1, metrics);
    const filename = `simulation-competition-${width}x${height}.png`;
    axi('screenshot', path.join('docs/screenshots', filename));
    screenshots.push(filename);
  }

  for (const item of routes) {
    if (focusedReviewFixes) break;
    const url = new URL(item.route, web).href;
    axi('resize', '1920', '1080');
    axi('open', url);
    const view = await waitFor(
      'JSON.stringify({url:location.pathname,hasMain:!!document.querySelector("main"),heading:document.querySelector("main h1")?.textContent.trim(),runLinks:[...document.querySelectorAll(".run-table a.run-name")].map(a=>a.href),chartRows:document.querySelectorAll(".equity-line").length,accountRows:document.querySelectorAll(".accounts-panel tbody tr").length,leaderboardRows:document.querySelectorAll(".leaderboard-table tbody tr").length,modelRows:document.querySelectorAll(".model-chart .equity-line").length})',
      (value) => value.url === item.route
        && value.hasMain
        && (item.name !== 'run-index' || value.heading === 'Open Alpha Arena Lab live research notes' && value.runLinks.some((href) => href.endsWith(competitionId)))
        && (item.name !== 'competition' || value.heading.toLowerCase() === apiEvidence.baseline.name.toLowerCase() && value.chartRows === apiEvidence.baseline.model_names.length)
        && (item.name !== 'leaderboard' || value.heading === 'LEADERBOARD' && value.leaderboardRows === apiEvidence.baseline.model_names.length)
        && (item.name !== 'model-profile' || value.heading === apiEvidence.baseline.model_names[0].toUpperCase() && value.modelRows === 1),
      `deep link ${item.name}`,
    );
    if (!functionalOnly && item.name !== 'run-index') {
      axi('screenshot', path.join('docs/screenshots', `simulation-${item.name}-1920x1080.png`));
    }
    record(`deep-link-${item.name}-renders`, true, {
      url: view.url,
      title: view.title,
      heading: view.heading,
    });
  }

  // Drive the public controls on the real baseline rather than inferring behavior from API responses.
  axi('open', new URL(narrativeRoute, web).href);
  await waitFor(
    'JSON.stringify({run:document.body.innerText.includes("40"),cards:document.querySelectorAll(".chat-card").length})',
    (value) => value.run && value.cards === 10,
    'first page of real decision cards',
  );
  const clickText = (selector, text) => evaluate(`JSON.stringify((()=>{const e=[...document.querySelectorAll(${JSON.stringify(selector)})].find(x=>x.textContent.trim()===${JSON.stringify(text)});if(!e)return false;e.click();return true})())`);
  const clickPrefix = (selector, prefix) => evaluate(`JSON.stringify((()=>{const e=[...document.querySelectorAll(${JSON.stringify(selector)})].find(x=>x.textContent.trim().startsWith(${JSON.stringify(prefix)}));if(!e)return false;e.click();return true})())`);
  const clickHref = (href) => evaluate(`JSON.stringify((()=>{const e=[...document.querySelectorAll('a[href]')].find(x=>x.getAttribute('href')===${JSON.stringify(href)} || x.href.endsWith(${JSON.stringify(href)}));if(!e)return false;e.click();return true})())`);
  const setInput = (selector, value) => evaluate(`JSON.stringify((()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return false;const setter=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e),'value').set;setter.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true})())`);
  const fillChatFilter = (value) => {
    const input = evaluate('JSON.stringify([...document.querySelectorAll("input")].find(e=>e.getAttribute("placeholder")?.toUpperCase()==="SYMBOL" || e.labels?.[0]?.textContent.trim()==="Symbol")?.outerHTML ?? null)');
    if (!input) throw new Error('Could not locate chat symbol filter');
    return setInput('aside input', value);
  };

  const modelSelect = evaluate('JSON.stringify([...document.querySelectorAll("select")].map(e=>({label:e.labels?.[0]?.textContent,options:[...e.options].map(o=>({text:o.text,value:o.value}))})))');
  if (!modelSelect.some((select) => select.options.some((option) => option.text.toUpperCase() === 'ATLAS'))) {
    throw new Error('Chat model filter does not expose Atlas');
  }
  const atlasModelId = apiEvidence.baseline.model_ids[0];
  record('chat-model-filter-can-select-atlas',
    setInput('aside select', atlasModelId),
    { selected_model_id: atlasModelId },
  );
  fillChatFilter('ZZZ_NOT_IN_API');
  record('unmatched-symbol-go-remains-visible', clickText('aside button', 'GO'));
  await waitFor(
    'JSON.stringify({empty:document.body.innerText.includes("No model decisions match this filter."),go:[...document.querySelectorAll("aside button")].some(b=>b.textContent.trim()==="GO"),model:document.querySelector("aside select")?.value})',
    (value) => value.empty && value.go && value.model === atlasModelId,
    'no-match symbol message while preserving model filter and GO',
  );
  record('unmatched-symbol-filter-is-recoverable', true, { symbol: 'ZZZ_NOT_IN_API', selected_model_id: atlasModelId });
  fillChatFilter('');
  clickText('aside button', 'GO');
  await waitFor('JSON.stringify({cards:document.querySelectorAll(".chat-card").length})', (value) => value.cards > 0, 'decision cards recover after clearing symbol');
  record('chat-filter-clears-and-recovers', true);
  setInput('aside select', '');
  await waitFor('JSON.stringify({model:document.querySelector("aside select")?.value,range:document.querySelector("aside")?.innerText.match(/\\d+\\s*–\\s*\\d+\\s*of\\s*\\d+/)?.[0]})', (value) => value.model === '' && value.range?.endsWith('of 40'), 'all-model decision count restored before pagination');

  const beforePage = evaluate('JSON.stringify([...document.querySelectorAll(".chat-card")].map(e=>e.textContent.slice(0,70)))');
  record('chat-next-page-enabled', clickText('aside button', 'NEXT'));
  const afterPage = await waitFor(
    'JSON.stringify({cards:document.querySelectorAll(".chat-card").length,range:document.querySelector("aside")?.innerText.match(/\\d+\\s*–\\s*\\d+\\s*of\\s*\\d+/)?.[0],first:document.querySelector(".chat-card")?.textContent.slice(0,70)})',
    (value) => value.cards === 10 && value.range?.startsWith('11') && value.first !== beforePage[0],
    'next decision page changes rows and count',
  );
  record('chat-pagination-next-changes-decision-page', true, { before: beforePage[0], after: afterPage.first, range: afterPage.range });
  clickText('aside button', 'PREV');
  await waitFor('JSON.stringify({range:document.querySelector("aside")?.innerText.match(/\\d+\\s*–\\s*\\d+\\s*of\\s*\\d+/)?.[0]})', (value) => value.range?.startsWith('1'), 'previous decision page');
  record('chat-pagination-previous-recovers-first-page', true);

  // Verify the visible download button produces the actual artifact bytes published by the API.
  const expanded = evaluate(`JSON.stringify((()=>{const e=document.querySelector('button[aria-label^="Expand public evidence"]');if(!e)return false;window.__evidenceExpander=e;e.focus();e.click();return true})())`);
  record('chat-evidence-expands', expanded);
  await waitFor('JSON.stringify({download:[...document.querySelectorAll(".artifact-block button")].some(b=>b.textContent.trim()==="DOWNLOAD")})', (value) => value.download, 'expanded artifact DOWNLOAD control');
  const promptPresentation = await evaluate(`(async()=>{const digest=async value=>{const bytes=new TextEncoder().encode(value);const result=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));return [...result].map(byte=>byte.toString(16).padStart(2,'0')).join('')};const disclosure=document.querySelector('.chat-user-prompt');const user=disclosure?.querySelector('pre');const request=document.querySelector('.artifact-block pre');return JSON.stringify({userHash:user?await digest(user.textContent):null,unavailable:disclosure?.innerText.includes('extraction is unavailable')??false,userDisclosure:disclosure?.querySelector('summary')?.textContent.trim()==='USER_PROMPT'&&disclosure.open,requestHash:request?await digest(request.textContent):null,label:[...document.querySelectorAll('.chat-detail summary')].some(e=>e.textContent.trim()==='PUBLIC REQUEST ARTIFACT · EXACT SENT BYTES')})})()`);
  record('user-prompt-is-separated-from-exact-public-request',
    apiEvidence.baseline.artifact.user_prompt_sha256 === null
      ? promptPresentation.unavailable && promptPresentation.userHash === null && promptPresentation.userDisclosure
      : promptPresentation.userHash === apiEvidence.baseline.artifact.user_prompt_sha256 && promptPresentation.userDisclosure,
    { user_prompt_extracted: !promptPresentation.unavailable, user_prompt_disclosure_open: promptPresentation.userDisclosure, request_label_present: promptPresentation.label },
  );
  record('exact-public-request-artifact-remains-readable',
    promptPresentation.requestHash === apiEvidence.baseline.artifact.prompt_sha256 && promptPresentation.label,
    { sha256: promptPresentation.requestHash, expected_sha256: apiEvidence.baseline.artifact.prompt_sha256 },
  );
  const focusOnExpand = evaluate('JSON.stringify(document.activeElement===window.__evidenceExpander)');
  evaluate('JSON.stringify((()=>{window.__evidenceExpander.click();return true})())');
  const collapsed = await waitFor('JSON.stringify({blocks:document.querySelectorAll(".artifact-block").length,focused:document.activeElement===window.__evidenceExpander})', (value) => value.blocks === 0 && value.focused, 'artifact collapses without losing focus');
  evaluate('JSON.stringify((()=>{window.__evidenceExpander.click();return true})())');
  await waitFor('JSON.stringify({download:[...document.querySelectorAll(".artifact-block button")].some(b=>b.textContent.trim()==="DOWNLOAD"),focused:document.activeElement===window.__evidenceExpander})', (value) => value.download && value.focused, 'artifact reopens with focus preserved');
  record('chat-expand-collapse-preserves-keyboard-focus', focusOnExpand && collapsed.focused, { focused_after_expand: focusOnExpand, focused_after_collapse: collapsed.focused });
  evaluate(`JSON.stringify((()=>{window.__downloadAudit={items:[],createObjectURL:URL.createObjectURL.bind(URL),anchorClick:HTMLAnchorElement.prototype.click};URL.createObjectURL=(blob)=>{const href=window.__downloadAudit.createObjectURL(blob);const item={href,size:blob.size};item.hashPromise=blob.arrayBuffer().then(async buffer=>{item.byteLength=buffer.byteLength;const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',buffer));item.sha256=[...digest].map(byte=>byte.toString(16).padStart(2,'0')).join('')});window.__downloadAudit.items.push(item);return href};HTMLAnchorElement.prototype.click=function(){const item=window.__downloadAudit.items.find(i=>i.href===this.href);if(item)item.filename=this.download};return true})())`);
  clickText('.artifact-block button', 'DOWNLOAD');
  const download = await waitFor(
    'JSON.stringify((()=>{const i=window.__downloadAudit?.items?.[0];return i?{filename:i.filename,size:i.size,byteLength:i.byteLength,sha256:i.sha256,hashReady:typeof i.sha256==="string"}:null})())',
    (value) => value?.hashReady,
    'button-triggered artifact Blob',
  );
  const actualDownloadHash = download.sha256;
  record('visible-artifact-download-matches-api-hash',
    actualDownloadHash === apiEvidence.baseline.artifact.prompt_sha256
      && download.size > 0 && download.byteLength === download.size
      && typeof download.filename === 'string',
    { filename: download.filename, size: download.size, captured_byte_length: download.byteLength, sha256: actualDownloadHash, expected_sha256: apiEvidence.baseline.artifact.prompt_sha256 },
  );
  evaluate('JSON.stringify((()=>{if(window.__downloadAudit){URL.createObjectURL=window.__downloadAudit.createObjectURL;HTMLAnchorElement.prototype.click=window.__downloadAudit.anchorClick;delete window.__downloadAudit}return true})())');

  const multimodalSetup = evaluate(`JSON.stringify((()=>{const card=document.querySelectorAll('.chat-card')[1];const button=card?.querySelector('button[aria-label^="Expand public evidence"]');if(!button)return false;const decisionId=card.id.slice(card.id.lastIndexOf('-decision-')+'-decision-'.length);window.__artifactMock={fetch:window.fetch.bind(window),decisionId,button,intercepted:0};window.fetch=async(input,init)=>{const target=typeof input==='string'?input:input.url;const response=await window.__artifactMock.fetch(input,init);if(!target.includes('/decisions/'+window.__artifactMock.decisionId+'/artifact'))return response;window.__artifactMock.intercepted++;const artifact=await response.json();const request=JSON.stringify({messages:[{role:'system',content:'SYSTEM CONTENT MUST NOT APPEAR AS USER_PROMPT'},{role:'user',content:[{type:'text',text:'visible user text'},{type:'image_url',image_url:{url:'data:image/png;base64,AA=='}}]}]});artifact.prompt_bytes_base64=btoa(request);artifact.prompt_sha256='0'.repeat(64);return new Response(JSON.stringify(artifact),{status:200,headers:{'Content-Type':'application/json'}})};button.click();return true})())`);
  record('multimodal-prompt-fixture-is-installed', multimodalSetup);
  const multimodalState = await waitFor('JSON.stringify((()=>{const disclosure=document.querySelectorAll(".chat-user-prompt")[1];return {unavailable:disclosure?.innerText.includes("extraction is unavailable"),hasPrompt:!!disclosure?.querySelector("pre"),intercepted:window.__artifactMock?.intercepted??0,open:disclosure?.open}})())',
    (value) => value.unavailable && !value.hasPrompt && value.intercepted > 0,
    'mixed text and image user prompt is unavailable',
  );
  const multimodalDisclosure = evaluate('JSON.stringify((()=>{const details=document.querySelectorAll(".chat-user-prompt")[1];if(!details)return null;const summary=details.querySelector("summary");summary.click();const closed=!details.open&&!details.innerText.includes("extraction is unavailable");summary.click();return {closed,reopened:details.open,summary:summary.textContent.trim()}})())');
  record('multimodal-user-prompt-is-withheld-in-accessible-disclosure',
    multimodalState.unavailable && !multimodalState.hasPrompt && multimodalDisclosure?.closed && multimodalDisclosure.reopened && multimodalDisclosure.summary === 'USER_PROMPT',
    { intercepted_artifacts: multimodalState.intercepted, disclosure: multimodalDisclosure },
  );
  evaluate('JSON.stringify((()=>{if(window.__artifactMock){window.fetch=window.__artifactMock.fetch;delete window.__artifactMock}return true})())');

  if (focusedReviewFixes) {
    const focusedCompetitionRoute = `/simulation/${competitionId}`;
    axi('open', new URL(focusedCompetitionRoute, web).href);
    await waitFor('JSON.stringify({path:location.pathname,main:!!document.querySelector("main")})', (value) => value.path === focusedCompetitionRoute && value.main, 'competition view for focused position check');
    evaluate('JSON.stringify((()=>{window.__positionFetch=window.fetch.bind(window);window.__positionRequests=[];window.fetch=(input,init)=>{const target=typeof input==="string"?input:input.url;if(target.includes("/positions?"))window.__positionRequests.push(target);return window.__positionFetch(input,init)};return true})())');
    const overviewRoute = `/simulation/${competitionId}/models/${apiEvidence.baseline.model_ids[0]}`;
    record('model-link-opens-active-position-overview', clickHref(overviewRoute));
    const openOnlyRequest = await waitFor('JSON.stringify(window.__positionRequests?.find(url=>new URL(url,location.origin).searchParams.get("include_closed")==="false")??null)', (value) => typeof value === 'string', 'model overview requests open positions only');
    record('model-overview-uses-open-only-position-pages', new URL(openOnlyRequest, web).searchParams.get('include_closed') === 'false', { request: openOnlyRequest });
    record('return-to-run-chat-for-position-history-check', clickHref(`/simulation?run=${encodeURIComponent(competitionId)}`));
    await waitFor(`JSON.stringify({url:location.pathname,run:location.search.includes(${JSON.stringify(competitionId)})})`, (value) => value.url === '/simulation' && value.run, 'selected run before position history check');
    record('position-history-tab-opens', clickText('[aria-label="Activity views"] [role="tab"]', 'POSITIONS'));
    const allPositionsRequest = await waitFor('JSON.stringify(window.__positionRequests?.find(url=>new URL(url,location.origin).searchParams.get("include_closed")==="true")??null)', (value) => typeof value === 'string', 'competition position history includes closed records');
    record('competition-position-history-keeps-closed-records', new URL(allPositionsRequest, web).searchParams.get('include_closed') === 'true', { request: allPositionsRequest });
    evaluate('JSON.stringify((()=>{if(window.__positionFetch){window.fetch=window.__positionFetch;delete window.__positionFetch;delete window.__positionRequests}return true})())');

    axi('open', new URL('/simulation/blog', web).href);
    const legacyBlog = await waitFor('JSON.stringify({path:location.pathname,hash:location.hash,methodology:!!document.querySelector("#methodology"),heading:document.querySelector("#methodology #data-title")?.textContent.trim(),landing:!!document.querySelector(".landing-content")})', (value) => value.path === '/' && value.hash === '#methodology' && value.methodology && value.landing, 'legacy blog performs full landing navigation to methodology');
    record('legacy-blog-reaches-landing-methodology-dom', legacyBlog.heading === 'A traceable record', legacyBlog);
    return { routes: [narrativeRoute, focusedCompetitionRoute, overviewRoute, '/simulation/blog'], interactions: 'user prompt extraction and disclosure, exact request hash and download, mixed multimodal withholding, open-only and full position query modes, full-document landing methodology redirect' };
  }

  // Keyboard navigation must move focus and selection through both tab sets.
  evaluate('JSON.stringify((()=>{document.getElementById("rail-tab-chat")?.focus();return true})())');
  axi('press', 'ArrowRight');
  const detailsTab = await waitFor('JSON.stringify({selected:document.getElementById("rail-tab-details")?.getAttribute("aria-selected"),focus:document.activeElement?.id})', (value) => value.selected === 'true' && value.focus === 'rail-tab-details', 'activity tabs ArrowRight');
  axi('press', 'ArrowLeft');
  await waitFor('JSON.stringify({selected:document.getElementById("rail-tab-chat")?.getAttribute("aria-selected")})', (value) => value.selected === 'true', 'activity tabs ArrowLeft');
  record('activity-tabs-support-arrow-key-navigation', true, { arrow_right: detailsTab.selected, arrow_left: 'MODEL CHAT' });

  // Switch runs after filtering; run identity must reset the feed's local query state.
  const extended = apiEvidence.fixtures.find((fixture) => fixture.name.endsWith('extended empty evidence'));
  if (includeFixtures && extended) {
    fillChatFilter('BTC');
    clickText('aside button', 'GO');
    evaluate(`JSON.stringify((()=>{const a=[...document.querySelectorAll('a[href]')].find(e=>e.href.includes(${JSON.stringify(extended.id)}));if(!a)return false;a.click();return true})())`);
    await waitFor('JSON.stringify({url:location.pathname,fixture:document.body.innerText.includes("SIMULATION UI VALIDATION · EXTENDED EMPTY EVIDENCE"),symbol:document.querySelector("aside input")?.value})', (value) => value.url.endsWith(extended.id) && value.fixture && value.symbol === '', 'cross-run switch clears symbol filter');
    record('cross-run-switch-resets-chat-filter', true, { fixture: extended.id });
  }

  // Competition route: ranges, series, hover mapping, shared account palette and keyboard tabs.
  axi('open', new URL(competitionRoute, web).href);
  await waitFor('JSON.stringify({url:location.pathname,plot:!!document.querySelector(".equity-plot"),rows:document.querySelectorAll(".equity-line").length})', (value) => value.url === competitionRoute && value.plot && value.rows === apiEvidence.baseline.model_names.length, 'baseline chart and all model series');
  record('chart-range-72h-control-works', clickText('[aria-label="Chart time range"] button', '72H'));
  const rangeState = await waitFor('JSON.stringify({pressed:document.querySelector(".range-control [aria-pressed=true]")?.textContent.trim(),points:document.querySelectorAll(".equity-line").length})', (value) => value.pressed === '72H', '72 hour chart range');
  record('chart-range-state-is-selected', true, rangeState);
  const beforeLines = evaluate('JSON.stringify(document.querySelectorAll(".equity-line").length)');
  const firstSeries = evaluate('JSON.stringify(document.querySelector(".equity-legend input")?.labels?.[0]?.textContent.trim())');
  const toggled = evaluate('JSON.stringify((()=>{const e=document.querySelector(".equity-legend input");if(!e)return false;e.click();return true})())');
  await waitFor(`JSON.stringify({lines:document.querySelectorAll(".equity-line").length})`, (value) => value.lines === beforeLines - 1, 'series toggle hides one account');
  evaluate('JSON.stringify((()=>{document.querySelector(".equity-legend input")?.click();return true})())');
  await waitFor(`JSON.stringify({lines:document.querySelectorAll(".equity-line").length})`, (value) => value.lines === beforeLines, 'series toggle restores account');
  record('chart-series-can-hide-and-restore', true, { series: firstSeries, visible_before: beforeLines, visible_after: beforeLines });

  const hover = evaluate(`JSON.stringify((()=>{const svg=document.querySelector('.equity-plot');const rect=svg.getBoundingClientRect();const x=rect.left+rect.width*(78/Number(svg.viewBox.baseVal.width));const y=rect.top+rect.height*0.5;svg.dispatchEvent(new PointerEvent('pointermove',{clientX:x,clientY:y,bubbles:true}));return {x,y,viewWidth:svg.viewBox.baseVal.width,viewHeight:svg.viewBox.baseVal.height}})())`);
  const hoverState = await waitFor('JSON.stringify({text:document.querySelector(".equity-tooltip")?.innerText ?? ""})', (value) => /ROUND\s+0/i.test(value.text), 'chart plot-left maps to round zero');
  record('chart-left-edge-is-first-recorded-round', true, { pointer: hover, tooltip: hoverState.text });

  const palette = evaluate('JSON.stringify({lines:[...document.querySelectorAll(".equity-line")].map(e=>[...e.classList].find(c=>c.startsWith("model-tone-"))),accounts:[...document.querySelectorAll(".accounts-panel a")].map(e=>[...e.classList].find(c=>c.startsWith("model-tone-"))),chat:[...document.querySelectorAll(".chat-card")].slice(0,2).map(e=>[...e.classList].find(c=>c.startsWith("model-tone-")))})');
  record('chart-rail-and-accounts-share-model-palette',
    palette.lines.length === 2 && palette.lines.every((tone, index) => tone && tone === palette.accounts[index] && tone === palette.chat[index]),
    palette,
  );
  evaluate('JSON.stringify((()=>{document.querySelector(".competition-record-tabs [role=tab]")?.focus();return true})())');
  axi('press', 'ArrowRight');
  const recordTab = await waitFor('JSON.stringify({selected:document.querySelector(".competition-record-tabs [aria-selected=true]")?.textContent.trim(),focus:document.activeElement?.textContent.trim()})', (value) => value.selected === 'POSITIONS' && value.focus === 'POSITIONS', 'competition record tabs ArrowRight');
  record('competition-tabs-support-arrow-key-navigation', true, recordTab);

  evaluate('JSON.stringify((()=>{window.__positionFetch=window.fetch.bind(window);window.__positionRequests=[];window.fetch=(input,init)=>{const target=typeof input==="string"?input:input.url;if(target.includes("/positions?"))window.__positionRequests.push(target);return window.__positionFetch(input,init)};return true})())');
  const overviewRoute = `/simulation/${competitionId}/models/${apiEvidence.baseline.model_ids[0]}`;
  record('model-link-opens-active-position-overview', clickHref(overviewRoute));
  const openOnlyRequest = await waitFor('JSON.stringify(window.__positionRequests?.find(url=>new URL(url,location.origin).searchParams.get("include_closed")==="false")??null)',
    (value) => typeof value === 'string',
    'model overview requests open positions only',
  );
  record('model-overview-uses-open-only-position-pages', new URL(openOnlyRequest, web).searchParams.get('include_closed') === 'false', { request: openOnlyRequest });
  record('return-to-run-chat-for-position-history-check', clickHref(`/simulation?run=${encodeURIComponent(competitionId)}`));
  await waitFor(`JSON.stringify({url:location.pathname,run:location.search.includes(${JSON.stringify(competitionId)})})`, (value) => value.url === '/simulation' && value.run, 'selected run before position history check');
  record('position-history-tab-opens', clickText('[aria-label="Activity views"] [role="tab"]', 'POSITIONS'));
  const allPositionsRequest = await waitFor('JSON.stringify(window.__positionRequests?.find(url=>new URL(url,location.origin).searchParams.get("include_closed")==="true")??null)',
    (value) => typeof value === 'string',
    'competition position history includes closed records',
  );
  record('competition-position-history-keeps-closed-records', new URL(allPositionsRequest, web).searchParams.get('include_closed') === 'true', { request: allPositionsRequest });
  evaluate('JSON.stringify((()=>{if(window.__positionFetch){window.fetch=window.__positionFetch;delete window.__positionFetch;delete window.__positionRequests}return true})())');

  // Model deep links have one id per node and every explicit label resolves.
  for (const modelId of apiEvidence.baseline.model_ids) {
    const modelRoute = `/simulation/${competitionId}/models/${modelId}`;
    axi('open', new URL(modelRoute, web).href);
    await waitFor(`JSON.stringify({url:location.pathname,heading:document.querySelector('main h1')?.textContent.trim(),modelRows:document.querySelectorAll('.model-chart .equity-line').length,chatCards:document.querySelectorAll('aside .chat-card').length})`, (value) => value.url === modelRoute && value.heading === apiEvidence.baseline.model_names[apiEvidence.baseline.model_ids.indexOf(modelId)].toUpperCase() && value.modelRows === 1 && value.chatCards > 0, `model route data ${modelId}`);
    const accessibility = evaluate('JSON.stringify({duplicateIds:[...document.querySelectorAll("[id]")].map(e=>e.id).filter((id,index,all)=>all.indexOf(id)!==index),missingLabels:[...document.querySelectorAll("label[for]")].map(l=>l.htmlFor).filter(id=>!document.getElementById(id))})');
    record(`model-${modelId}-has-unique-ids-and-valid-labels`, accessibility.duplicateIds.length === 0 && accessibility.missingLabels.length === 0, accessibility);
  }
  const leaderboardRoute = `/simulation/${competitionId}/leaderboard`;
  axi('open', new URL(leaderboardRoute, web).href);
  await waitFor('JSON.stringify({url:location.pathname,rows:document.querySelectorAll(".leaderboard-table tbody tr").length})', (value) => value.url === leaderboardRoute && value.rows === apiEvidence.baseline.model_names.length, 'leaderboard accounts are loaded');
  clickPrefix('.leaderboard-table th button', 'ACCOUNT');
  const accountAsc = await waitFor('JSON.stringify({sort:document.querySelector(".leaderboard-table th[aria-sort]")?.getAttribute("aria-sort"),first:document.querySelector(".leaderboard-table tbody tr")?.innerText})', (value) => value.sort === 'ascending' && value.first?.includes('Atlas'), 'leaderboard account ascending sort');
  clickPrefix('.leaderboard-table th button', 'ACCOUNT');
  const accountDesc = await waitFor('JSON.stringify({sort:document.querySelector(".leaderboard-table th[aria-sort]")?.getAttribute("aria-sort"),first:document.querySelector(".leaderboard-table tbody tr")?.innerText})', (value) => value.sort === 'descending' && value.first?.includes('Vector'), 'leaderboard account descending sort');
  record('leaderboard-account-sort-toggles-order', true, { ascending_first: accountAsc.first, descending_first: accountDesc.first });

  if (includeFixtures) {
    const empty = apiEvidence.fixtures.find((fixture) => fixture.name.endsWith('extended empty evidence'));
    const running = apiEvidence.fixtures.find((fixture) => fixture.name.endsWith('running stream state'));
    const paused = apiEvidence.fixtures.find((fixture) => fixture.name.endsWith('paused lifecycle state'));
    const rulesUnavailable = apiEvidence.fixtures.find((fixture) => fixture.name.endsWith('rules evidence unavailable'));
    axi('open', new URL(`/simulation/${empty.id}`, web).href);
    const emptyState = await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),title:document.querySelector("main h1")?.textContent,main:document.querySelector("main")?.innerText,emptyChat:document.querySelector("aside")?.innerText})', (value) => value.id === empty.id && value.title?.toLowerCase().includes('extended empty evidence') && value.main?.includes('The API has no equity points for this competition.') && value.emptyChat?.includes('No model decisions match'), 'extended empty run and empty chat');
    record('empty-extended-run-has-real-empty-states', true, { id: empty.id, equity: 'The API has no equity points for this competition.', chat: emptyState.emptyChat.slice(-120) });

    axi('open', new URL(`/simulation/${paused.id}`, web).href);
    const pausedState = await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),status:document.querySelector(".data-status")?.textContent})', (value) => value.id === paused.id && value.status?.includes('PAUSED · 5 S REFRESH'), 'paused stream polling state');
    record('paused-run-exposes-polling-state', true, { id: paused.id, status: pausedState.status });

    axi('open', new URL(`/simulation/${running.id}`, web).href);
    const connectedState = await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),status:document.querySelector(".data-status")?.textContent})', (value) => value.id === running.id && value.status?.includes('EVENT STREAM CONNECTED'), 'live fixture connects to actual SSE API');
    record('running-fixture-connects-to-real-sse', true, { id: running.id, status: connectedState.status });

    // Inject a refused connection in this browser page, then restore the native EventSource and remount the route.
    evaluate('JSON.stringify((()=>{window.__realEventSource=window.EventSource;window.EventSource=class extends window.__realEventSource{constructor(_url,options){super("http://127.0.0.1:1/isolated-sse-failure",options)}};return true})())');
    clickHref(`/simulation/${competitionId}`);
    await waitFor('JSON.stringify({id:location.pathname.split("/").pop()})', (value) => value.id === competitionId, 'leave running stream before faulted reconnect');
    clickHref(`/simulation/${running.id}`);
    const reconnectingState = await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),status:document.querySelector(".data-status")?.textContent})', (value) => value.id === running.id && value.status?.includes('RECONNECTING'), 'isolated SSE failure state');
    evaluate('JSON.stringify((()=>{if(window.__realEventSource)window.EventSource=window.__realEventSource;return true})())');
    clickHref(`/simulation/${competitionId}`);
    await waitFor('JSON.stringify({id:location.pathname.split("/").pop()})', (value) => value.id === competitionId, 'clear faulted stream page');
    clickHref(`/simulation/${running.id}`);
    const recoveredState = await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),status:document.querySelector(".data-status")?.textContent})', (value) => value.id === running.id && value.status?.includes('EVENT STREAM CONNECTED'), 'SSE reconnects after browser fault is removed');
    record('sse-injected-url-failure-recovers-after-route-remount', true, { reconnecting: reconnectingState.status, recovered: recoveredState.status, fault: 'browser-only refused connection to 127.0.0.1:1' });

    // Probe the browser's real public API path while network emulation is toggled.
    axi('emulate', '--network', 'Offline');
    const browserApiUrl = new URL(`/api/v1/public/competitions/${competitionId}`, web).href;
    evaluate(`JSON.stringify((()=>{window.__networkProbe=null;fetch(${JSON.stringify(browserApiUrl)}).then(r=>{window.__networkProbe={ok:true,status:r.status}}).catch(e=>{window.__networkProbe={ok:false,error:e.message}});return true})())`);
    const networkError = await waitFor('JSON.stringify(window.__networkProbe)', (value) => value && value.ok === false, 'real browser API request fails while offline');
    axi('emulate', '--network', 'Fast 4G');
    evaluate(`JSON.stringify((()=>{window.__networkProbe=null;fetch(${JSON.stringify(browserApiUrl)}).then(r=>{window.__networkProbe={ok:true,status:r.status}}).catch(e=>{window.__networkProbe={ok:false,error:e.message}});return true})())`);
    const networkRecovered = await waitFor('JSON.stringify(window.__networkProbe)', (value) => value && value.ok === true && value.status === 200, 'real browser API request succeeds after network returns');
    record('real-browser-network-failure-and-recovery', true, {
      offline_probe: networkError,
      online_probe: networkRecovered,
      fault: 'Chrome DevTools AXI network emulation Offline; request used the real same-origin Vite API proxy',
      ui_error_state: 'not asserted; existing React Query data remained cached during the offline probe',
    });

    axi('open', new URL(`/simulation/${competitionId}`, web).href);
    await waitFor('JSON.stringify({main:!!document.querySelector("main")})', (value) => value.main, 'baseline before rules verification probe');
    // Fail only browser-side digest verification; API response bytes remain real and intact.
    evaluate('JSON.stringify((()=>{window.__originalDigest=crypto.subtle.digest.bind(crypto.subtle);crypto.subtle.digest=()=>Promise.reject(new Error("isolated verification failure"));return true})())');
    clickText('[aria-label="Activity views"] [role="tab"]', 'COMPETITION DETAILS');
    const verification = await waitFor('JSON.stringify({text:document.querySelector(".run-rules")?.innerText ?? "",disabled:[...document.querySelectorAll(".run-rules button")].some(b=>b.disabled)})', (value) => value.text.includes('verification is unavailable') && value.disabled, 'rules digest unavailable and exact download disabled');
    record('rules-digest-unavailable-is-visible-and-download-disabled', true, verification);
    evaluate('JSON.stringify((()=>{if(window.__originalDigest)crypto.subtle.digest=window.__originalDigest;return true})())');
    axi('open', new URL(`/simulation/${rulesUnavailable.id}`, web).href);
    await waitFor('JSON.stringify({id:location.pathname.split("/").pop(),source:document.querySelector("main")?.innerText})', (value) => value.id === rulesUnavailable.id && value.source?.includes('TEST FIXTURE'), 'explicit API unavailable scenario');
    clickText('[aria-label="Activity views"] [role="tab"]', 'COMPETITION DETAILS');
    const unavailable = await waitFor('JSON.stringify({text:document.querySelector(".run-rules")?.innerText ?? ""})', (value) => value.text.includes('Competition rules evidence unavailable'), 'rules API 503 renders an explicit unavailable state');
    record('rules-api-503-is-visible-and-retryable', unavailable.text.includes('Retry rules'), { fixture_id: rulesUnavailable.id, source_label: rulesUnavailable.source_label, text: unavailable.text });
  }

  axi('open', new URL('/simulation/blog', web).href);
  const legacyBlog = await waitFor('JSON.stringify({path:location.pathname,hash:location.hash,methodology:!!document.querySelector("#methodology"),heading:document.querySelector("#methodology #data-title")?.textContent.trim(),landing:!!document.querySelector(".landing-content")})',
    (value) => value.path === '/' && value.hash === '#methodology' && value.methodology && value.landing,
    'legacy blog performs full landing navigation to methodology',
  );
  record('legacy-blog-reaches-landing-methodology-dom', legacyBlog.heading === 'A traceable record', legacyBlog);

  return {
    viewport_sizes: viewports.map(([width, height]) => `${width}x${height}`),
    directory_screenshot: 'simulation-directory-1920x1080.png',
    narrative_screenshots: viewports.map(([width, height]) => `simulation-narrative-${width}x${height}.png`),
    competition_screenshots: screenshots,
    routes,
    interactions: 'filters, pagination, artifact button/blob SHA-256, multimodal prompt withholding and disclosure, open-only versus full position queries, full landing methodology redirect, keyboard tabs, ranges, series, pointer mapping, palette, model DOM ids/labels, isolated rules verification failure, injected SSE failure/remount recovery',
  };
}

let apiEvidence = null;
let browserEvidence = { skipped: apiOnly };
let failure = null;
try {
  apiEvidence = await apiChecks();
  if (!apiOnly) browserEvidence = await browserChecks(apiEvidence);
} catch (error) {
  failure = {
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : null,
  };
} finally {
  if (browserSessionStarted) {
    try {
      axi('stop');
    } catch {
      // Preserve the validation result if the owned browser session already exited.
    }
  }
  const evidence = {
    created_at: new Date().toISOString(),
    passed: failure === null && checks.every((check) => check.passed),
    failure,
    method: 'real local PostgreSQL replay API through FastAPI and Chrome DevTools AXI',
    artifact_hash_measurement: 'The browser computes the visible-download Blob SHA-256 in page context. An earlier AXI JSON-array capture was truncated; its shortened-text digest 0cfb6483a1181ebb1ef971fb931dba0f072787a1f8699613bf4bc05b1ce34490 did not represent the 6078-byte artifact, whose API SHA-256 is 968b3b1da429029fcd220b7533890109fd1f4ab89b9c1d239fe05d6266ac3c83.',
    no_paid_provider_calls: true,
    checks,
    api: apiEvidence,
    browser: browserEvidence,
  };
  await mkdir(path.dirname(evidencePath), { recursive: true });
  await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
}

if (failure) {
  console.error(JSON.stringify({ evidence: evidencePath, failure, checks: checks.length }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({ evidence: evidencePath, passed: checks.length, browser: browserEvidence }, null, 2));
}
