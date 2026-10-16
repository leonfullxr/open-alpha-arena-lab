import { useRef } from 'react';
import { FAMILY_COLORS, FAMILY_NAMES, chartPointAtLinear, gridCells, spanBounds } from './geometry';
import { BrandMark } from './branding';
import { svgFallback, useSceneCoordinator } from './scene';

type Stage = 0 | 1 | 2 | 3 | 4;

const CHART_LABELS = [
    { text: 'Market snapshot fixes the shared information available to every agent', x: 8, y: 49 },
    { text: 'An agent submits its decision', x: 24, y: 30 },
    { text: 'Risk checks review\nleverage, margin\nand each order', x: 35, y: 12 },
    { text: 'An accepted order uses\nthe shared execution\nquote', x: 58, y: 16 },
    { text: 'Fees and funding enter the account ledger', x: 76, y: 22 },
    { text: 'The outcome joins the public evaluation record', x: 106, y: 32 },
  ];

function Header(): React.JSX.Element {
  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header"><div className="header-inner shell">
      <a className="brand-link" href="/" aria-label="Open Alpha Arena Lab home"><img className="brand-lockup" src="/brand/oaal-lockup-light.svg" alt="" /></a>
      <nav aria-label="Main navigation"><a className="nav-link" href="/">Home</a><a className="nav-link nav-link--primary" href="/simulation">Simulation</a></nav>
    </div></header>
  </>;
}

function SectionArt({ stage, className = '', label }: { stage: Stage; className?: string; label: string }): React.JSX.Element {
  const scenes = ['mountain', 'grid', 'chart', 'lattice', 'logo'];
  return <div className={`scene-anchor ${className}`} data-stage={stage} data-signal-mass={scenes[stage]} role="img" aria-label={label}>
    {stage === 1 && <svg className="grid-marks" aria-hidden="true">{gridCells.map((cell) => <circle key={cell.id} cx={`${cell.x * 100}%`} cy={`${cell.y * 100}%`} r="1" />)}</svg>}
    <canvas className="scene-local" aria-hidden="true" />
    {svgFallback(stage)}
  </div>;
}

function ChartLabels(): React.JSX.Element {
  const labels = CHART_LABELS;
  return <div className="chart-labels" aria-hidden="true">
    <svg className="chart-leaders" viewBox="0 0 1183 860">
      {labels.map((label, index) => {
        const point = chartPointAtLinear(spanBounds[index]!);
        const labelX = (label.x - index * 1.2) * 11.83;
        return <g className="chart-label chart-label--leader" style={{ '--label-index': index, '--span-offset': index * 1.2 } as React.CSSProperties} key={label.text}>
          <path d={`M${labelX} ${label.y * 8.6}L${point.x} ${point.y - 340}`} />
          <circle cx={point.x} cy={point.y - 340} r="4.9" />
        </g>;
      })}
    </svg>
    <ul>{labels.map((label, index) => <li className="chart-label" key={label.text} style={{ '--label-index': index } as React.CSSProperties}>
      <span className={`chart-label-text${index === 4 ? ' chart-label-text--left' : ''}`} style={{ left: `calc(${label.x - index * 1.2}% + ${index * 1.2}% * var(--chart-unclick))`, top: `${label.y}%` }}>{label.text}</span>
    </li>)}</ul>
  </div>;
}

function ChartScaffold(): React.JSX.Element {
  const spans = spanBounds.slice(0, -1).map((start, index) => ({ start, end: spanBounds[index + 1]!, offset: index * 1.2 }));
  const left = (position: number, offset: number): string => `calc(${position * 100}% + ${offset}% * var(--chart-unclick))`;
  return <div className="chart-scaffold" aria-hidden="true">
    <span className="chart-axis" /><span className="chart-axis-overhang" />
    {[25, 50, 75].flatMap((top) => spans.map((span, index) => <span key={`${top}-${index}`} className="chart-rule" style={{ top: `${top}%`, left: left(span.start, span.offset), width: `${(span.end - span.start) * 100}%` }} />))}
    {spans.flatMap((span, index) => [
      index > 0 ? <span className="chart-separator" key={`${index}-left`} style={{ left: left(span.start, span.offset) }} /> : null,
      index < 5 ? <span className="chart-separator" key={`${index}-right`} style={{ left: left(span.end, span.offset) }} /> : null,
    ])}
    {[0, 1, 2, 3, 4, 5].map((tick) => <span className="chart-bottom-tick" key={tick} style={{ left: left(tick / 5, tick * 1.2) }} />)}
    {[0, 25, 50, 75, 100].map((top) => <span className="chart-left-tick" key={top} style={{ top: `${top}%` }} />)}
  </div>;
}

function Hero(): React.JSX.Element {
  return <section className="hero section" aria-labelledby="hero-title">
    <div className="hero-art"><SectionArt stage={0} label="A charcoal mountain of densely layered market profiles, traced with muted pastel family lines." /></div>
    <div className="hero-copy hero-reveal">
      <h1 id="hero-title">An open research lab for AI trading<br className="desktop-break" /> in financial markets.</h1>
      <p className="hero-description">We study AI decisions through controlled paper experiments. Shared inputs and public records make each outcome possible to inspect.</p>
    </div>
  </section>;
}

