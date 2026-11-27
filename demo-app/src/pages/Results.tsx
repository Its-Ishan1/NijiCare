import { LinkageView } from '../components/LinkageView';
import { StatCard } from '../components/StatCard';
import type { PageId, RunDetail, RunHistoryItem } from '../types';
import './Results.css';

interface ResultsProps {
  runDetail: RunDetail | null;
  history: RunHistoryItem[];
  onSelectRun: (runId: string) => Promise<void>;
  onNavigate: (page: PageId) => void;
}

function fmt(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null;
  return n.toLocaleString('en-IN');
}

function fmtSec(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null;
  return `${n.toFixed(2)} s`;
}

export function Results({ runDetail, history, onSelectRun, onNavigate }: ResultsProps) {
  if (!runDetail || runDetail.status !== 'completed') {
    return (
      <div className="card">
        <p className="section-subtitle" style={{ padding: '0.5rem 0' }}>
          No completed run yet.{' '}
          <button type="button" className="btn btn-secondary" style={{ marginLeft: '0.75rem' }} onClick={() => onNavigate('run')}>
            Open Workbench →
          </button>
        </p>
      </div>
    );
  }

  const { counts, entities, timing, resources, records, risk, run_id, policy_used, secret_mode } = runDetail;
  const entityEntries = Object.entries(entities || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="results-layout">
      <div className="results-header">
        <div>
          <div className="section-kicker">
            Run completed · {runDetail.label || runDetail.source} · Key mode: {secret_mode || 'default'}
          </div>
          <h2 className="section-title" style={{ marginTop: '0.35rem' }}>Results dashboard</h2>
          <p className="section-subtitle" style={{ marginTop: '0.4rem' }}>
            Live metrics from <span className="mono">report.json</span> and <span className="mono">records.jsonl</span> (<span className="mono">{run_id}</span>).
          </p>
        </div>
        <div className="results-actions">
          {history.length > 1 && (
            <select
              aria-label="Switch run"
              className="field-select"
              style={{ width: 'auto', minWidth: '180px' }}
              value={run_id}
              onChange={(e) => void onSelectRun(e.target.value)}
            >
              {history.map((h) => (
                <option key={h.run_id} value={h.run_id}>
                  {h.label || h.source} ({h.run_id.slice(-6)})
                </option>
              ))}
            </select>
          )}
          <a
            href={`/api/runs/${encodeURIComponent(run_id)}/export`}
            download
            className="btn btn-secondary"
            title="Download sanitized files, report.json, and records.jsonl as a ZIP"
          >
            ↓ Download ZIP
          </a>
          <button type="button" className="btn btn-navy" onClick={() => onNavigate('files')}>
            Inspect files →
          </button>
        </div>
      </div>

      {/* KPI stat grid */}
      <section className="results-kpi-grid" aria-label="Run summary metrics">
        <StatCard label="Files processed" value={fmt(counts?.files_total)} tone="default" />
        <StatCard label="Files sanitized" value={fmt(counts?.files_sanitized)} tone="highlight" />
        <StatCard
          label="Files quarantined"
          value={fmt(counts?.files_quarantined)}
          tone={counts?.files_quarantined ? 'saffron' : 'default'}
        />
        <StatCard label="Records processed" value={fmt(counts?.records_processed)} />
        <StatCard label="Records linked" value={fmt(counts?.records_linked)} tone="highlight" />
        <StatCard label="Identifiers detected" value={fmt(counts?.identifiers_detected)} />
        <StatCard label="Records generalized" value={fmt(counts?.records_generalized)} />
        <StatCard
          label="Runtime"
          value={fmtSec(timing?.seconds)}
          hint={resources?.peak_rss_mb ? `Peak RSS: ${resources.peak_rss_mb.toFixed(1)} MB` : 'Offline CPU execution'}
        />
      </section>

      {/* Entity breakdown */}
      {entityEntries.length > 0 && (
        <section className="card">
          <div className="section-heading" style={{ marginBottom: '1rem' }}>
            <div className="section-kicker">Entity Detection Breakdown</div>
            <h3 style={{ fontSize: '1.1rem', marginTop: '0.25rem' }}>Identifiers redacted by category</h3>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.55rem' }}>
            {entityEntries.map(([kind, count]) => (
              <div
                key={kind}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.45rem 0.85rem',
                  borderRadius: '8px',
                  background: 'var(--bg-primary)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <span className="mono">{kind}</span>
                <strong>{count.toLocaleString('en-IN')}</strong>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Active Policy summary */}
      {policy_used && (
        <section className="card">
          <div className="section-kicker">Active Policy Snapshot</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.4rem' }}>
            <span className="preset-chip">Age band: {policy_used.age_band_years}–{policy_used.age_band_max_years} yrs (k={policy_used.age_k_anonymity})</span>
            <span className="preset-chip">Date shift: {policy_used.shift_dates ? `±${policy_used.date_shift_max_days} days` : 'OFF'}</span>
            <span className="preset-chip">Age banding: {policy_used.generalize_ages ? 'ON' : 'OFF'}</span>
            <span className="preset-chip">Preserve doctors: {policy_used.preserve_doctors ? 'ON' : 'OFF'}</span>
            <span className="preset-chip">Filename hashing: {policy_used.hash_sensitive_filenames ? 'ON' : 'OFF'}</span>
            {policy_used.extra_redact_fields.length > 0 && (
              <span className="preset-chip">Extra redact: {policy_used.extra_redact_fields.join(', ')}</span>
            )}
            {policy_used.extra_preserve_fields.length > 0 && (
              <span className="preset-chip">Extra preserve: {policy_used.extra_preserve_fields.join(', ')}</span>
            )}
          </div>
        </section>
      )}

      {/* Risk summary */}
      {risk && (
        <section className="card" aria-labelledby="risk-title">
          <div className="section-heading">
            <div className="section-kicker">Indirect-identification risk · from release_risk.py</div>
            <h3 id="risk-title" style={{ fontSize: '1.1rem', marginTop: '0.35rem' }}>
              Uniqueness measurement
            </h3>
          </div>
          <div className="results-risk-grid">
            {risk.age_band_and_district && (
              <div className="risk-item">
                <span className="risk-label">Age-band + district</span>
                <span className="risk-value">
                  {risk.age_band_and_district.unique_on_at_least_one_observation} /{' '}
                  {risk.age_band_and_district.covered_pseudonyms} unique
                </span>
              </div>
            )}
            {risk.age_band_district_shifted_admission_week_and_diagnosis && (
              <div className="risk-item">
                <span className="risk-label">4-field FHIR subset</span>
                <span className="risk-value">
                  {risk.age_band_district_shifted_admission_week_and_diagnosis.unique_on_at_least_one_observation} /{' '}
                  {risk.age_band_district_shifted_admission_week_and_diagnosis.covered_pseudonyms} unique
                </span>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Linkage groups */}
      <section className="card" aria-labelledby="linkage-title">
        <div className="section-heading">
          <div className="section-kicker">Record linkage · from records.jsonl</div>
          <h3 id="linkage-title" style={{ fontSize: '1.1rem', marginTop: '0.35rem' }}>
            Pseudonym groups
          </h3>
        </div>
        <LinkageView records={records} />
      </section>
    </div>
  );
}
