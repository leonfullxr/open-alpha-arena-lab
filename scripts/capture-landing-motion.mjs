#!/usr/bin/env node
import { mkdirSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const [inputUrl, directory] = process.argv.slice(2);
if (!inputUrl || !directory) throw new Error('Usage: node scripts/capture-landing-motion.mjs <http(s)-url> <output-directory>');
const url = new URL(inputUrl);
if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Provide an http(s) URL without credentials.');
const output = path.resolve(directory);
mkdirSync(output, { recursive: true });
const session = `landing-motion-${process.pid}`;
const binary = process.env.CHROME_DEVTOOLS_AXI_BIN || 'chrome-devtools-axi';
function browser(args) {
  const result = spawnSync(binary, args, {
    encoding: 'utf8', timeout: 30_000, maxBuffer: 64 * 1024 * 1024,
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
const frames = [];
try {
  browser(['open', url.href]);
  browser(['resize', '1363', '936']);
  evaluate('async () => { await document.fonts.ready; scrollTo(0,0); return true; }');
  browser(['wait', '2400']);
  for (const destination of ['grid', 'chart', 'lattice', 'logo']) {
    const sampled = evaluate(`async () => {
      const element = document.querySelector('[data-signal-mass="${destination}"]');
      if (!element) throw new Error('Missing ${destination} anchor');
      const originalRAF = window.requestAnimationFrame;
      const deadlines = [0,100,200,300,450,600,900,1200,1800,2400];
      const frames = [];
      const started = performance.now();
      let lastPaint = started;
      const compose = (now) => {
        if (frames.length >= deadlines.length || now-started < deadlines[frames.length]) return;
        const bitmap = document.createElement('canvas');
        bitmap.width=innerWidth; bitmap.height=innerHeight;
        const context=bitmap.getContext('2d');
        context.fillStyle='#f9f9f8'; context.fillRect(0,0,innerWidth,innerHeight);
        const dark=document.querySelector('[data-signal-mass="lattice"]')?.closest('section')?.getBoundingClientRect();
        if(dark){context.fillStyle='#21201c';context.fillRect(0,dark.top,innerWidth,dark.height);}
        const canvases=[...document.querySelectorAll('canvas')];
        const global=canvases.filter(c=>c.classList.contains('panel-canvas')||c.classList.contains('scene-canvas'));
        for(const canvas of [...canvases.filter(c=>!global.includes(c)),...global]){
          const style=getComputedStyle(canvas),rect=canvas.getBoundingClientRect();
          if(style.display==='none'||style.visibility==='hidden'||!rect.width||!rect.height)continue;
          context.globalAlpha=Number(style.opacity);
          context.drawImage(canvas,rect.left,rect.top,rect.width,rect.height);
        }
        context.globalAlpha=1;
        frames.push({bitmap,nominalMs:deadlines[frames.length],elapsedMs:now-started,
          scrollY, scene:{...document.querySelector('.scene-canvas')?.dataset},
          annotationOpacities:[...document.querySelectorAll('.chart-labels li')].map(e=>getComputedStyle(e).opacity)});
      };
      window.requestAnimationFrame = callback => originalRAF.call(window, time => {
        callback(time);lastPaint=performance.now();compose(lastPaint);
      });
      const interval=setInterval(()=>{const now=performance.now();if(now-lastPaint>60)compose(now);},20);
      try {
        scrollTo(0,element.getBoundingClientRect().top+scrollY-innerHeight*${destination === 'grid' ? .65 : .8}+30);
        await new Promise(resolve=>setTimeout(resolve,2650));
        return frames.map(({bitmap,...metadata})=>({...metadata,png:bitmap.toDataURL('image/png').split(',')[1]}));
      } finally {clearInterval(interval);window.requestAnimationFrame=originalRAF;}
    }`);
    if (sampled.length !== 10) throw new Error('Missing timed illustration samples for '+destination);
    for (const {png,...metadata} of sampled) {
      const filename = `${destination}-${String(metadata.nominalMs).padStart(4, '0')}.png`;
      writeFileSync(path.join(output, filename), Buffer.from(png, 'base64'));
      frames.push({destination,...metadata,screenshot:filename});
    }
    process.stdout.write(`${JSON.stringify({ destination, frames: frames.length })}\n`);
  }
} finally {
  writeFileSync(path.join(output, 'motion-manifest.json'), JSON.stringify({
    url: url.href, generatedAt: new Date().toISOString(),
    note: 'Canvas illustration layers sampled inside actual animation callbacks, with idle timer samples after settlement. Text and DOM scaffolding are excluded; use the full-page capture tool for those. Actual elapsed times are recorded. Canvas copies add instrumentation overhead; this is not a calibrated frame-rate measurement. Scroll pauses after each trigger.',
    frames,
  }, null, 2) + '\n');
  browser(['stop']);
}
