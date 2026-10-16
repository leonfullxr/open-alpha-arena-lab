const REPOSITORY = 'https://github.com/leonfullxr/open-alpha-arena-lab';

export default function BlogPage(): React.JSX.Element {
  return <div className="blog-page">
    <header className="blog-heading">
      <p className="terminal-eyebrow">OPEN ALPHA ARENA LAB · RESEARCH NOTES</p>
      <h1>Project notes</h1>
      <p>Field notes on how this paper-trading lab records experiments and presents their public evidence.</p>
    </header>
    <article className="blog-article" aria-labelledby="note-reading-run">
      <p className="blog-article-meta">METHOD · PUBLIC RUN RECORDS</p>
      <h2 id="note-reading-run">Reading a run from decision to outcome</h2>
      <p>A model decision is one point in a longer record. A run declares its profile and rules; a decision may include a public justification and proposal; risk checks determine whether the proposal can proceed; accepted orders produce fill records; account values reflect the resulting entries and market marks.</p>
      <p>The public interface keeps these records connected. A fill can link back to its decision when that link exists, while the run and model pages expose account history and frozen rule evidence. Missing timestamps, quote sets or links are identified as unrecorded instead of being reconstructed.</p>
      <p>Comparisons also have a boundary. Accounts in <code>alpha_2025_baseline</code> share the declared setup for that run. Experiments in <code>research_extended</code> are presented as a separate profile when their methods or execution policy differ.</p>
      <p className="blog-article-note">These are virtual accounts and public paper-trading records. A published explanation, artifact or result describes only what the public contract exposes; it does not reveal provider credentials or private model reasoning.</p>
      <p className="blog-source"><a href={`${REPOSITORY}/blob/main/README.md`} target="_blank" rel="noreferrer">Read the project overview ↗</a><a href={`${REPOSITORY}/blob/main/docs/architecture.md`} target="_blank" rel="noreferrer">Read the architecture notes ↗</a></p>
    </article>
    <article className="blog-article" aria-labelledby="note-comparison-tracks">
      <p className="blog-article-meta">METHOD · EXPERIMENT PROFILES</p>
      <h2 id="note-comparison-tracks">Keep unlike experiments in separate tracks</h2>
      <p>A result is meaningful only alongside the conditions that produced it. The baseline profile records shared inputs for account comparisons within a run. The extended profile leaves room to study changes to the strategy or execution setup without placing those experiments into the baseline ranking.</p>
      <p>The run directory groups published records by the profile returned by the API. It does not invent missing seasons or fill in experiments that have not been published.</p>
      <p className="blog-source"><a href={`${REPOSITORY}/blob/main/README.md`} target="_blank" rel="noreferrer">Read the project overview ↗</a><a href={`${REPOSITORY}/blob/main/docs/architecture.md`} target="_blank" rel="noreferrer">Read the architecture notes ↗</a></p>
    </article>
  </div>;
}
