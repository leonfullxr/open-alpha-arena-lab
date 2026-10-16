#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const api = new URL(process.env.SIMULATION_API_BASE_URL ?? 'http://127.0.0.1:8026/api/v1/public');
const web = new URL(process.env.SIMULATION_BASE_URL ?? 'http://127.0.0.1:5186');
const session = process.env.CHROME_DEVTOOLS_AXI_SESSION ?? 'arena-exact-spec-tests';
const evidenceFile = path.resolve(root, process.env.SIMULATION_EXACT_EVIDENCE_FILE ?? 'docs/evidence/exact-terminal-spec-validation-2026-10-16.json');
const screenshotDir = path.join(root, 'docs/screenshots');
const checks = [];
let started = false;

function axi(...args) {
  return execFileSync('chrome-devtools-axi', args, {
    cwd: root,
    env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 120_000,
  });
}
function evaluate(expression) {
  const output = axi('eval', expression);
  if (/result was truncated|output truncated/i.test(output)) throw new Error('Browser evaluation returned truncated output');
  const line = output.split('\n').find((item) => item.startsWith('result: '));
  if (!line) throw new Error(`Browser evaluation returned no result: ${output}`);
  let value = JSON.parse(line.slice('result: '.length));
  for (let index = 0; index < 3 && typeof value === 'string'; index += 1) {
    try { value = JSON.parse(value); } catch { break; }
  }
  return value;
}
async function waitFor(expression, predicate, label, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  let latest;
  while (Date.now() < deadline) {
    latest = evaluate(expression);
    if (predicate(latest)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(latest)}`);
}
async function json(route) {
  const response = await fetch(new URL(route.replace(/^\//, ''), `${api.href.replace(/\/$/, '')}/`));
  if (!response.ok) throw new Error(`${route}: HTTP ${response.status}`);
  return response.json();
}
function check(name, passed, details = {}) { checks.push({ name, passed, ...details }); }
function open(route) { axi('open', new URL(route, web).href); }
function click(selector) { return evaluate(`JSON.stringify((()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return false;e.click();return true})())`); }
function screenshot(name) { axi('screenshot', path.join('docs/screenshots', name)); }

async function main() {
  await mkdir(path.dirname(evidenceFile), { recursive: true });
  await mkdir(screenshotDir, { recursive: true });
  const competitions = await json('/competitions');
  const baseline = competitions.find((item) => item.id === '036d6115-3edb-5dca-92d3-eb46a649a1b2');
  if (!baseline) throw new Error('The public baseline replay was not found');
  const [ticker, decisions] = await Promise.all([
    json(`/ticker?competition_id=${encodeURIComponent(baseline.id)}`),
    json(`/competitions/${baseline.id}/decisions?limit=200`),
  ]);
  const modelIds = { Atlas: 'ce388865-2dfe-5055-9173-2bbce70b24cc', Vector: '94cfdc45-adb3-5766-b2d1-bbd78ad49783' };
  if (baseline.state !== 'FINISHED' || baseline.agents.length !== 2) throw new Error('Baseline identity differs from the recorded two-model replay');

  const liveRoute = `/simulation?run=${baseline.id}`;
  open('/simulation');
  started = true;
  await waitFor('JSON.stringify({path:location.pathname,rail:!!document.querySelector(".arena-rail"),cards:document.querySelectorAll(".chat-card").length})',
    (value) => value.path === '/simulation' && value.rail && value.cards > 0, 'aggregate simulation index page');
  axi('resize', '1920', '1080');
  const shell = evaluate('JSON.stringify((()=>{const rect=s=>{const e=document.querySelector(s),r=e?.getBoundingClientRect();return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};const links=[...document.querySelectorAll(".arena-nav a")].map(a=>({text:a.textContent.trim(),href:a.getAttribute("href")}));const runs=[...document.querySelectorAll(".arena-run-tab")].map(a=>({text:a.textContent.trim(),href:a.getAttribute("href")}));const quotes=[...document.querySelectorAll(".ticker-cell b")].map(e=>e.textContent.trim());return {header:rect(".arena-head"),headRow:rect(".arena-head-row"),band:rect(".arena-band"),context:rect(".arena-context"),workspace:rect(".arena-workspace"),main:rect(".arena-main"),article:rect(".index-narrative"),rail:rect(".arena-rail"),railTabs:rect(".arena-rail-tabs"),links,runs,quotes,documentWidth:document.documentElement.scrollWidth,fonts:document.fonts.status}})())');
  const expectedNav = ['LIVE', 'LEADERBOARD', 'MODELS', 'BLOG', 'ABOUT'];
  const navOk = shell.links.map((item) => item.text).join(',') === expectedNav.join(',')
    && shell.links[3]?.href === '/#methodology'
    && shell.links[4]?.href === '/#methodology'
    && shell.links[1]?.href?.startsWith('/simulation/')
    && shell.links[2]?.href?.includes('/models/')
    && shell.documentWidth <= 1921;
  check('desktop-header-navigation-labels-and-targets', navOk, shell.links);
  check('desktop-header-band-context-and-rail-geometry', shell.headRow.height === 58 && shell.header.height === 58 && shell.band.height === 45
    && shell.context.y === 103 && shell.context.height === 32 && shell.article.width === 672
    && shell.rail.y === 103 && shell.railTabs.height === 32
    && shell.rail.width === 500, shell);
  const liveRunIds = shell.runs.filter((item) => item.href?.includes('?run=')).map((item) => item.href.split('?run=')[1]);
  check('run-band-uses-aggregate-index-and-numbered-public-runs', shell.runs[0]?.text === 'AGGREGATE INDEX'
    && liveRunIds.length === competitions.length && liveRunIds.includes(baseline.id)
    && shell.runs.slice(1).every((item, index) => item.text.startsWith(`${index + 1}:`)), { runs: shell.runs, api_run_count: competitions.length });
  const actualTickerSymbols = ticker.map((item) => item.symbol);
  check('run-band-market-ticker-uses-real-api-symbols', actualTickerSymbols.length > 0
    && actualTickerSymbols.every((symbol) => shell.quotes.includes(symbol)), { api_symbols: actualTickerSymbols, visible_symbols: shell.quotes });
  const theme = evaluate('JSON.stringify((()=>{const s=getComputedStyle(document.documentElement);return {paper:s.getPropertyValue("--paper").trim(),secondary:s.getPropertyValue("--secondary").trim(),panel:s.getPropertyValue("--panel").trim(),ink:s.getPropertyValue("--ink").trim(),muted:s.getPropertyValue("--muted").trim(),hairline:s.getPropertyValue("--hairline").trim(),positive:s.getPropertyValue("--positive").trim(),negative:s.getPropertyValue("--negative").trim(),link:s.getPropertyValue("--link").trim(),mono:s.fontFamily}})())');
  check('theme-tokens-and-static-mono-font', theme.paper === '#ffffff' && theme.secondary === '#f7f7f7'
    && theme.panel === '#f9fafb' && theme.ink === '#111111' && theme.muted === '#5b6470'
    && theme.hairline === '#d7dce2' && theme.positive === '#00bf00' && theme.negative === '#ff0000'
    && theme.link === '#3467ff' && /IBM Plex Mono/.test(theme.mono) && shell.fonts === 'loaded', theme);

  // Verify that actual API decisions supply the tinted evidence cards and downloads.
  const firstDecision = decisions.items.find((item) => item.proposals?.length > 0 && item.prompt_sha256);
  const card = firstDecision && evaluate(`JSON.stringify((()=>{const e=document.getElementById("run-decision-${firstDecision.id}")||document.querySelector(".chat-card");if(!e)return null;const bubble=e.querySelector(".chat-bubble");return {id:e.id,classes:e.className,background:getComputedStyle(bubble).backgroundColor,marker:getComputedStyle(e.querySelector(".chat-marker")).color,card:e.querySelector(".chat-head")?.textContent.trim()}})())`);
  check('actual-decision-card-has-model-tint', !!firstDecision && !!card?.id && /color\(srgb|rgb\(/.test(card.background) && card.marker !== 'rgb(0, 0, 0)', { decision_id: firstDecision?.id, card });
  if (card?.id) {
    click(`#${card.id} .chat-expand`);
    const evidence = await waitFor('JSON.stringify({prompt:document.body.textContent.includes("USER_PROMPT"),trading:document.body.textContent.includes("TRADING_DECISIONS"),download:!!document.querySelector(".artifact-block button"),hash:!!document.querySelector(".chat-hash")})',
      (value) => value.prompt && value.trading && value.download, 'actual decision prompt, proposal, and download');
    check('actual-decision-exposes-prompt-proposals-and-download', evidence.prompt && evidence.trading && evidence.download && evidence.hash, evidence);
  }
  screenshot('exact-terminal-live-1920x1080.png');

  open('/simulation');
  await waitFor('JSON.stringify({path:location.pathname,tab:document.querySelector("#rail-tab-chat")?.textContent.trim(),cards:document.querySelectorAll(".chat-card").length})',
    (value) => value.path === '/simulation' && value.tab === 'MODELCHAT' && value.cards > 0, 'aggregate rail labels');
  const aggregateTabs = evaluate('JSON.stringify([...document.querySelectorAll(".arena-rail-tabs button")].map(e=>({id:e.id,label:e.textContent.trim()})))');
  check('aggregate-index-rail-tabs-use-requested-labels', JSON.stringify(aggregateTabs) === JSON.stringify([{ id: 'rail-tab-chat', label: 'MODELCHAT' }, { id: 'rail-tab-details', label: 'SEASON DETAILS' }]), aggregateTabs);
  const ctaLink = evaluate('JSON.stringify((()=>{const a=document.querySelector(".index-narrative-cta a");return a?{text:a.textContent.trim(),color:getComputedStyle(a).color}:null})())');
  check('index-route-link-uses-bright-blue-token', ctaLink?.color === 'rgb(52, 103, 255)', ctaLink);
  click('#rail-tab-details');
  const season = await waitFor('JSON.stringify({selected:document.querySelector(".arena-rail-tabs [aria-selected=true]")?.id,runs:document.querySelectorAll(".season-run-card").length})', (value) => value.runs > 0, 'season details rail');
  check('season-details-selects-real-run-records', season.selected === 'rail-tab-details' && season.runs === competitions.length, season);
  const blog = shell.links.find((item) => item.text === 'BLOG');
  if (blog) {
    open(blog.href);
    await waitFor('JSON.stringify({path:location.pathname,hash:location.hash,target:!!document.querySelector("#methodology"),top:document.querySelector("#methodology")?.getBoundingClientRect().top})',
      (value) => value.path === '/' && value.hash === '#methodology' && value.target, 'BLOG methodology anchor');
    const anchor = evaluate('JSON.stringify({path:location.pathname,hash:location.hash,exists:!!document.querySelector("#methodology")})');
    check('blog-link-lands-on-existing-methodology-section', anchor.path === '/' && anchor.hash === '#methodology' && anchor.exists, anchor);
  }

  open(liveRoute);
  await waitFor('JSON.stringify({path:location.pathname,tabs:document.querySelectorAll(".arena-rail-tabs button").length})', (value) => value.path === '/simulation' && value.tabs === 4, 'run rail labels');
  const runTabs = evaluate('JSON.stringify([...document.querySelectorAll(".arena-rail-tabs button")].map(e=>({id:e.id,label:e.textContent.trim()})))');
  check('selected-run-rail-tabs-use-requested-labels', JSON.stringify(runTabs) === JSON.stringify([
    { id: 'rail-tab-fills', label: 'TRADES' }, { id: 'rail-tab-chat', label: 'MODELCHAT' },
    { id: 'rail-tab-positions', label: 'POSITIONS' }, { id: 'rail-tab-details', label: 'COMP DETAILS' },
  ]), runTabs);
  for (const [width, height] of [[1440, 900], [390, 844]]) {
    axi('resize', String(width), String(height));
    const mobile = evaluate('JSON.stringify((()=>{const nav=document.querySelector(".arena-nav"),r=nav.getBoundingClientRect(),head=document.querySelector(".arena-head-row").getBoundingClientRect(),band=document.querySelector(".arena-band").getBoundingClientRect(),context=document.querySelector(".arena-context").getBoundingClientRect();nav.scrollLeft=nav.scrollWidth;return {width:innerWidth,doc:document.documentElement.scrollWidth,nav:{x:r.x,right:r.right,client:nav.clientWidth,scroll:nav.scrollWidth,lastRight:nav.querySelectorAll("a")[4]?.getBoundingClientRect().right,links:[...nav.querySelectorAll("a")].map(a=>({text:a.textContent.trim(),href:a.getAttribute("href")}))},header:document.querySelector(".arena-head").getBoundingClientRect().height,head:head.height,band:band.height,context:{top:context.top,height:context.height},railTop:document.querySelector(".arena-rail").getBoundingClientRect().top}})())');
    const allLinks = mobile.nav.links.map((item) => item.text).join(',') === expectedNav.join(',');
    check(`live-${width}-no-overflow-and-five-navigation-links`, mobile.doc <= width + 1 && allLinks && mobile.nav.links.length === 5
      && mobile.head === 58 && (width !== 390 || (mobile.nav.scroll >= mobile.nav.client && mobile.nav.lastRight <= mobile.nav.right + 1)), mobile);
    check(`live-${width}-rail-stays-aligned-after-context`, width > 800
      ? Math.abs(mobile.railTop - mobile.context.top) <= 1
      : mobile.railTop >= mobile.context.top + mobile.context.height, mobile);
    if (width === 390) screenshot('exact-terminal-live-mobile-390x844.png');
  }

  const modelRoute = `/simulation/${baseline.id}/models/${modelIds.Atlas}`;
  open(modelRoute);
  await waitFor('JSON.stringify({path:location.pathname,h1:!!document.querySelector(".md-page h1"),fills:!!document.querySelector(".md-fill-table")})',
    (value) => value.path === modelRoute && value.h1 && value.fills, 'Atlas model page');
  axi('resize', '1920', '1080');
  const modelPage = evaluate('JSON.stringify((()=>{const box=s=>{const e=document.querySelector(s),r=e?.getBoundingClientRect();return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null};const links=[...document.querySelectorAll(".md-backlinks a")].map(e=>({text:e.textContent.trim(),height:e.getBoundingClientRect().height,href:e.getAttribute("href")}));const fills=document.querySelectorAll(".md-fill-table tbody tr").length;const summary=document.querySelector(".md-summary");return {page:box(".md-page"),links,summary:box(".md-summary"),summaryColumns:getComputedStyle(summary).gridTemplateColumns.split(" ").length,fillHeading:document.querySelector("#md-fills-title")?.textContent.trim(),fills,classes:document.querySelector(".md-page")?.className,modelName:document.querySelector(".md-identity h1")?.textContent.trim(),wideBody:getComputedStyle(document.querySelector(".arena-body")).backgroundColor,grain:getComputedStyle(document.querySelector(".arena")).backgroundImage}})())');
  const routeLinksOk = modelPage.links.length === 2 && modelPage.links.every((item) => item.height >= 42)
    && modelPage.links.some((item) => item.href.endsWith('/leaderboard'));
  check('model-page-1216-wide-90px-pnl-strip-and-three-columns', modelPage.page.width === 1216 && modelPage.summary.height === 90
    && modelPage.summaryColumns === 3 && routeLinksOk, modelPage);
  check('standalone-model-page-reveals-static-grain', modelPage.wideBody === 'rgba(0, 0, 0, 0)' && modelPage.grain.includes('data:image/svg+xml'), { wideBody: modelPage.wideBody, grain: modelPage.grain.slice(0, 80) });
  check('model-page-shows-the-last-25-fills', modelPage.fillHeading === 'LAST 25 FILLS' && modelPage.fills <= 25 && modelPage.fills > 0, modelPage);
  const colorProof = evaluate(`JSON.stringify((()=>{window.__colorProof={status:"loading"};const agents=${JSON.stringify(baseline.agents)};import("/src/simulation/colors.ts").then(m=>{const reversed=[...agents].reverse();const result=agents.map(a=>({name:a.name,provider:a.provider,model:a.model,id:a.id,color:m.modelColor(agents,a.id),reversed:m.modelColor(reversed,a.id),tone:m.modelToneClass(agents,a.id)}));window.__colorProof={status:"ready",result}}).catch(e=>window.__colorProof={status:"error",message:String(e)});return true})())`);
  if (!colorProof) throw new Error('Could not start named model color helper proof');
  const colors = await waitFor('JSON.stringify(window.__colorProof)', (value) => value?.status !== 'loading', 'named model color helper');
  if (colors.status === 'error') throw new Error(colors.message);
  check('atlas-vector-fallbacks-use-first-two-palette-slots', colors.result.length === 2
    && colors.result[0]?.color === '#3467ff' && colors.result[1]?.color === '#ec4899'
    && colors.result[0]?.tone === 'model-tone-0' && colors.result[1]?.tone === 'model-tone-1', colors.result);
  evaluate('JSON.stringify((()=>{window.__grokColorProof={status:"loading"};import("/src/simulation/colors.ts").then(m=>{const agents=[{id:"grok420",name:"Atlas",provider:"xAI",model:"Grok-4.20"},{id:"grok4",name:"Vector",provider:"xAI",model:"Grok-4"}];window.__grokColorProof={status:"ready",models:agents.map(a=>({model:a.model,color:m.modelColor(agents,a.id)}))}}).catch(e=>window.__grokColorProof={status:"error",message:String(e)});return true})())');
  const namedColorProof = evaluate('JSON.stringify((()=>{window.__namedColorProof={status:"loading"};import("/src/simulation/colors.ts").then(m=>{const expected={"GPT-5.1":"#00a98f",Qwen:"#8b5cf6",Kimi:"#168bff",DeepSeek:"#4f46e5",Gemini:"#3467ff",Claude:"#f97316","Grok-4.20":"#ec4899","Grok-4":"#111111"};const agents=Object.keys(expected).map((model,index)=>({id:String(index),name:model,provider:"Synthetic named test",model}));const reversed=[...agents].reverse();window.__namedColorProof={status:"ready",models:agents.map(a=>({model:a.model,expected:expected[a.model],color:m.modelColor(agents,a.id),reversed:m.modelColor(reversed,a.id)}))}}).catch(e=>window.__namedColorProof={status:"error",message:String(e)});return true})())');
  void namedColorProof;
  const namedColors = await waitFor('JSON.stringify(window.__namedColorProof)', (value) => value?.status !== 'loading', 'eight named model color mappings');
  check('named-model-palette-maps-all-eight-models-independent-of-order', namedColors.status === 'ready'
    && namedColors.models.length === 8 && namedColors.models.every((item) => item.color === item.expected && item.reversed === item.expected), namedColors);
  screenshot('exact-terminal-model-1920x1080.png');

  const leaderboardRoute = `/simulation/${baseline.id}/leaderboard`;
  open(leaderboardRoute);
  await waitFor('JSON.stringify({path:location.pathname,rows:document.querySelectorAll(".lb-overall-table tbody tr").length})',
    (value) => value.path === leaderboardRoute && value.rows === 2, 'baseline leaderboard');
  axi('resize', '1920', '1080');
  const leaderboard = evaluate('JSON.stringify((()=>{const page=document.querySelector(".leaderboard-page"),table=document.querySelector(".lb-overall-table"),head=table.querySelector("thead tr"),row=table.querySelector("tbody tr");const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}};const sort=table.querySelector("th[aria-sort]"),sortStyle=sort?getComputedStyle(sort):null;return {page:rect(page),heading:document.querySelector(".lb-title-block h1").getBoundingClientRect().height,headerHeight:rect(head).height,rowHeight:rect(row).height,table:rect(table),sort:sort?{text:sort.innerText.trim(),state:sort.getAttribute("aria-sort"),color:sortStyle.color,borderColor:sortStyle.borderRightColor}:null,modelColumn:rect(table.querySelector("thead th:nth-child(2)")),summary:document.querySelector(".lb-winner")?.innerText.trim(),winner:document.querySelector(".lb-winner-name a")?.getAttribute("href"),documentWidth:document.documentElement.scrollWidth,wideBody:getComputedStyle(document.querySelector(".arena-body")).backgroundColor,grain:getComputedStyle(document.querySelector(".arena")).backgroundImage}})())');
  check('leaderboard-1568-wide-heading-35-and-22px-rows', leaderboard.page.width === 1568 && leaderboard.page.x === 176
    && leaderboard.heading === 35 && leaderboard.rowHeight >= 22 && leaderboard.rowHeight <= 23
    && leaderboard.documentWidth <= 1921, leaderboard);
  check('leaderboard-black-dividers-default-equity-sort-and-summary', leaderboard.sort?.text.includes('ACCOUNT VALUE')
    && leaderboard.sort.state === 'descending' && /rgb\(\d+,\s*\d+,\s*\d+\)/.test(leaderboard.sort.borderColor)
    && leaderboard.summary?.includes('WINNING MODEL'), leaderboard);
  check('standalone-leaderboard-reveals-static-grain', leaderboard.wideBody === 'rgba(0, 0, 0, 0)' && leaderboard.grain.includes('data:image/svg+xml'), { wideBody: leaderboard.wideBody, grain: leaderboard.grain.slice(0, 80) });
  axi('resize', '1920', '720');
  axi('resize', '1920', '480');
  evaluate('JSON.stringify((()=>{window.scrollTo(0,600);const main=document.querySelector(".arena-main");if(main)main.scrollTop=600;return true})())');
  const sticky = await waitFor('JSON.stringify((()=>{const header=document.querySelector(".arena-head"),rect=header.getBoundingClientRect();return {scrollY:window.scrollY,top:rect.top,height:rect.height,position:getComputedStyle(header).position}})())',
    (value) => value.scrollY > 0, 'document scroll under sticky shared header');
  check('shared-navigation-header-remains-sticky-at-58px', sticky.position === 'sticky' && sticky.top <= 1 && sticky.height === 58, sticky);
  evaluate('JSON.stringify((()=>{window.scrollTo(0,0);const main=document.querySelector(".arena-main");if(main)main.scrollTop=0;return true})())');
  axi('resize', '1920', '1080');
  screenshot('exact-terminal-leaderboard-1920x1080.png');

  const network = axi('network');
  const failures = checks.filter((item) => !item.passed);
  const output = { generated_at: new Date().toISOString(), api_base: api.origin, web_base: web.origin, session,
    baseline: { id: baseline.id, state: baseline.state, models: baseline.agents.map(({ id, name, provider, model }) => ({ id, name, provider, model })), run_count: competitions.length, ticker_symbols: actualTickerSymbols, decisions: decisions.total },
    checks, passed: checks.length - failures.length, failed: failures.length, network_summary: network.slice(0, 4000) };
  await writeFile(evidenceFile, `${JSON.stringify(output, null, 2)}\n`);
  console.log(JSON.stringify({ evidence: evidenceFile, passed: output.passed, failed: output.failed }, null, 2));
  if (output.failed) process.exitCode = 1;
}

main().catch(async (error) => {
  const output = { generated_at: new Date().toISOString(), error: String(error?.stack ?? error), checks };
  await mkdir(path.dirname(evidenceFile), { recursive: true });
  await writeFile(evidenceFile, `${JSON.stringify(output, null, 2)}\n`);
  console.error(error);
  process.exitCode = 1;
}).finally(() => {
  if (started) {
    try { axi('stop'); } catch (error) { console.error(`Could not stop browser session ${session}: ${error.message}`); }
  }
});
