import { useRef } from 'react';
import { FAMILY_COLORS, FAMILY_NAMES } from './geometry';
import { svgFallback, useSceneCoordinator } from './scene';

type Stage = 0 | 1 | 2 | 3 | 4;

function BrandMark({ small = false }: { small?: boolean }): React.JSX.Element {
  return <span aria-hidden="true" className={small ? 'brand-mark brand-mark--small' : 'brand-mark'}>{Array.from({ length: 36 }, (_, index) => <i key={index} style={{ '--tile-color': FAMILY_COLORS[index % 6] } as React.CSSProperties} />)}</span>;
}

function Header(): React.JSX.Element {
  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header"><div className="header-inner shell">
      <a className="brand-link" href="/" aria-label="Open Alpha Arena Lab home"><BrandMark /></a>
      <nav aria-label="Main navigation"><a className="nav-link" href="/">Home</a><a className="nav-link nav-link--primary" href="/simulation">Simulation</a></nav>
    </div></header>
  </>;
}

function SectionArt({ stage, className = '', label }: { stage: Stage; className?: string; label: string }): React.JSX.Element {
  return <div className={`scene-anchor ${className}`} data-stage={stage} role="img" aria-label={label}>
    <canvas className="scene-local" aria-hidden="true" />
    {svgFallback(stage)}
  </div>;
}

function ChartLabels(): React.JSX.Element {
  const labels = [
    { text: ['Market', 'snapshot'], x: 145, y: 47, anchor: 180, end: 220 },
    { text: ['Prompt &', 'response'], x: 337, y: 151, anchor: 350, end: 300 },
    { text: ['Risk', 'checks'], x: 520, y: 47, anchor: 520, end: 250 },
    { text: ['Order', 'execution'], x: 705, y: 151, anchor: 705, end: 330 },
    { text: ['Account', 'ledger'], x: 890, y: 47, anchor: 890, end: 295 },
    { text: ['Evaluation', 'record'], x: 1064, y: 151, anchor: 1064, end: 400 },
  ];
  return <svg className="chart-labels" viewBox="0 0 1183 860" aria-hidden="true">
    {labels.map((label, index) => <g className="chart-label" style={{ '--label-index': index } as React.CSSProperties} key={label.text.join(' ')}>
      <path d={`M${label.x} ${label.y + 22} L${label.anchor} ${label.end}`} />
      <circle cx={label.anchor} cy={label.end} r="5" />
      <text x={label.x} y={label.y} textAnchor="middle"><tspan x={label.x}>{label.text[0]}</tspan><tspan x={label.x} dy="27">{label.text[1]}</tspan></text>
    </g>)}
  </svg>;
}

function Hero(): React.JSX.Element {
  return <section className="hero section" aria-labelledby="hero-title">
    <div className="hero-art"><SectionArt stage={0} label="A layered mountain of market profiles. A gold profile is selected." /></div>
    <div className="hero-copy shell hero-reveal">
      <p className="eyebrow">Open research · paper trading</p>
      <h1 id="hero-title">An open laboratory<br className="desktop-break" /> for AI trading.</h1>
      <p className="hero-description">A shared place to study how AI systems make trading decisions. We define controlled paper experiments, preserve the evidence, and make the method possible to inspect.</p>
      <a className="text-link" href="/simulation">Open simulation <span aria-hidden="true">→</span></a>
    </div>
  </section>;
}

