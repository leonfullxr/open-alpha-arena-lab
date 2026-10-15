#!/usr/bin/env node

import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const usage = 'Usage: node scripts/capture-landing.mjs <http(s)-url> <output-directory>';
const waitMs = 4200;
const sections = [
  { name: 'hero', art: '[data-signal-mass="mountain"]', anchor: 'section' },
  { name: 'grid', art: '[data-signal-mass="grid"]', anchor: 'art', offset: 180 },
  { name: 'chart', art: '[data-signal-mass="chart"]', anchor: 'section', offset: 180 },
  { name: 'lattice', art: '[data-signal-mass="lattice"]', anchor: 'heading', offset: 120 },
  { name: 'team', art: '[data-signal-mass="logo"]', anchor: 'section', offset: 203 },
];

function fail(message) {
  throw new Error(message);
}

function parseArgs(args) {
  if (args.length !== 2 || !args[0] || !args[1]) fail(usage);

  let url;
  try {
    url = new URL(args[0]);
  } catch {
    fail(`Invalid URL. Provide a valid http(s) URL.\n${usage}`);
  }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) {
    fail('URL must be a valid http(s) URL without embedded credentials.');
  }

  return { url: url.href, outputDirectory: path.resolve(args[1]) };
}

function makeAxi(binary, session) {
  return (args) => {
    const result = spawnSync(binary, args, {
      encoding: 'utf8',
      env: { ...process.env, CHROME_DEVTOOLS_AXI_SESSION: session },
      timeout: 30_000,
      maxBuffer: 2 * 1024 * 1024,
    });

    if (result.error) fail(`Could not run ${binary}: ${result.error.message}`);
    if (result.status !== 0) {
      const detail = [result.stderr, result.stdout].filter(Boolean).join('\n').trim();
      fail(`${binary} ${args.join(' ')} failed${result.signal ? ` (${result.signal})` : ''}${detail ? `:\n${detail}` : '.'}`);
    }
    return result.stdout;
  };
}

function evaluate(runAxi, expression) {
  const output = runAxi(['eval', expression]);
  const line = output.split(/\r?\n/).find((entry) => entry.startsWith('result: '));
  if (!line) fail(`Browser evaluation returned no result:\n${output.trim()}`);

  try {
    const result = JSON.parse(line.slice('result: '.length));
    return typeof result === 'string' ? JSON.parse(result) : result;
  } catch (error) {
    fail(`Could not parse browser evaluation output: ${error.message}\n${output.trim()}`);
  }
}

function roundRect(rect) {
  if (!rect) return null;
  return Object.fromEntries(Object.entries(rect).map(([key, value]) => [key, Math.round(value * 10) / 10]));
}

function pageSnapshot(runAxi, art) {
  const expression = `() => {
    const art = document.querySelector(${JSON.stringify(art)});
    const section = art?.closest('section');
    const heading = section?.querySelector('h1, h2');
    const toRect = (element) => {
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, documentY: rect.top + window.scrollY };
    };
    return {
      url: location.href,
      viewport: { width: innerWidth, height: innerHeight },
      clientWidth: document.documentElement.clientWidth,
      scroll: { x: scrollX, y: scrollY },
      document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
      heading: heading?.innerText ?? null,
      font: heading ? getComputedStyle(heading).fontFamily : null,
      fontReady: document.fonts.check('450 44px Signifier'),
      renderer: document.querySelector('[data-renderer]')?.getAttribute('data-renderer') ?? 'not reported',
      section: toRect(section),
      art: toRect(art),
    };
  }`;
  const snapshot = evaluate(runAxi, expression);
  if (!snapshot.heading) fail(`Missing heading for ${art}`);
  if (!snapshot.section || snapshot.section.width <= 0 || snapshot.section.height <= 0) fail(`Missing or zero-sized section for ${art}`);
  if (!snapshot.art || snapshot.art.width <= 0 || snapshot.art.height <= 0) fail(`Missing or zero-sized art ${art}`);
  if (snapshot.document.width > snapshot.viewport.width) {
    fail(`Horizontal overflow at ${snapshot.viewport.width}x${snapshot.viewport.height}: document width ${snapshot.document.width}`);
  }
  return snapshot;
}