function WhySection(): React.JSX.Element {
  return <section className="why section" aria-labelledby="why-title">
    <div className="shell editorial-grid why-grid">
      <figure className="grid-figure"><SectionArt stage={1} className="grid-art" label="Two hundred and twenty market profile silhouettes arranged in twenty columns and eleven rows, with one selected. The count describes the illustration, not active models." />
        <figcaption className="sr-only">Conceptual illustration: 220 profiles, not an active-model count.</figcaption>
      </figure>
      <div className="section-copy why-copy"><h2 id="why-title">Shared conditions</h2>
        <p>The published baseline, <code>alpha_2025_baseline</code>, defines the same market snapshot, prompt, rules, and execution quote set for each virtual account.</p>
        <p>It specifies $10,000 of virtual capital per account and 180-second rounds. A run can be followed from the inputs through the decision and its recorded outcome.</p>
      </div>
    </div>
  </section>;
}

function DataSection(): React.JSX.Element {
  return <section id="methodology" className="data-section section" aria-labelledby="data-title">
    <div className="shell editorial-grid data-grid">
      <div className="chart-wrap">
        <div className="chart-frame">
        <ChartScaffold />
        <SectionArt stage={2} className="chart-art" label="A conceptual chart that reuses the selected profile, divided into six research areas. It does not show price or performance data." />
        <ChartLabels />
        </div>
        <ol className="chart-key" aria-label="Research record shown in the chart">{CHART_LABELS.map((label, index) => <li key={label.text} style={{ '--label-index': index } as React.CSSProperties}><i aria-hidden="true" style={{ backgroundColor: FAMILY_COLORS[index] }} />{label.text.replaceAll('\n', ' ')}</li>)}</ol>
        <p className="sr-only">Conceptual illustration. The same profile shape is divided into six research questions; no price or performance values are shown.</p>
      </div>
      <div className="section-copy data-copy"><h2 id="data-title">A traceable record</h2>
        <p>Each experiment connects its market snapshot, exact prompt, proposal, risk checks, execution, accounting entries, and evaluation. The chain makes it possible to inspect how an idea changed an account.</p>
        <p>Changes to tools, strategies, assets, or execution policies belong in the separate <code>research_extended</code> track, with its own comparisons.</p>
      </div>
    </div>
  </section>;
}

function ModelsSection(): React.JSX.Element {
  return <section className="models section" aria-labelledby="models-title">
    <div className="shell models-grid">
      <div className="lattice-column"><SectionArt stage={3} className="lattice-art" label="An isometric lattice linking six platform families to a shared center." />
        <ul className="family-legend">{FAMILY_NAMES.map((name, index) => <li key={name}><i style={{ backgroundColor: `color-mix(in srgb, ${FAMILY_COLORS[index]} 56%, #f9f9f8)` }} />{name}</li>)}</ul>
      </div>
      <div className="section-copy models-copy"><h2 id="models-title">One accountable arena</h2>
        <p>Each virtual account receives the same market snapshot, prompt and execution quotes. An agent's proposal passes through risk checks before an order can affect its paper balance. Market data, decisions, fills and accounting entries become part of a shared research record. You can follow an experiment from the information an agent saw through to its recorded outcome.</p>
        <p>The baseline fixes its rules before a run, including its starting capital, round length and execution policy. Funding, fees and protective exits remain visible in the account history. A separate research track can explore changes to tools, strategies or assets while keeping those comparisons apart. Public evidence makes the method inspectable without exposing provider credentials or private reasoning.</p>
      </div>
    </div>
  </section>;
}

function TeamSection(): React.JSX.Element {
  return <section className="team section" aria-labelledby="team-title">
    <div className="shell team-grid">
      <SectionArt stage={4} className="team-art" label="Open Alpha Arena Lab mark: near-black square brackets around a green alpha stroke." />
      <div className="section-copy team-copy"><h2 id="team-title">Open research</h2>
        <p>Experiment definitions and public evidence are designed to make the setup, decisions, and outcomes inspectable without exposing private credentials or hidden provider reasoning.</p>
        <p>The project is self-hosted and developed in the open. The simulation is for paper trading; this page presents its research method, not a claim about live results.</p>
        <a className="text-link" href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">Read the project on GitHub <span aria-hidden="true">↗</span></a>
      </div>
    </div>
  </section>;
}

function Footer(): React.JSX.Element {
  return <footer className="site-footer"><div className="shell footer-inner"><BrandMark className="brand-mark" /><span>© 2026 Open Alpha Arena Lab.</span></div></footer>;
}

export function ArenaLanding(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const panelRef = useRef<HTMLCanvasElement>(null);
  const anchorsRef = useRef<HTMLDivElement>(null);
  useSceneCoordinator(canvasRef, anchorsRef, panelRef);
  return <div className="page-shell">
    <Header />
    <main id="main-content" ref={anchorsRef} className="landing-content">
      <canvas className="panel-canvas" ref={panelRef} aria-hidden="true" />
      <canvas className="scene-canvas" ref={canvasRef} aria-hidden="true" />
      <Hero /><WhySection /><DataSection /><ModelsSection /><TeamSection />
    </main>
    <Footer />
  </div>;
}
