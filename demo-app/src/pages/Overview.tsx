import { useEffect, useState } from 'react';
import { apiGet } from '../hooks/useApi';
import type { PageId, PresetInfo, RunRequestPayload, ScorecardResponse } from '../types';
import './Overview.css';

interface OverviewProps {
  onNavigate: (page: PageId) => void;
  demoConfigured: boolean | null;
  onQuickRun: (payload: RunRequestPayload) => Promise<boolean>;
  isStarting: boolean;
  presets: PresetInfo[];
}

function ShieldIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 19 6v5c0 4.8-3 8.3-7 10-4-1.7-7-5.2-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/></svg>;
}

function RecordsIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4.5h9l3 3v12H6z"/><path d="M14.5 4.5v3h3M9 11h6M9 14h6M9 17h4"/></svg>;
}

function LinkIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 14.5 5-5M8 16l-1 1a4 4 0 0 1-5.7-5.7l4-4A4 4 0 0 1 11 7m5 1 1-1a4 4 0 0 1 5.7 5.7l-4 4A4 4 0 0 1 13 17"/></svg>;
}

export function Overview({ onNavigate, demoConfigured, onQuickRun, isStarting, presets }: OverviewProps) {
  const [benchmark, setBenchmark] = useState<ScorecardResponse['practice_benchmark']>();

  useEffect(() => {
    let active = true;
    apiGet<ScorecardResponse>('/api/scorecard').then(data => {
      if (active) setBenchmark(data.practice_benchmark);
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  const run = (id: string, seed?: number) => {
    onNavigate('run');
    void onQuickRun({ source: 'preset', preset_id: id, seed });
  };
  const scenarios = presets.filter(preset => preset.sample_seed != null);

  return (
    <div className="overview-layout">
      <section className="overview-hero" aria-labelledby="hero-title">
        <div className="overview-intro">
          <span className="overview-eyebrow"><span className="eyebrow-dot" /> PRIVATE BY DESIGN · RUNS LOCALLY</span>
          <h1 id="hero-title">Protect privacy.<br /><em>Keep meaning.</em></h1>
          <p>Prepare safer research data from hospital records in English, Hindi and Hinglish. Remove identity details while keeping useful clinical information.</p>
          <div className="overview-actions">
            <button className="btn btn-primary overview-primary" onClick={() => onNavigate('run')}>
              Open the workbench <span aria-hidden="true">→</span>
            </button>
            <button className="overview-demo" disabled={!demoConfigured || isStarting} onClick={() => run('unseen_chaos')}>
              {isStarting ? 'Starting sample…' : 'Try a sample dataset'} <span aria-hidden="true">↗</span>
            </button>
          </div>
          {demoConfigured === false && <p className="overview-warning" role="alert">The local pipeline is offline. Start the Secret Wards launcher, then refresh this page.</p>}
          {demoConfigured === true && <p className="overview-local-note"><span aria-hidden="true">●</span> Files stay on this computer during processing.</p>}
        </div>
        <div className="overview-art-wrap">
          <img className="overview-art" src="/clinical-privacy-hero.svg" alt="A protected medical record with a privacy shield" />
          <div className="art-caption"><span className="art-lock" aria-hidden="true">⌑</span><span><strong>Private processing</strong><small>Local CPU · no cloud upload</small></span></div>
        </div>
      </section>

      <section className="overview-process" aria-label="How Secret Wards works">
        <article className="process-step"><span className="process-icon"><RecordsIcon /></span><span><strong>Bring your records</strong><small>Upload a folder of CSV, TSV, JSON or text files.</small></span></article>
        <span className="process-arrow" aria-hidden="true">→</span>
        <article className="process-step"><span className="process-icon"><ShieldIcon /></span><span><strong>Protect identities</strong><small>Redact identifiers and quarantine unsafe files.</small></span></article>
        <span className="process-arrow" aria-hidden="true">→</span>
        <article className="process-step"><span className="process-icon"><LinkIcon /></span><span><strong>Review the release</strong><small>Check the files, patient links and audit report.</small></span></article>
      </section>

      {scenarios.length > 0 && <section className="overview-section" aria-labelledby="scenarios-title">
        <div className="overview-section-head">
          <div><span className="section-kicker">PRACTICE WITH SYNTHETIC DATA</span><h2 id="scenarios-title">Choose a sample run</h2></div>
          <button className="text-action" onClick={() => onNavigate('run')}>See all input options <span aria-hidden="true">→</span></button>
        </div>
        <div className="scenario-cards">{scenarios.map((preset, index) => <article className="scenario-card" key={preset.id}>
          <div className={`scenario-art scenario-art-${index % 3}`}>
            <img
              src={`/scenario-${['ward', 'lab', 'outreach'][index % 3]}.svg`}
              alt=""
              aria-hidden="true"
            />
            <span className="scenario-tag">{preset.highlights[0]}</span>
          </div>
          <h3>{preset.name}</h3><p>{preset.description}</p>
          <button className="scenario-run" disabled={!demoConfigured || isStarting} onClick={() => run(preset.id, preset.sample_seed ?? undefined)}>
            Run sample <span aria-hidden="true">↗</span>
          </button>
        </article>)}</div>
      </section>}

      <section className="overview-benchmark" aria-labelledby="practice-title">
        <div className="benchmark-heading">
          <span className="benchmark-mark"><ShieldIcon /></span>
          <div><span className="section-kicker">PRACTICE DATA CHECK</span><h2 id="practice-title">A quick quality snapshot</h2>
            <p>Measurements from the organizer’s synthetic practice set.</p></div>
        </div>
        {benchmark ? <dl className="benchmark-strip">
          <div><dt>Identifiers visible</dt><dd>{benchmark.labeled_identifiers_visible.found} <small>/ {benchmark.labeled_identifiers_visible.total.toLocaleString()}</small></dd><span className="metric-foot">Lower is better</span></div>
          <div><dt>Clinical values kept</dt><dd>{benchmark.checked_medical_values_retained.kept.toLocaleString()} <small>/ {benchmark.checked_medical_values_retained.total.toLocaleString()}</small></dd><span className="metric-foot">Higher is better</span></div>
          <div><dt>Linking precision</dt><dd>{(benchmark.linkage.precision * 100).toFixed(0)}<small>%</small></dd><span className="metric-foot">Avoids false merges</span></div>
          <div><dt>Linking recall</dt><dd>{(benchmark.linkage.recall * 100).toFixed(0)}<small>%</small></dd><span className="metric-foot">Finds repeated patients</span></div>
        </dl> : <p className="benchmark-loading">Benchmark figures load from the local adapter.</p>}
      </section>

      <div className="overview-formats" aria-label="Supported input types">
        <span>Works with</span><b>CSV</b><b>TSV</b><b>JSON / FHIR</b><b>Plain text</b><i />
        <span className="language-note">English <span>·</span> हिन्दी <span>·</span> Hinglish</span>
      </div>
    </div>
  );
}