function positionFor(runAxi, target) {
  if (target.name === 'hero') {
    return evaluate(runAxi, '() => { window.scrollTo(0, 0); return { y: scrollY }; }').y;
  }
  const offset = target.offset ?? 0;
  const expression = `() => {
    const art = document.querySelector(${JSON.stringify(target.art)});
    const section = art?.closest('section');
    const element = ${JSON.stringify(target.anchor)} === 'heading' ? section?.querySelector('h1,h2') : ${JSON.stringify(target.anchor)} === 'art' ? art : section;
    if (!element) return { missing: true, selector: ${JSON.stringify(target.art)} };
    const desired = Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight, element.getBoundingClientRect().top + scrollY - ${offset}));
    window.scrollTo(0, desired);
    return { y: scrollY };
  }`;
  const result = evaluate(runAxi, expression);
  if (result.missing) fail(`Missing capture anchor ${result.selector}`);
  return result.y;
}

function capture(runAxi, outputDirectory, viewportName, expectedViewport, target) {
  positionFor(runAxi, target);
  runAxi(['wait', String(waitMs)]);

  const snapshot = pageSnapshot(runAxi, target.art);
  if (snapshot.viewport.width !== expectedViewport.width || snapshot.viewport.height !== expectedViewport.height) {
    fail(`Requested ${expectedViewport.width}x${expectedViewport.height}, browser reports ${snapshot.viewport.width}x${snapshot.viewport.height}`);
  }
  const screenshot = path.join(outputDirectory, `${viewportName}-${target.name}.png`);
  runAxi(['screenshot', screenshot]);
  let screenshotStat;
  try {
    screenshotStat = statSync(screenshot);
  } catch {
    fail(`Screenshot was not created: ${screenshot}`);
  }
  if (!screenshotStat.isFile() || screenshotStat.size === 0) fail(`Screenshot is empty or not a file: ${screenshot}`);

  return {
    name: `${viewportName}-${target.name}`,
    viewport: snapshot.viewport,
    clientWidth: snapshot.clientWidth,
    font: snapshot.font,
    fontReady: snapshot.fontReady,
    renderer: snapshot.renderer,
    scroll: snapshot.scroll,
    url: snapshot.url,
    heading: snapshot.heading,
    section: roundRect(snapshot.section),
    art: roundRect(snapshot.art),
    screenshot,
  };
}

function main() {
  const { url, outputDirectory } = parseArgs(process.argv.slice(2));
  mkdirSync(outputDirectory, { recursive: true });
  const binary = process.env.CHROME_DEVTOOLS_AXI_BIN || 'chrome-devtools-axi';
  const session = `landing-capture-${process.pid}`;
  const runAxi = makeAxi(binary, session);
  let sessionTouched = false;

  try {
    sessionTouched = true;
    runAxi(['open', url]);
    const captures = [];
    for (const [width, height] of [[1363, 936], [1440, 900], [1024, 768], [768, 1024], [390, 844]]) {
      runAxi(['resize', String(width), String(height)]);
      evaluate(runAxi, 'async () => { await document.fonts.ready; return { ready: true }; }');
      for (const section of sections) {
        const target = width < 1024 ? { ...section, anchor: section.name === 'hero' ? 'section' : 'art', offset: section.name === 'hero' ? 0 : 80 } : section;
        captures.push(capture(runAxi, outputDirectory, `${width}x${height}`, { width, height }, target));
      }
      process.stdout.write(`${JSON.stringify({ viewport: [width, height], screenshots: captures.length })}\n`);
    }

    const manifest = {
      sourceUrl: url,
      generatedAt: new Date().toISOString(),
      note: 'Geometry and content checks only; these captures do not establish visual fidelity.',
      captures,
    };
    const manifestPath = path.join(outputDirectory, 'manifest.json');
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify({ manifest: manifestPath, screenshots: captures.length }, null, 2)}\n`);
  } finally {
    if (sessionTouched) {
      try {
        runAxi(['stop']);
      } catch (error) {
        process.stderr.write(`Could not stop capture browser session ${session}: ${error.message}\n`);
      }
    }
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