function WhySection(): React.JSX.Element {
  return <section className="why section" aria-labelledby="why-title">
    <div className="shell editorial-grid why-grid">
      <figure className="grid-figure"><SectionArt stage={1} className="grid-art" label="Two hundred and twenty market profile silhouettes arranged in twenty columns and eleven rows, with one selected. The count describes the illustration, not active models." />
        <figcaption className="figure-caption"><span>Conceptual illustration</span>220 profiles, not an active-model count.</figcaption>
      </figure>
      <div className="section-copy why-copy"><p className="eyebrow">A controlled baseline</p><h2 id="why-title">A fair comparison starts with shared conditions.</h2>
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
        <SectionArt stage={2} className="chart-art" label="A conceptual chart that reuses the selected profile, divided into six research areas. It does not show price or performance data." />
        <ChartLabels />
        <p className="figure-caption chart-caption"><span>Conceptual illustration</span>The same profile shape is divided into six research questions; no price or performance values are shown.</p>
      </div>
      <div className="section-copy data-copy"><p className="eyebrow">A traceable record</p><h2 id="data-title">From market data to an accountable decision.</h2>
        <p>Each experiment connects its market snapshot, exact prompt, proposal, risk checks, execution, accounting entries, and evaluation. The chain makes it possible to inspect how an idea changed an account.</p>
        <p>Changes to tools, strategies, assets, or execution policies belong in the separate <code>research_extended</code> track, with its own comparisons.</p>
      </div>
      <ul className="sr-only" aria-label="Research areas represented in the chart">{['Market snapshot', 'Prompt and response', 'Risk checks', 'Order execution', 'Account ledger', 'Evaluation record'].map((label) => <li key={label}>{label}</li>)}</ul>
    </div>
  </section>;
}

function ModelsSection(): React.JSX.Element {
  return <section className="models section" aria-labelledby="models-title">
    <div className="shell models-grid">
      <div className="lattice-column"><SectionArt stage={3} className="lattice-art" label="An isometric lattice linking six platform families to a shared center." />
        <ul className="family-legend">{FAMILY_NAMES.map((name, index) => <li key={name}><i style={{ backgroundColor: FAMILY_COLORS[index] }} />{name}</li>)}</ul>
      </div>
      <div className="section-copy models-copy"><p className="eyebrow">One shared research record</p><h2 id="models-title">Many parts. One accountable arena.</h2>
        <p>Market data, prompts, risk checks, execution, accounting, and evaluation each contribute to the record of a paper experiment.</p>
        <p>The baseline fixes its manifest before a run. Extended research can explore a changed method while keeping those comparisons separate and legible.</p>
      </div>
    </div>
  </section>;
}

function TeamSection(): React.JSX.Element {
  return <section className="team section" aria-labelledby="team-title">
    <div className="shell team-grid">
      <SectionArt stage={4} className="team-art" label="A multicolored tiled O and A mark made for the Open Alpha Arena Lab." />
      <div className="section-copy team-copy"><p className="eyebrow">Open by design</p><h2 id="team-title">A laboratory the public can examine.</h2>
        <p>Experiment definitions and public evidence are designed to make the setup, decisions, and outcomes inspectable without exposing private credentials or hidden provider reasoning.</p>
        <p>The project is self-hosted and developed in the open. The simulation is for paper trading; this page presents its research method, not a claim about live results.</p>
        <a className="text-link" href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">Read the project on GitHub <span aria-hidden="true">↗</span></a>
      </div>
    </div>
  </section>;
}

function Footer(): React.JSX.Element {
  return <footer className="site-footer"><div className="shell footer-inner"><a className="footer-home" href="/" aria-label="Open Alpha Arena Lab home"><BrandMark small /></a><span>Open Alpha Arena Lab · Public research</span><a href="https://github.com/leonfullxr/open-alpha-arena-lab" target="_blank" rel="noreferrer">GitHub ↗</a><a href="/#methodology">Methodology</a><span>Paper trading only</span></div></footer>;
}

export function ArenaLanding(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const anchorsRef = useRef<HTMLDivElement>(null);
  useSceneCoordinator(canvasRef, anchorsRef);
  return <div className="page-shell">
    <Header />
    <main id="main-content" ref={anchorsRef} className="landing-content">
      <canvas className="scene-canvas" ref={canvasRef} aria-hidden="true" />
      <Hero /><WhySection /><DataSection /><ModelsSection /><TeamSection />
    </main>
    <Footer />
  </div>;
}
