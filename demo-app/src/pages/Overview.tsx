import { useEffect, useState } from 'react';
import { apiGet } from '../hooks/useApi';
import type { PageId, ScorecardResponse } from '../types';
import './Overview.css';

interface OverviewProps {
  onNavigate: (page: PageId) => void;
  demoConfigured: boolean | null;
}

export function Overview({ onNavigate, demoConfigured }: OverviewProps) {
  const [benchmark, setBenchmark] = useState<ScorecardResponse['practice_benchmark']>();
  useEffect(() => {
    let active = true;
    apiGet<ScorecardResponse>('/api/scorecard').then(data => {
      if (active) setBenchmark(data.practice_benchmark);
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  return (
    <div className="overview-layout">
      <section className="overview-hero" aria-labelledby="hero-title">
        <div className="overview-intro">
          <span className="overview-eyebrow">Hospital research / Privacy workbench</span>
          <h1 id="hero-title">Secret Wards</h1>
          <p>Prepare a research release from multilingual hospital records. Compare each file, inspect patient links and review what the release still reveals.</p>
          <div className="overview-actions">
            <button className="btn btn-primary" onClick={() => onNavigate('run')}>Open workbench →</button>
          </div>
          {demoConfigured === false && <p role="alert">The local adapter is unavailable. Start the workbench launcher to run a dataset.</p>}
        </div>
        <div className="release-example">
          <span className="overview-eyebrow">Example release</span>
          <dl><div><dt>Patient name</dt><dd className="example-private">[NAME]</dd></div>
            <div><dt>Age at visit</dt><dd>40–44 years</dd></div>
            <div><dt>Medication</dt><dd>Paracetamol 650 mg</dd></div>
            <div><dt>Length of stay</dt><dd>9 days</dd></div></dl>
          <small>English · हिन्दी · Hinglish</small>
        </div>
      </section>
      <section aria-labelledby="practice-title">
        <h2 id="practice-title">Practice benchmark</h2>
        <p className="overview-caption">Local measurements on the organiser’s 200-file practice set.</p>
        {benchmark ? <dl className="benchmark-strip">
          <div><dt>Visible identifiers</dt><dd>{benchmark.labeled_identifiers_visible.found} / {benchmark.labeled_identifiers_visible.total.toLocaleString()}</dd></div>
          <div><dt>Clinical probes kept</dt><dd>{benchmark.checked_medical_values_retained.kept.toLocaleString()} / {benchmark.checked_medical_values_retained.total.toLocaleString()}</dd></div>
          <div><dt>Linkage recall</dt><dd>{(benchmark.linkage.recall * 100).toFixed(0)}%</dd></div>
          <div><dt>Linkage precision</dt><dd>{(benchmark.linkage.precision * 100).toFixed(0)}%</dd></div>
        </dl> : <p>Benchmark figures load from the local adapter.</p>}
      </section>
    </div>
  );
}
