#!/usr/bin/env node
import { spawnSync } from 'node:child_process';

const [inputUrl] = process.argv.slice(2);
if (!inputUrl) throw new Error('Usage: node scripts/check-landing-resize.mjs <http(s)-url>');
const url = new URL(inputUrl);
if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Provide an http(s) URL without credentials.');
const session = `landing-resize-${process.pid}`;
const binary = process.env.CHROME_DEVTOOLS_AXI_BIN || 'chrome-devtools-axi';
function browser(args) {
  const result = spawnSync(binary, args, {
    encoding: 'utf8', timeout: 30_000, maxBuffer: 16 * 1024 * 1024,
    env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
  });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || result.stdout);
  return result.stdout;
}
function evaluate(expression) {
  const line = browser(['eval', expression, '--full']).split('\n').find((item) => item.startsWith('result: '));
  if (!line) throw new Error('Browser returned no evaluation result.');
  const result = JSON.parse(line.slice(8));
  return typeof result === 'string' ? JSON.parse(result) : result;
}

const helpers = `
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const scene = () => ({ ...document.querySelector('.scene-canvas').dataset });
  const wrap = () => document.querySelector('.chart-wrap');
  const chart = () => document.querySelector('[data-stage="2"]');
  const state = () => ({ ...scene(), landed: wrap().classList.contains('is-chart-landed'), split: Number(wrap().style.getPropertyValue('--chart-split')), splitting: chart().getAttribute('data-signal-mass-splitting') });
  const trigger = (stage) => { const element = document.querySelector('[data-stage="' + stage + '"]'); return element.getBoundingClientRect().top + scrollY - innerHeight * (stage === 1 ? .65 : .8); };
  const idle = async () => { await wait(120); for (let i = 0; i < 200 && scene().direction !== 'idle'; i += 1) await wait(20); await wait(1400); };
  const reachGrid = async () => { scrollTo(0, 0); await idle(); scrollTo(0, trigger(1) + 30); await idle(); };
`;
const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok, detail });
  process.stdout.write(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ` ${JSON.stringify(detail)}`}\n`);
}

try {
  browser(['open', url.href]);
  browser(['resize', '1363', '936']);
  evaluate('async () => { await document.fonts.ready; return true; }');

  const flight = evaluate(`async () => { ${helpers}
    await reachGrid();
    const landedHistory = [];
    const observer = new MutationObserver(() => landedHistory.push(chart().getAttribute('data-signal-mass-landed')));
    observer.observe(chart(), { attributes: true, attributeFilter: ['data-signal-mass-landed'] });
    scrollTo(0, trigger(2) + 30);
    await wait(150);
    const before = state();
    dispatchEvent(new Event('resize'));
    const after = state();
    await idle();
    observer.disconnect();
    return { before, after, landedHistory, final: state() };
  }`);
  check('resize during selected->chart flight keeps the directed leg', flight.before.direction === 'forward' && flight.after.direction === 'forward'
    && flight.after.activeStage === '1' && flight.after.targetStage === '2', flight);
  check('resize during selected->chart flight does not mark the chart landed', !flight.after.landed && flight.after.split === 0, flight);
  check('chart lands once, without a landed->unlanded flicker', flight.final.landed && flight.landedHistory.lastIndexOf('false') < flight.landedHistory.indexOf('true'), flight);

  const splitting = evaluate(`async () => { ${helpers}
    await reachGrid();
    scrollTo(0, trigger(2) + 30);
    await wait(120);
    for (let i = 0; i < 200 && scene().direction !== 'idle'; i += 1) await wait(10);
    await wait(700);
    const before = state();
    dispatchEvent(new Event('resize'));
    const after = state();
    await wait(1200);
    return { before, after, final: state() };
  }`);
  check('resize during splitting keeps the split clock running', splitting.before.splitting === 'true' && splitting.after.splitting === 'true'
    && !splitting.after.landed && splitting.after.split < 1, splitting);
  check('split completes after resize', splitting.final.landed && splitting.final.split === 1, splitting);

  const reflow = evaluate(`async () => { ${helpers}
    document.documentElement.style.overflowAnchor = 'none';
    const hero = document.querySelector('.hero');
    await reachGrid();
    scrollTo(0, trigger(2) + 20); await idle();
    const settled = state();
    hero.style.paddingBottom = '120px';
    await wait(400);
    const shifted = { state: state(), behindReadingLine: scrollY < trigger(2) };
    hero.style.paddingBottom = '';
    await wait(400);
    await reachGrid();
    const landedHistory = [];
    const observer = new MutationObserver(() => landedHistory.push(chart().getAttribute('data-signal-mass-landed')));
    observer.observe(chart(), { attributes: true, attributeFilter: ['data-signal-mass-landed'] });
    scrollTo(0, trigger(2) + 20);
    await wait(150);
    const flying = state();
    hero.style.paddingBottom = '120px';
    await wait(50);
    const interrupted = state();
    await idle();
    observer.disconnect();
    const final = state();
    hero.style.paddingBottom = '';
    document.documentElement.style.overflowAnchor = '';
    return { settled, shifted, flying, interrupted, final, landedHistory };
  }`);
  check('same-width anchor reflow re-derives the settled stage', reflow.settled.targetStage === '2' && reflow.shifted.behindReadingLine
    && reflow.shifted.state.targetStage === '1' && reflow.shifted.state.direction === 'idle' && !reflow.shifted.state.landed, reflow);
  check('same-width reflow during an incoherent flight settles once without landing the chart', reflow.flying.direction === 'forward'
    && reflow.interrupted.direction === 'idle' && reflow.interrupted.targetStage === '1' && reflow.final.targetStage === '1'
    && !reflow.final.landed && !reflow.landedHistory.includes('true'), reflow);

  browser(['resize', '1363', '1000']);
  const tall = evaluate(`async () => { ${helpers}
    await wait(400); await reachGrid();
    scrollTo(0, trigger(2) + 20); await idle();
    return { settled: state(), innerWidth, innerHeight };
  }`);
  browser(['resize', '1363', '960']);
  const short = evaluate(`async () => { ${helpers}
    await wait(400);
    return { state: state(), behindReadingLine: scrollY < trigger(2), innerWidth, innerHeight };
  }`);
  check('viewport-height-only resize with unchanged anchors keeps the settled stage (hysteresis)', tall.settled.targetStage === '2' && short.behindReadingLine
    && short.state.targetStage === '2' && short.state.direction === 'idle' && short.state.landed, { tall, short });

  browser(['resize', '390', '844']);
  evaluate(`async () => { ${helpers} await wait(400); await reachGrid(); scrollTo(0, trigger(2) + 20); await idle(); return true; }`);
  browser(['resize', '844', '390']);
  const rotated = evaluate(`async () => { ${helpers}
    await wait(400);
    let expected = 0; while (expected < 4 && scrollY >= trigger(expected + 1)) expected += 1;
    return { state: state(), expected: String(expected), innerWidth, innerHeight };
  }`);
  check('width/orientation change re-derives a coherent idle stage', rotated.state.targetStage === rotated.expected && rotated.state.activeStage === rotated.expected
    && rotated.state.direction === 'idle' && rotated.state.landed === (Number(rotated.expected) >= 2), rotated);
} finally {
  browser(['stop']);
}
if (checks.some((item) => !item.ok)) process.exit(1);
