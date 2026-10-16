#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const api = new URL(process.env.SIMULATION_API_BASE_URL ?? 'http://127.0.0.1:8026/api/v1/public');
const web = new URL(process.env.SIMULATION_BASE_URL ?? 'http://127.0.0.1:5186');
const session = process.env.CHROME_DEVTOOLS_AXI_SESSION ?? 'arena-lab-expanded-tests';
const evidenceFile = path.join(root, 'docs/evidence/expanded-simulation-validation-2026-10-16.json');
const screenshotDir = path.join(root, 'docs/screenshots');
const sourceDir = process.env.SIMULATION_REFERENCE_DIR ?? path.join(root, 'logos/site');
const checks = [];
let started = false;

function sha256(bytes) { return createHash('sha256').update(bytes).digest('hex'); }
function record(name, passed, details = {}) {
  checks.push({ name, passed, ...details });
}
function axi(...args) {
  return execFileSync('chrome-devtools-axi', args, {
    cwd: root,
    env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 120_000,
  });
}
function evaluate(expression) {
  const output = axi('eval', expression);
  if (/result was truncated|output truncated/i.test(output)) throw new Error('AXI truncated a browser result');
  const line = output.split('\n').find((item) => item.startsWith('result: '));
  if (!line) throw new Error(`Browser evaluation returned no result: ${output}`);
  let value = JSON.parse(line.slice('result: '.length));
  for (let i = 0; i < 3 && typeof value === 'string'; i += 1) {
    try { value = JSON.parse(value); } catch { break; }
  }
  return value;
}
async function waitFor(expression, predicate, name, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    last = evaluate(expression);
    if (predicate(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${name}: ${JSON.stringify(last)}`);
}
async function json(route) {
  const url = route.startsWith('/api/v1/public/') ? new URL(route, api.origin) : new URL(route.replace(/^\/+/, ''), `${api.href.replace(/\/$/, '')}/`);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  return response.json();
}
function click(selector, text) {
  return evaluate(`JSON.stringify((()=>{const e=[...document.querySelectorAll(${JSON.stringify(selector)})].find(n=>n.textContent.trim()===${JSON.stringify(text)});if(!e)return false;e.click();return true})())`);
}
function fill(selector, value) {
  return evaluate(`JSON.stringify((()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return false;const p=Object.getPrototypeOf(e);const d=Object.getOwnPropertyDescriptor(p,'value');d?.set?.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true})())`);
}
function open(route) { axi('open', new URL(route, web).href); }

const sourceViews = [
  { source: 'Screenshot from 2026-10-16 09-40-50.png', key: 'aggregate-chat', route: () => '/simulation', action: 'aggregate-chat-all', note: 'Season activity chat scoped to the real baseline replay; the API serves local published runs, not the former hosted season aggregate.' },
  { source: 'Screenshot from 2026-10-16 10-36-42.png', key: 'aggregate-chat-model', route: () => '/simulation', action: 'aggregate-chat-model', note: 'Season activity chat additionally filtered to the actual Atlas account.' },
  { source: 'Screenshot from 2026-10-16 10-36-49.png', key: 'selected-chat', route: (id) => `/simulation?run=${id}`, action: 'selected-run-chat', note: 'Selected-run activity rail with the real public decision feed and exact disclosed artifacts.' },
  { source: 'Screenshot from 2026-10-16 10-36-55.png', key: 'leaderboard-overall', route: (id) => `/simulation/${id}/leaderboard`, note: 'Overall account ranking from public leaderboard rows.' },
  { source: 'Screenshot from 2026-10-16 10-36-58.png', key: 'leaderboard-advanced', route: (id) => `/simulation/${id}/leaderboard`, action: 'advanced', note: 'Advanced tab preserves unavailable source metrics as N/A.' },
  { source: 'Screenshot from 2026-10-16 10-37-03.png', key: 'leaderboard-average-summary', route: (id) => `/simulation/${id}/leaderboard`, action: 'average-advanced', note: 'Average enabled for the actual provider/model accounts; each group is N=1 in this replay.' },
  { source: 'Screenshot from 2026-10-16 10-37-12.png', key: 'model-summary', route: (id, agent) => `/simulation/${id}/models/${agent}`, note: 'Public model profile summary and reported metrics.' },
  { source: 'Screenshot from 2026-10-16 10-37-15.png', key: 'model-positions-trades', route: (id, agent) => `/simulation/${id}/models/${agent}`, action: 'positions-trades', note: 'Public position and fill panels. This closed replay has zero open positions; its actual fill rows remain available.' },
  { source: 'Screenshot from 2026-10-16 10-37-25.png', key: 'season-details', route: () => '/simulation', action: 'season-details', note: 'Season details rail adapted to the actual public run index and declared run profiles.' },
];

async function main() {
  await mkdir(path.dirname(evidenceFile), { recursive: true });
  await mkdir(screenshotDir, { recursive: true });
  const competitions = await json('/competitions');
  const baseline = competitions.find((item) => item.id === '036d6115-3edb-5dca-92d3-eb46a649a1b2');
  if (!baseline || !baseline.source_label.startsWith('DEMO REPLAY')) throw new Error('Expected real DEMO REPLAY baseline was not found');
  const modelIds = { Atlas: 'ce388865-2dfe-5055-9173-2bbce70b24cc', Vector: '94cfdc45-adb3-5766-b2d1-bbd78ad49783' };
  const [leaderboard, atlasPositions, atlasTrades, decisions] = await Promise.all([
    json(`/competitions/${baseline.id}/leaderboard`),
    json(`/competitions/${baseline.id}/positions?limit=200&agent_id=${modelIds.Atlas}`),
    json(`/competitions/${baseline.id}/trades?limit=200&agent_id=${modelIds.Atlas}`),
    json(`/competitions/${baseline.id}/decisions?limit=200`),
  ]);
  record('source-replay-identity-and-read-only-records', baseline.state === 'FINISHED' && baseline.agents.length === 2 && atlasPositions.total === 0 && atlasTrades.total > 0 && decisions.total > 0, {
    id: baseline.id, source_label: baseline.source_label, state: baseline.state,
    model_ids: baseline.agents.map((agent) => agent.id), atlas_open_positions: atlasPositions.total,
    atlas_fill_rows: atlasTrades.total, decision_rows: decisions.total,
  });

  axi('open', web.href);
  started = true;
  await waitFor('JSON.stringify({url:location.pathname,h1:document.querySelector("main h1")?.textContent.trim(),fonts:document.fonts.status,navigation:[...document.querySelectorAll("header nav a")].map(a=>a.textContent.trim())})',
    (value) => value.url === '/' && value.h1 && value.fonts === 'loaded', 'landing page, headline, navigation, and loaded fonts');
  const landing = evaluate('JSON.stringify({h1:document.querySelector("main h1")?.textContent.trim(),fonts:document.fonts.status,links:[...document.querySelectorAll("header nav a")].map(a=>({text:a.textContent.trim(),href:a.getAttribute("href"),visible:!!(a.offsetWidth||a.offsetHeight||a.getClientRects().length)}))})');
  record('protected-landing-remains-rendered-with-loaded-fonts', !!landing.h1 && landing.fonts === 'loaded' && landing.links.some((link) => /simulation/i.test(link.text) && link.visible), landing);

  const screenshots = [];
  const sourceTypography = [];
  const widths = [[1920, 932], [1440, 900], [1024, 768], [768, 1024], [640, 900], [390, 844]];
  for (const view of sourceViews) {
    const route = view.route(baseline.id, modelIds.Atlas);
    open(route);
    await waitFor('JSON.stringify({path:location.pathname,h1:document.querySelector("main h1")?.textContent.trim(),body:document.body.innerText.length})',
      (value) => value.path === new URL(route, web).pathname && value.h1 && value.body > 80, `${view.key} view ready`);
    if (view.action === 'advanced' || view.action === 'average-advanced') {
      if (view.action === 'average-advanced') {
        const checkbox = evaluate('JSON.stringify(!!document.querySelector(".lb-average input"))');
        if (!checkbox) throw new Error('Leaderboard average checkbox was not found');
        evaluate('JSON.stringify((()=>{const e=document.querySelector(".lb-average input");e.click();return e.checked})())');
      }
      click('[role="tab"]', 'ADVANCED ANALYTICS');
      await waitFor('JSON.stringify({tab:document.querySelector("[role=tab][aria-selected=true]")?.textContent.trim(),rows:document.querySelectorAll(".lb-table tbody tr").length})',
        (value) => value.tab === 'ADVANCED ANALYTICS' && value.rows === 4, `${view.key} state`);
    }
    if (view.action === 'aggregate-chat-all' || view.action === 'aggregate-chat-model') {
      const selected = evaluate(`JSON.stringify((()=>{const run=document.querySelector("#aggregate-run-filter");if(!run)return false;run.value=${JSON.stringify(baseline.id)};run.dispatchEvent(new Event("change",{bubbles:true}));return true})())`);
      if (!selected) throw new Error('Aggregate run selector was not found');
      await waitFor('JSON.stringify(document.querySelector("#aggregate-run-filter")?.value)', (value) => value === baseline.id, 'aggregate chat baseline selection');
      if (view.action === 'aggregate-chat-model') {
        evaluate(`JSON.stringify((()=>{const model=document.querySelector("#aggregate-model-filter");if(!model)return false;model.value=${JSON.stringify(modelIds.Atlas)};model.dispatchEvent(new Event("change",{bubbles:true}));return true})())`);
        await waitFor('JSON.stringify({model:document.querySelector("#aggregate-model-filter")?.value,cards:document.querySelectorAll(".chat-card").length})', (value) => value.model === modelIds.Atlas && value.cards === 10, 'aggregate chat filtered to Atlas');
      } else {
        await waitFor('JSON.stringify({model:document.querySelector("#aggregate-model-filter")?.value,cards:document.querySelectorAll(".chat-card").length})', (value) => value.model === '' && value.cards === 10, 'aggregate chat first page across both accounts');
      }
    }
    if (view.action === 'selected-run-chat') {
      await waitFor('JSON.stringify({tabs:[...document.querySelectorAll(".arena-rail-tabs [role=tab]")].map(t=>t.textContent.trim()),cards:document.querySelectorAll(".chat-card").length})',
        (value) => value.tabs.includes('COMPLETED FILLS') && value.tabs.includes('POSITIONS') && value.cards === 10, 'selected run activity rail');
      evaluate('JSON.stringify((()=>{document.querySelector(".chat-expand")?.click();return true})())');
      await waitFor('JSON.stringify({detail:!!document.querySelector(".chat-detail"),prompt:document.body.textContent.includes("USER_PROMPT"),trading:document.body.textContent.includes("TRADING_DECISIONS")})',
        (value) => value.detail && value.prompt && value.trading, 'selected-run chat public prompt and proposal disclosures');
    }
    if (view.action === 'season-details') {
      click('#rail-tab-details', 'SEASON DETAILS');
      await waitFor('JSON.stringify({tab:document.querySelector(".arena-rail-tabs [aria-selected=true]")?.textContent.trim(),runs:document.querySelectorAll(".season-run-card").length})',
        (value) => value.tab === 'SEASON DETAILS' && value.runs > 0, 'season details run index');
      const type = evaluate('JSON.stringify({body:getComputedStyle(document.querySelector(".season-method p")).fontSize,heading:getComputedStyle(document.querySelector(".season-method h3")).fontSize,run:getComputedStyle(document.querySelector(".season-run-copy strong")).fontSize})');
      sourceTypography.push({ view: view.key, ...type });
      record('season-details-reference-font-sizes', type.body === '12px' && type.heading === '14px' && type.run === '11px', type);
    }
    if (view.action === 'aggregate-chat-all' || view.action === 'aggregate-chat-model') {
      const type = evaluate('JSON.stringify({filter:getComputedStyle(document.querySelector("#aggregate-run-filter")).fontSize,body:getComputedStyle(document.querySelector(".rail-intro")).fontSize})');
      sourceTypography.push({ view: view.key, ...type });
      record('aggregate-chat-filter-font-sizes', type.filter === '11px' && type.body === '9px', type);
    }
    if (view.action === 'positions-trades') {
      for (const summary of ['POSITION AND FUNDING HISTORY', 'COMPLETE FILL HISTORY']) {
        evaluate(`JSON.stringify((()=>{const s=[...document.querySelectorAll(".md-disclosure summary")].find(e=>e.textContent.includes(${JSON.stringify(summary)}));if(s&&!s.parentElement.open)s.click();return !!s})())`);
      }
      await waitFor('JSON.stringify({open:document.querySelectorAll(".md-disclosure[open]").length,positionText:document.body.innerText.includes("No open position rows"),fillTable:!!document.querySelector(".md-fill-table tbody tr")})',
        (value) => value.open >= 2 && value.positionText && value.fillTable, 'actual empty positions and real fill rows');
    }
    if (view.action === 'decisions') {
      evaluate('JSON.stringify((()=>{const s=[...document.querySelectorAll("details.md-disclosure > summary")].find(e=>e.textContent.includes("DECISIONS AND ARTIFACTS"));if(s&&!s.parentElement.open)s.click();return !!s})())');
      await waitFor('JSON.stringify({cards:document.querySelectorAll(".chat-card").length,expand:!!document.querySelector(".chat-expand")})',
        (value) => value.cards > 0 && value.expand, 'model-scoped decision cards');
      evaluate('JSON.stringify((()=>{document.querySelector(".chat-expand")?.click();return true})())');
      const evidence = await waitFor('JSON.stringify({detail:!!document.querySelector(".chat-detail"),prompt:document.body.textContent.includes("USER_PROMPT"),trading:document.body.textContent.includes("TRADING_DECISIONS"),download:!!document.querySelector(".artifact-block button")})',
        (value) => value.detail && value.prompt, 'actual prompt and proposal evidence in a selected decision');
      record('selected-model-decision-shows-public-prompt-and-recorded-proposals', evidence.prompt && evidence.trading, evidence);
    }
    if (view.action === 'settings') {
      evaluate('JSON.stringify((()=>{const s=[...document.querySelectorAll("details.md-disclosure > summary")].find(e=>e.textContent.includes("PUBLIC MODEL SETTINGS AND AUDIT REFERENCES"));if(s&&!s.parentElement.open)s.click();return !!s})())');
      await waitFor('JSON.stringify({open:!![...document.querySelectorAll("details.md-disclosure")].find(e=>e.textContent.includes("PUBLIC MODEL SETTINGS AND AUDIT REFERENCES")&&e.open),hash:document.querySelector(".md-audit-facts")?.textContent.includes("Settings SHA-256")})',
        (value) => value.open && value.hash, 'public model settings and hashes disclosure');
    }
    axi('resize', '1920', '1080');
    if (view.key === 'leaderboard-overall' || view.key === 'leaderboard-advanced' || view.key === 'leaderboard-average-summary') {
      const tableFit = evaluate('JSON.stringify((()=>{const wrap=document.querySelector(".lb-panel .lb-table-wrap");const table=wrap?.querySelector(".lb-table:not(.lb-detail-table)");const bounds=wrap?.getBoundingClientRect();const rect=table?.getBoundingClientRect();const row=table?.querySelector("tbody tr");const labels=[...table?.querySelectorAll("tbody tr td:nth-child(2) .lb-model-link")??[]].map(e=>({text:e.textContent.trim(),title:e.title}));return {viewport:innerWidth,wrapClient:wrap?.clientWidth,wrapScroll:wrap?.scrollWidth,wrapRight:bounds?.right,tableRight:rect?.right,columns:row?.children.length,labels}})())');
      const fits = tableFit.viewport === 1920 && tableFit.wrapScroll <= tableFit.wrapClient + 1 && tableFit.tableRight <= tableFit.wrapRight + 1;
      if (view.key === 'leaderboard-overall') record('leaderboard-overall-table-fits-desktop-container', fits && tableFit.columns === 11, tableFit);
      if (view.key === 'leaderboard-advanced') record('leaderboard-advanced-table-fits-desktop-container', fits && tableFit.columns === 13, tableFit);
      if (view.key === 'leaderboard-average-summary') {
        const baseNames = tableFit.labels.length === 2 && tableFit.labels.every((label) => label.text.length > 0 && !label.text.includes(' · ') && !label.title.includes(' · '));
        record('leaderboard-average-n1-uses-base-model-labels', baseNames, tableFit.labels);
        record('leaderboard-average-13-column-table-fits-desktop-container', fits && tableFit.columns === 13, tableFit);
      }
    }
    const filename = `expanded-simulation-${view.key}-1920x1080.png`;
    axi('screenshot', path.join('docs/screenshots', filename));
    const sourceBytes = await readFile(path.join(sourceDir, view.source));
    screenshots.push({ filename, route, source: view.source, source_sha256: sha256(sourceBytes), source_bytes: sourceBytes.length, adaptation: view.note });
  }
  record('nine-reference-states-captured', screenshots.length === 9, { screenshots: screenshots.map(({ filename, source }) => ({ filename, source })) });

  const layoutScreenshots = [];
  const liveRoute = `/simulation?run=${baseline.id}`;
  open(liveRoute);
  await waitFor('JSON.stringify({path:location.pathname,cards:document.querySelectorAll(".chat-card").length,rail:!!document.querySelector(".arena-rail")})',
    (value) => value.path === '/simulation' && value.cards === 10 && value.rail, 'selected-run live layout');
  const liveLayouts = [];
  for (const [width, height] of widths) {
    axi('resize', String(width), String(height));
    const metrics = evaluate('JSON.stringify((()=>{const rail=document.querySelector(".arena-rail").getBoundingClientRect();const main=document.querySelector(".arena-main").getBoundingClientRect();const link=[...document.querySelectorAll(".arena-nav a")].find(a=>a.textContent.trim()==="LIVE");return {width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,rail:{left:rail.left,right:rail.right,top:rail.top,bottom:rail.bottom,width:rail.width},main:{left:main.left,right:main.right,top:main.top,bottom:main.bottom,width:main.width},liveLink:link?{visible:!!(link.offsetWidth||link.offsetHeight||link.getClientRects().length),right:link.getBoundingClientRect().right}:null,selectedTab:document.querySelector(".arena-rail-tabs [aria-selected=true]")?.textContent.trim()}})())');
    liveLayouts.push(metrics);
    const railFits = width === 1920 ? Math.abs(metrics.rail.width - 500) <= 2 : width > 800 ? metrics.rail.width > 0 : metrics.rail.top >= metrics.main.bottom - 1;
    const fit = metrics.documentWidth <= width + 1 && metrics.bodyWidth <= width + 1 && metrics.liveLink?.visible && metrics.liveLink.right <= width + 1 && railFits;
    record(`live-layout-${width}x${height}-navigation-and-rail-fit`, fit, metrics);
    if (width === 390) {
      const filename = 'expanded-simulation-live-mobile-390x844.png';
      axi('screenshot', path.join('docs/screenshots', filename));
      layoutScreenshots.push(filename);
    }
  }
  record('live-rail-is-500px-on-desktop-and-stacks-on-mobile', liveLayouts[0].width === 1920 && Math.abs(liveLayouts[0].rail.width - 500) <= 2 && liveLayouts.filter((item) => item.width <= 800).every((item) => item.rail.top >= item.main.bottom - 1), liveLayouts.map((item) => ({ width: item.width, rail_width: item.rail.width, rail_top: item.rail.top, main_bottom: item.main.bottom })));

  const leaderboardRoute = `/simulation/${baseline.id}/leaderboard`;
  open(leaderboardRoute);
  await waitFor('JSON.stringify({path:location.pathname,rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length,nav:!!document.querySelector(".arena-nav")})',
    (value) => value.path === leaderboardRoute && value.rows === 2 && value.nav, 'standalone leaderboard layout');
  const leaderboardLayouts = [];
  for (const [width, height] of widths) {
    axi('resize', String(width), String(height));
    const metrics = evaluate('JSON.stringify((()=>{const page=document.querySelector(".leaderboard-page").getBoundingClientRect();const wrap=document.querySelector("#lb-panel-overall .lb-table-wrap");const table=wrap?.getBoundingClientRect();const link=[...document.querySelectorAll(".arena-nav a")].find(a=>a.textContent.trim()==="LEADERBOARD");return {width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,page:{left:page.left,right:page.right,width:page.width},table:wrap?{client:wrap.clientWidth,scroll:wrap.scrollWidth,left:table.left,right:table.right}:null,nav:link?{visible:!!(link.offsetWidth||link.offsetHeight||link.getClientRects().length),right:link.getBoundingClientRect().right}:null}})())');
    leaderboardLayouts.push(metrics);
    const fit = metrics.documentWidth <= width + 1 && metrics.bodyWidth <= width + 1 && metrics.nav?.visible && metrics.nav.right <= width + 1 && (width !== 1920 || Math.abs(metrics.page.width - 1568) <= 2) && (width !== 390 || metrics.table?.scroll > metrics.table?.client && metrics.table.right <= width + 1);
    record(`leaderboard-layout-${width}x${height}-max-width-and-table-fit`, fit, metrics);
    if (width === 390) {
      const filename = 'expanded-simulation-leaderboard-mobile-390x844.png';
      axi('screenshot', path.join('docs/screenshots', filename));
      layoutScreenshots.push(filename);
    }
  }
  evaluate('JSON.stringify((()=>{window.scrollTo(0,600);return true})())');
  const stickyHeader = await waitFor('JSON.stringify({scrollY:window.scrollY,position:getComputedStyle(document.querySelector("#lb-panel-overall .lb-table:not(.lb-detail-table) thead th")).position,top:document.querySelector("#lb-panel-overall .lb-table:not(.lb-detail-table) thead th").getBoundingClientRect().top})',
    (value) => value.scrollY > 0, 'standalone leaderboard document scroll');
  record('leaderboard-table-header-sticks-at-document-top', stickyHeader.position === 'sticky' && stickyHeader.top <= 2, stickyHeader);
  evaluate('JSON.stringify((()=>{window.scrollTo(0,0);return true})())');

  // Leaderboard behavior and the exact page-level state are checked against the real replay.
  open(leaderboardRoute);
  await waitFor('JSON.stringify({rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length,defaultSort:document.querySelector("#lb-panel-overall .lb-table:not(.lb-detail-table) thead th[aria-sort=descending]")?.innerText.trim(),winner:document.querySelector(".lb-winner-name")?.innerText.trim()})',
    (value) => value.rows === 2 && value.defaultSort?.includes('ACCOUNT VALUE'), 'default leaderboard order and winner');
  const rankBefore = evaluate('JSON.stringify([...document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr")].map(e=>e.innerText.split("\\t")[1]))');
  click('.lb-sort', 'ACCOUNT VALUE ↓');
  const reversed = await waitFor('JSON.stringify({sort:document.querySelector("#lb-panel-overall .lb-table:not(.lb-detail-table) thead th[aria-sort=ascending]")?.innerText.trim(),winner:document.querySelector(".lb-winner-name a")?.getAttribute("href"),rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length})', (value) => value.sort?.includes('ACCOUNT VALUE') && value.rows === 2, 'equity sort toggle');
  record('leaderboard-equity-sort-and-independent-winner', reversed.winner?.endsWith(modelIds.Atlas), { before: rankBefore, winner_after_sort: reversed.winner, expected_highest_equity_model_id: modelIds.Atlas });
  click('[role="tab"]', 'ADVANCED ANALYTICS');
  await waitFor('JSON.stringify(document.querySelector("[role=tab][aria-selected=true]")?.textContent.trim())', (value) => value === 'ADVANCED ANALYTICS', 'advanced leaderboard tab');
  evaluate('JSON.stringify((()=>{document.querySelector("[role=tab][aria-selected=true]")?.focus();return document.activeElement?.getAttribute("aria-selected")})())');
  axi('press', 'ArrowLeft');
  const tabState = await waitFor('JSON.stringify({selected:document.querySelector("[role=tab][aria-selected=true]")?.textContent.trim(),focus:document.activeElement?.textContent.trim()})', (value) => value.selected === 'OVERALL STATS', 'leaderboard roving tabs');
  record('leaderboard-tabs-keyboard-navigation', tabState.selected === 'OVERALL STATS', tabState);
  const competitorSelect = evaluate('JSON.stringify({value:document.querySelector(".lb-scope select")?.value,options:[...document.querySelectorAll(".lb-scope option")].length})');
  record('leaderboard-competition-selector-has-options', competitorSelect.options >= 2, competitorSelect);
  const emptyFixture = competitions.find((item) => item.source_label.startsWith('TEST FIXTURE') && item.profile === 'research_extended');
  const rulesFixture = competitions.find((item) => item.source_label.startsWith('TEST FIXTURE') && item.name.includes('rules evidence unavailable'));
  if (emptyFixture) {
    evaluate(`JSON.stringify((()=>{const e=document.querySelector(".lb-scope select");e.value=${JSON.stringify(emptyFixture.id)};e.dispatchEvent(new Event("change",{bubbles:true}));return true})())`);
    const changed = await waitFor('JSON.stringify({path:location.pathname,rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length,heading:document.querySelector(".lb-title-block h1")?.textContent.trim()})',
      (value) => value.path.endsWith(`${emptyFixture.id}/leaderboard`) && value.rows === 1 && value.heading === 'LEADERBOARD', 'switch leaderboard to empty extended fixture');
    record('competition-selector-navigates-and-loads-new-competition', true, { competition_id: emptyFixture.id, rows: changed.rows });
    evaluate(`JSON.stringify((()=>{const e=document.querySelector(".lb-scope select");e.value=${JSON.stringify(baseline.id)};e.dispatchEvent(new Event("change",{bubbles:true}));return true})())`);
    await waitFor('JSON.stringify({path:location.pathname,rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length})',
      (value) => value.path.endsWith(`${baseline.id}/leaderboard`) && value.rows === 2, 'return leaderboard to actual baseline');
  }

  // The average checkbox is exercised with a two-account browser-side input to the actual pure helper.
  evaluate('JSON.stringify((()=>{window.__meanProof={status:"loading"};import("/src/simulation/leaderboard.tsx").then(m=>{const base={provider:"TEST PROVIDER",model:"TEST MODEL",name:"Account A",agentIds:["a"],members:1,key:"a",values:{equity:100,roi_pct:1,total_pnl:0,fees:2,win_rate_pct:50,sharpe_ratio:null,trade_count:2,average_leverage:null,realized_pnl:4,unrealized_pnl:null,funding:1,profit_factor:null,max_drawdown_pct:null,current_margin_used:10,current_gross_exposure:20,closed_trades:1,winning_trades:1,losing_trades:0}};const other={...base,name:"Account B",agentIds:["b"],key:"b",values:{...base.values,equity:200,roi_pct:3,trade_count:4,realized_pnl:8,fees:null}};const r=m.averageRows([base,other]);window.__meanProof={status:"ready",result:{count:r.length,members:r[0]?.members,ids:r[0]?.agentIds,equity:r[0]?.values.equity,roi:r[0]?.values.roi_pct,fees:r[0]?.values.fees,sharpe:r[0]?.values.sharpe_ratio}}}).catch(e=>window.__meanProof={status:"error",message:String(e)});return true})())');
  const meanState = await waitFor('JSON.stringify(window.__meanProof)', (value) => value?.status !== 'loading', 'browser-imported average helper');
  if (meanState.status === 'error') throw new Error(`Could not run the exported average helper: ${meanState.message}`);
  const avgResult = meanState.result;
  record('average-helper-groups-pair-means-values-and-excludes-null', avgResult.count === 1 && avgResult.members === 2 && avgResult.equity === 150 && avgResult.roi === 2 && avgResult.fees === 2 && avgResult.sharpe === null, avgResult);

  if (emptyFixture) {
    open(`/simulation?run=${emptyFixture.id}`);
    const emptyState = await waitFor('JSON.stringify({selected:document.body.textContent.includes("SIMULATION UI VALIDATION · extended empty evidence"),empty:document.body.textContent.includes("No model decisions match this filter."),cards:document.querySelectorAll(".chat-card").length})',
      (value) => value.selected && value.empty && value.cards === 0, 'real empty run chat state');
    record('empty-fixture-run-renders-public-empty-state', emptyState.empty && emptyState.cards === 0, { fixture_id: emptyFixture.id, cards: emptyState.cards });
  }
  if (rulesFixture) {
    open(`/simulation?run=${rulesFixture.id}`);
    await waitFor('JSON.stringify({selected:document.body.textContent.includes("SIMULATION UI VALIDATION · rules evidence unavailable"),tab:!!document.querySelector("#rail-tab-details")})',
      (value) => value.selected && value.tab, 'rules-error fixture run');
    click('#rail-tab-details', 'COMP DETAILS');
    const rulesError = await waitFor('JSON.stringify({alert:document.querySelector("#rail-panel [role=alert]")?.textContent.trim(),retry:!!document.querySelector("#rail-panel [role=alert] button")})',
      (value) => value.alert && value.retry, 'service-reported unavailable rules state');
    record('public-rules-error-has-visible-retry', /503|unavailable|failed|error/i.test(rulesError.alert) && rulesError.retry, { fixture_id: rulesFixture.id, alert: rulesError.alert });
  }

  // Exercise the run-scoped chat filter and pagination against the actual 40 public decisions.
  const narrativeRoute = `/simulation?run=${encodeURIComponent(baseline.id)}`;
  open(narrativeRoute);
  await waitFor('JSON.stringify({path:location.pathname,selected:document.body.textContent.includes("Offline Paper Arena · fill evidence v3 · 20 rounds"),cards:document.querySelectorAll(".chat-card").length})',
    (value) => value.path === '/simulation' && value.selected && value.cards === 10, 'selected run chat rail and first page');
  const filterSelect = evaluate('JSON.stringify([...document.querySelectorAll("select")].map(e=>({id:e.id,options:[...e.options].map(o=>({text:o.textContent.trim(),value:o.value}))})))');
  const modelFilter = filterSelect.find((item) => item.options.some((option) => option.value === modelIds.Atlas));
  record('run-chat-filter-exposes-real-model-accounts', !!modelFilter, { select: modelFilter?.id, options: modelFilter?.options.length });
  if (modelFilter) {
    fill(`#${modelFilter.id}`, modelIds.Atlas);
    await waitFor('JSON.stringify({model:document.querySelector("#'+modelFilter.id+'")?.value,cards:document.querySelectorAll(".chat-card").length})',
      (value) => value.model === modelIds.Atlas && value.cards === 10, 'model filter to a real account');
  }
  const symbolInput = evaluate('JSON.stringify([...document.querySelectorAll("input")].find(e=>e.placeholder==="SYMBOL")?.id ?? null)');
  if (!symbolInput) throw new Error('Run-scoped chat symbol filter not found');
  fill(`#${symbolInput}`, 'ZZZ_NOT_IN_API');
  click('form.chat-symbol-form button', 'GO');
  await waitFor('JSON.stringify({empty:document.body.textContent.includes("No model decisions match this filter."),model:document.querySelector("#'+modelFilter?.id+'")?.value})',
    (value) => value.empty && value.model === modelIds.Atlas, 'unmatched symbol state retaining model filter');
  record('chat-symbol-filter-empty-state-preserves-model-filter', true, { symbol: 'ZZZ_NOT_IN_API', selected_agent: modelIds.Atlas });
  fill(`#${symbolInput}`, '');
  click('form.chat-symbol-form button', 'GO');
  await waitFor('JSON.stringify({cards:document.querySelectorAll(".chat-card").length,range:document.querySelector(".history-pagination span")?.textContent.trim()})',
    (value) => value.cards > 0 && value.range?.endsWith('of 20'), 'chat filters clear and restore matching account decisions');
  const firstRound = evaluate('JSON.stringify(document.querySelector(".chat-card .chat-head")?.innerText.trim())');
  click('.history-pagination button', 'NEXT');
  const nextPage = await waitFor('JSON.stringify({cards:document.querySelectorAll(".chat-card").length,range:document.querySelector(".history-pagination span")?.textContent.trim(),first:document.querySelector(".chat-card .chat-head")?.innerText.trim()})',
    (value) => value.range?.startsWith('11–') && value.first !== firstRound, 'next page shows different real decisions');
  record('chat-pagination-next-changes-real-decisions', true, { first_page_card: firstRound, second_page_card: nextPage.first, range: nextPage.range });

  // Verify that the visible public artifact download preserves the API's exact prompt bytes.
  const atlasDecisionPage = await json(`/competitions/${baseline.id}/decisions?limit=10&agent_id=${modelIds.Atlas}`);
  const auditDecision = atlasDecisionPage.items.find((item) => item.prompt_sha256);
  if (!auditDecision) throw new Error('Atlas public decisions do not include a prompt hash');
  const artifactUrl = new URL(auditDecision.artifact_url, api.origin);
  const artifactResponse = await fetch(artifactUrl);
  if (!artifactResponse.ok) throw new Error(`Artifact request returned ${artifactResponse.status}`);
  const artifact = await artifactResponse.json();
  const promptHash = sha256(Buffer.from(artifact.prompt_bytes_base64, 'base64'));
  record('api-artifact-prompt-bytes-match-published-hash', promptHash === auditDecision.prompt_sha256 && promptHash === artifact.prompt_sha256,
    { decision_id: auditDecision.id, prompt_sha256: promptHash });
  // Return to the selected model page with the same API decision highlighted through its route query.
  open(`/simulation/${baseline.id}/models/${modelIds.Atlas}?decision=${auditDecision.id}&round=${auditDecision.round}`);
  evaluate('JSON.stringify((()=>{document.querySelector(".chat-expand")?.click();return true})())');
  await waitFor('JSON.stringify({path:location.pathname,linked:!!document.querySelector(".chat-card--linked"),prompt:document.body.textContent.includes("USER_PROMPT")})',
    (value) => value.path === `/simulation/${baseline.id}/models/${modelIds.Atlas}` && value.linked && value.prompt, 'linked selected public decision and prompt evidence');
  evaluate('JSON.stringify((()=>{window.__artifactDownload={items:[],url:URL.createObjectURL.bind(URL),click:HTMLAnchorElement.prototype.click};URL.createObjectURL=blob=>{const href=window.__artifactDownload.url(blob);const item={href,size:blob.size};item.ready=blob.arrayBuffer().then(async b=>{item.bytes=b.byteLength;item.hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",b))].map(x=>x.toString(16).padStart(2,"0")).join("")});window.__artifactDownload.items.push(item);return href};HTMLAnchorElement.prototype.click=function(){const item=window.__artifactDownload.items.find(x=>x.href===this.href);if(item)item.filename=this.download};return true})())');
  click('.artifact-block button', 'DOWNLOAD');
  const downloadedArtifact = await waitFor('JSON.stringify((()=>{const item=window.__artifactDownload?.items?.[0];return item?{hash:item.hash,bytes:item.bytes,size:item.size,filename:item.filename}:null})())',
    (value) => typeof value?.hash === 'string', 'browser-generated exact prompt download');
  record('visible-prompt-download-matches-api-sha256', downloadedArtifact.hash === promptHash && downloadedArtifact.bytes === downloadedArtifact.size && downloadedArtifact.size > 0,
    { ...downloadedArtifact, expected_sha256: promptHash });
  evaluate('JSON.stringify((()=>{URL.createObjectURL=window.__artifactDownload.url;HTMLAnchorElement.prototype.click=window.__artifactDownload.click;delete window.__artifactDownload;return true})())');

  // Model page public evidence disclosures and responsive geometry.
  const modelRoute = `/simulation/${baseline.id}/models/${modelIds.Atlas}`;
  open(modelRoute);
  await waitFor('JSON.stringify({h1:document.querySelector("main h1")?.innerText,positions:document.body.innerText.includes("No open position rows"),fills:!!document.querySelector(".md-fill-table")})',
    (value) => value.h1?.toUpperCase().includes('ATLAS') && value.positions && value.fills, 'actual model account page');
  const layout = [];
  for (const [width, height] of widths) {
    axi('resize', String(width), String(height));
    const measurement = evaluate('JSON.stringify((()=>{const grid=document.querySelector(".md-position-grid");const cards=[...(grid?.children??[])];const xs=[...new Set(cards.map(e=>Math.round(e.getBoundingClientRect().left)))];const nav=[...document.querySelectorAll("header nav a")].map(a=>({label:a.textContent.trim(),visible:!!(a.offsetWidth||a.offsetHeight||a.getClientRects().length),right:a.getBoundingClientRect().right}));const body=document.body.scrollWidth,doc=document.documentElement.scrollWidth;const table=document.querySelector(".md-table-scroll,.md-fill-table")?.closest(".md-table-scroll");const t=table?.getBoundingClientRect();return {width:innerWidth,height:innerHeight,body,doc,positionColumns:xs.length,navigation:nav,table:table?{client:table.clientWidth,scroll:table.scrollWidth,clientRight:t.right}:null,fonts:document.fonts.status}})())');
    // The production replay has no active positions, so position-grid columns are tested below
    // with explicitly labeled browser-only component fixtures.
    const cssColumns = evaluate('JSON.stringify((()=>{const e=document.querySelector(".md-position-grid");return e?getComputedStyle(e).gridTemplateColumns.split(" ").length:null})())');
    measurement.positionGridColumns = cssColumns;
    layout.push(measurement);
    record(`model-${width}x${height}-no-page-overflow-and-live-navigation`, measurement.doc <= width + 1 && measurement.body <= width + 1 && measurement.navigation.some((link) => link.label === 'LIVE' && link.visible && link.right <= width + 1) && measurement.fonts === 'loaded', measurement);
    if (width === 390) record('mobile-wide-fill-table-scrolls-inside-its-container', !!measurement.table && measurement.table.clientRight <= width + 1 && measurement.table.scroll > measurement.table.client, measurement.table);
  }

  const disclosureAudit = [];
  for (const label of ['ACCOUNT EQUITY CHART', 'COMPLETE FILL HISTORY', 'POSITION AND FUNDING HISTORY', 'DECISIONS AND ARTIFACTS', 'PUBLIC MODEL SETTINGS AND AUDIT REFERENCES', 'DATA AVAILABILITY AND METRIC DEFINITIONS']) {
    const found = evaluate(`JSON.stringify((()=>{const s=[...document.querySelectorAll("details.md-disclosure > summary")].find(e=>e.textContent.includes(${JSON.stringify(label)}));if(s&&!s.parentElement.open)s.click();return !!s})())`);
    disclosureAudit.push({ label, found });
  }
  const availability = evaluate('JSON.stringify({text:document.querySelector(".md-method-notes")?.textContent ?? "",prompt:document.body.textContent.includes("USER_PROMPT"),trading:document.body.textContent.includes("TRADING_DECISIONS"),fills:[...document.querySelectorAll(".md-fill-table tbody tr")].map(e=>({round:Number(e.querySelector("td small")?.textContent.match(/R(\\d+)/)?.[1]??0),side:e.querySelector("td span")?.textContent.trim(),tone:[...e.querySelector("td span")?.classList??[]].find(c=>c.startsWith("md-fill-"))})),cards:document.querySelectorAll(".md-position-card").length,openEmpty:document.body.textContent.includes("No open position rows")})');
  record('model-public-record-disclosures-and-limits', disclosureAudit.every((x) => x.found) && availability.openEmpty && availability.cards === 0 && availability.fills.length > 0, {
    disclosures: disclosureAudit, prompt_or_trading_decisions_labels_present: availability.prompt || availability.trading,
    fills: availability.fills, actual_open_position_cards: availability.cards, empty_state: availability.openEmpty,
    unavailable_metrics: availability.text,
  });
  const newestFirstExpected = [...atlasTrades.items].reverse();
  const orderedAndColored = availability.fills.length === newestFirstExpected.length && availability.fills.every((row, index) => {
    const source = newestFirstExpected[index];
    const expectedTone = source?.side?.toUpperCase() === 'LONG' || source?.side?.toUpperCase() === 'BUY' ? 'md-fill-buy' : 'md-fill-sell';
    return source && row.round === Number(source.round) && row.side.toUpperCase() === source.side.toUpperCase() && row.tone === expectedTone;
  });
  record('model-fill-rows-are-newest-first-with-side-colors', orderedAndColored, {
    api_rounds_oldest_to_newest: atlasTrades.items.map((trade) => trade.round),
    visible_rounds_newest_to_oldest: availability.fills.map((trade) => trade.round),
    visible_sides_and_colors: availability.fills.map(({ side, tone }) => ({ side, tone })),
  });
  const chartRangeControl = evaluate('JSON.stringify({controls:[...document.querySelectorAll(".range-control button")].map(e=>e.textContent.trim()),selected:document.querySelector(".range-control [aria-pressed=true]")?.textContent.trim(),lines:document.querySelectorAll(".md-chart-section .equity-line").length})');
  const rangeButton = chartRangeControl.controls.includes('72H') && click('.range-control button', '72H');
  const modelChartRange = await waitFor('JSON.stringify({selected:document.querySelector(".range-control [aria-pressed=true]")?.textContent.trim(),lines:document.querySelectorAll(".md-chart-section .equity-line").length})',
    (value) => value.selected === '72H' && value.lines === 1, 'model equity chart range control');
  record('model-equity-chart-range-control-works', !!rangeButton && modelChartRange.selected === '72H', { before: chartRangeControl, after: modelChartRange });

  // Render the real position card in a clearly labeled, temporary browser-only fixture.
  // It is removed before captures and never represents a backend or paper-trading result.
  evaluate('JSON.stringify((()=>{window.__positionFixture={status:"loading"};const assets=performance.getEntriesByType("resource").map(e=>e.name);const reactAsset=new URL(assets.find(x=>x.includes("/node_modules/.vite/deps/react.js?")));const domAsset=new URL(assets.find(x=>x.includes("/node_modules/.vite/deps/react-dom_client.js?")));Promise.all([import("/src/simulation/model-detail.tsx"),import(reactAsset.pathname+reactAsset.search),import(domAsset.pathname+domAsset.search)]).then(([module,reactModule,domModule])=>{const React=reactModule.default,ReactDOM=domModule.default;const host=document.createElement("section");host.dataset.expandedValidationFixture="true";host.style.cssText="position:fixed;z-index:99999;top:100px;left:50%;transform:translateX(-50%);width:min(1216px,calc(100vw - 32px));max-height:80vh;overflow:auto;background:white;border:3px solid #8b1e1e;padding:12px";const label=document.createElement("strong");label.textContent="TEST FIXTURE · synthetic component check only · no reported result";const mount=document.createElement("div");mount.className="md-position-grid";mount.dataset.cardMount="";host.append(label,mount);document.body.append(host);window.__positionFixture.root=ReactDOM.createRoot(mount);const position={id:"synthetic-ui-check",competition_id:"synthetic-ui-check",agent_id:"synthetic-ui-check",agent_name:"TEST FIXTURE",symbol:"TEST-ONLY",side:"LONG",quantity:"2",average_entry:"100",reserved_margin:"20",stop_loss:"95",take_profit:"110",state:"OPEN",opened_at:"2026-10-16T00:00:00Z",closed_at:null};window.__positionFixture.root.render(React.createElement(React.Fragment,null,...[0,1,2].map(i=>React.createElement(module.PositionCard,{key:i,position:{...position,id:`synthetic-ui-check-${i}`,symbol:`TEST-ONLY-${i}`}}))));window.__positionFixture.status="ready"}).catch(e=>window.__positionFixture={status:"error",message:String(e)});return true})())');
  const positionFixture = await waitFor('JSON.stringify(window.__positionFixture&&{status:window.__positionFixture.status,message:window.__positionFixture.message,title:document.querySelector("[data-expanded-validation-fixture]")?.innerText.slice(0,90),card:document.querySelector("[data-expanded-validation-fixture] .md-position-card")?.innerText})', (value) => value?.status !== 'loading', 'synthetic position card fixture render');
  if (positionFixture.status === 'error') throw new Error(`PositionCard fixture render failed: ${positionFixture.message}`);
  const exitPlan = evaluate('JSON.stringify((()=>{const fixture=document.querySelector("[data-expanded-validation-fixture]");const summary=fixture?.querySelector(".md-exit-plan summary");if(summary)summary.click();const fields=fixture?.querySelector(".md-position-card .md-position-fields");return {fixtureLabel:fixture?.innerText.includes("synthetic component check only"),details:fixture?.querySelector(".md-exit-plan details")?.open,stop:fixture?.innerText.includes("$95.00"),target:fixture?.innerText.includes("$110.00"),naFields:[...fields?.querySelectorAll(":scope > div")??[]].filter(e=>e.innerText.includes("N/A")).length,card:!!fixture?.querySelector(".md-position-card")}})())');
  record('synthetic-position-card-exit-plan-and-unavailable-fields', exitPlan.fixtureLabel && exitPlan.details && exitPlan.stop && exitPlan.target && exitPlan.naFields === 3 && exitPlan.card, exitPlan);
  const positionGridBreakpoints = [];
  for (const [width, height] of widths) {
    axi('resize', String(width), String(height));
    const grid = evaluate('JSON.stringify((()=>{const e=document.querySelector("[data-expanded-validation-fixture] .md-position-grid");return {width:innerWidth,columns:getComputedStyle(e).gridTemplateColumns.split(" ").length,cardCount:e.children.length,cardLefts:[...new Set([...e.children].map(c=>Math.round(c.getBoundingClientRect().left)))]}})())');
    positionGridBreakpoints.push({ width, columns: grid.columns, cardCount: grid.cardCount });
    const expected = width > 760 ? 3 : width > 480 ? 2 : 1;
    record(`synthetic-position-grid-${width}x${height}-expected-columns`, grid.columns === expected && grid.cardCount === 3 && grid.cardLefts.length === expected, grid);
  }
  record('synthetic-position-grid-responsive-3-2-1', positionGridBreakpoints.map((item) => item.columns).join(',') === '3,3,3,3,2,1', { breakpoints: positionGridBreakpoints });
  evaluate('JSON.stringify((()=>{window.__positionFixture.root.unmount();document.querySelector("[data-expanded-validation-fixture]")?.remove();delete window.__positionFixture;return true})())');
  open(modelRoute);
  await waitFor('JSON.stringify({path:location.pathname,fills:!!document.querySelector(".md-fill-table")})', (value) => value.path === modelRoute && value.fills, 'model page before mobile capture');
  axi('resize', '390', '844');
  const modelMobile = 'expanded-simulation-model-mobile-390x844.png';
  axi('screenshot', path.join('docs/screenshots', modelMobile));
  layoutScreenshots.push(modelMobile);

  const invalidModelRoute = `/simulation/${baseline.id}/models/00000000-0000-4000-8000-000000000000`;
  open(invalidModelRoute);
  const invalidModel = await waitFor('JSON.stringify({url:location.pathname,body:document.body.innerText})',
    (value) => value.url === invalidModelRoute && /not present|not found|unavailable|could not/i.test(value.body), 'invalid model ID state');
  record('invalid-model-id-is-explained', true, { path: invalidModel.url, excerpt: invalidModel.body.slice(0, 260) });
  if (emptyFixture?.agents[0]?.id) {
    const mismatchRoute = `/simulation/${baseline.id}/models/${emptyFixture.agents[0].id}`;
    open(mismatchRoute);
    const mismatch = await waitFor('JSON.stringify({path:location.pathname,message:document.querySelector(".md-state[role=alert]")?.textContent.trim()})',
      (value) => value.path === mismatchRoute && value.message?.includes('do not match'), 'valid model ID with a different competition');
    record('model-competition-mismatch-is-explained', true, { path: mismatch.path, message: mismatch.message });
  }

  // Confirm average mode still keeps wide advanced metrics inside a local scroll area on phones.
  open(`/simulation/${baseline.id}/leaderboard`);
  await waitFor('JSON.stringify({rows:document.querySelectorAll("#lb-panel-overall .lb-table:not(.lb-detail-table) tbody tr").length,average:!!document.querySelector(".lb-average input")})',
    (value) => value.rows === 2 && value.average, 'leaderboard for average mobile regression');
  evaluate('JSON.stringify((()=>{document.querySelector(".lb-average input").click();return true})())');
  click('[role="tab"]', 'ADVANCED ANALYTICS');
  await waitFor('JSON.stringify(document.querySelector("[role=tab][aria-selected=true]")?.textContent.trim())', (value) => value === 'ADVANCED ANALYTICS', 'average advanced table for mobile regression');
  axi('resize', '390', '844');
  const averageMobileTable = await waitFor('JSON.stringify((()=>{const wrap=document.querySelector("#lb-panel-advanced .lb-table-wrap");const rect=wrap?.getBoundingClientRect();return {documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,client:wrap?.clientWidth,scroll:wrap?.scrollWidth,right:rect?.right,columns:wrap?.querySelector("table:not(.lb-detail-table) tbody tr")?.children.length}})())',
    (value) => value.columns === 13, 'average advanced mobile table');
  record('leaderboard-average-mobile-table-scrolls-locally', averageMobileTable.documentWidth <= 391 && averageMobileTable.bodyWidth <= 391 && averageMobileTable.scroll > averageMobileTable.client && averageMobileTable.right <= 391, averageMobileTable);
  const averageMobileScreenshot = 'expanded-simulation-leaderboard-mobile-390x844.png';
  axi('screenshot', path.join('docs/screenshots', averageMobileScreenshot));

  const network = axi('network');
  const output = {
    generated_at: new Date().toISOString(), api_base: api.origin, web_base: web.origin,
    session, baseline: { id: baseline.id, name: baseline.name, source_label: baseline.source_label, state: baseline.state, model_ids: modelIds, decisions: decisions.total, atlas_fill_rows: atlasTrades.total, atlas_open_positions: atlasPositions.total },
    source_directory: sourceDir, reference_screenshots: screenshots, reference_typography: sourceTypography,
    layout_screenshots: layoutScreenshots, responsive_model_layout: layout, responsive_live_layout: liveLayouts,
    responsive_leaderboard_layout: leaderboardLayouts, synthetic_position_grid: positionGridBreakpoints,
    network_summary: network.slice(0, 4000), checks, passed: checks.filter((item) => item.passed).length, failed: checks.filter((item) => !item.passed).length,
  };
  await writeFile(evidenceFile, `${JSON.stringify(output, null, 2)}\n`);
  console.log(JSON.stringify({ evidence: evidenceFile, passed: output.passed, failed: output.failed, screenshot_count: screenshots.length }, null, 2));
  if (output.failed) process.exitCode = 1;
}

main().catch(async (error) => {
  const partial = { generated_at: new Date().toISOString(), error: String(error?.stack ?? error), checks, screenshot_count: checks.find((item) => item.name === 'nine-reference-states-captured')?.screenshots?.length ?? null };
  await mkdir(path.dirname(evidenceFile), { recursive: true });
  await writeFile(evidenceFile, `${JSON.stringify(partial, null, 2)}\n`);
  console.error(error);
  process.exitCode = 1;
}).finally(() => {
  if (started) {
    try { axi('stop'); } catch (error) { console.error(`Could not stop named browser session ${session}: ${error.message}`); }
  }
});
