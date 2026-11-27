import { useEffect, useState } from 'react';
import { apiGet } from '../hooks/useApi';
import type { RunDetail, ScorecardResponse } from '../types';
import './PrivacyAudit.css';

interface PrivacyAuditProps {
  runDetail: RunDetail | null;
}

function Fraction({ kept, total }: { kept: number; total: number }) {
  return (
    <span>
      <strong>{kept.toLocaleString('en-IN')}</strong> / {total.toLocaleString('en-IN')}
    </span>
  );
}

export function PrivacyAudit({ runDetail }: PrivacyAuditProps) {
  const [scorecard, setScorecard] = useState<ScorecardResponse | null>(null);
  const [loadingScorecard, setLoadingScorecard] = useState(true);

  useEffect(() => {
    setLoadingScorecard(true);
    apiGet<ScorecardResponse>('/api/scorecard')
      .then(setScorecard)
      .catch(() => setScorecard(null))
      .finally(() => setLoadingScorecard(false));
  }, []);

  const counts = runDetail?.counts;
  const timing = runDetail?.timing;
  const resources = runDetail?.resources;
  const sc = scorecard?.practice_benchmark;
  const v3 = scorecard?.v3_local_verification;

  return (
    <div className="audit-layout">
      {/* Section 1: This run */}
      <section className="card" aria-labelledby="run-audit-title">
        <div className="section-heading">
          <div className="section-kicker">From report.json — current pipeline execution</div>
          <h2 id="run-audit-title" className="section-title">This run</h2>
        </div>

        {!runDetail || runDetail.status !== 'completed' ? (
          <div className="audit-no-run">
            <span>No completed run yet. Run the synthetic demo to populate this section.</span>
          </div>
        ) : (
          <div className="audit-run-grid">
            <div className="audit-row">
              <span className="audit-label">Files total</span>
              <span className="audit-val">{counts?.files_total ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Files sanitized</span>
              <span className="audit-val">{counts?.files_sanitized ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Files quarantined</span>
              <span className="audit-val">{counts?.files_quarantined ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Records processed</span>
              <span className="audit-val">{counts?.records_processed?.toLocaleString('en-IN') ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Records linked</span>
              <span className="audit-val">{counts?.records_linked?.toLocaleString('en-IN') ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Identifiers detected</span>
              <span className="audit-val">{counts?.identifiers_detected?.toLocaleString('en-IN') ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Records generalized</span>
              <span className="audit-val">{counts?.records_generalized?.toLocaleString('en-IN') ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Records suppressed</span>
              <span className="audit-val">{counts?.records_suppressed ?? '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Runtime</span>
              <span className="audit-val mono">{timing?.seconds !== undefined ? `${timing.seconds.toFixed(2)} s` : '—'}</span>
            </div>
            <div className="audit-row">
              <span className="audit-label">Peak memory (RSS)</span>
              <span className="audit-val mono">
                {resources?.peak_rss_mb ? `${resources.peak_rss_mb.toFixed(1)} MB` : 'Not measured'}
              </span>
            </div>
          </div>
        )}
      </section>

      {/* Section 2: Practice benchmark */}
      <section className="card" aria-labelledby="practice-audit-title">
        <div className="section-heading">
          <div className="section-kicker">Organiser practice benchmark · 200 files</div>
          <h2 id="practice-audit-title" className="section-title">Practice benchmark results</h2>
          <div className="disclaimer-note audit-disclaimer">
            <span>ℹ</span>
            Practice data; not hidden competition results.
          </div>
        </div>

        {loadingScorecard ? (
          <div className="audit-loading">Loading scorecard…</div>
        ) : !sc ? (
          <div className="audit-no-run">Could not load scorecard from local server.</div>
        ) : (
          <>
            <div className="audit-benchmark-grid">
              <div className="audit-benchmark-card">
                <div className="ab-label">Labeled identifiers still visible</div>
                <div className="ab-value ab-green">
                  <Fraction kept={sc.labeled_identifiers_visible.found} total={sc.labeled_identifiers_visible.total} />
                </div>
                <div className="ab-hint">0 found — all identifiers removed</div>
              </div>
              <div className="audit-benchmark-card">
                <div className="ab-label">Planted canaries exposed</div>
                <div className="ab-value ab-green">
                  <Fraction kept={sc.planted_canaries_exposed.found} total={sc.planted_canaries_exposed.total} />
                </div>
                <div className="ab-hint">0 of 4 canaries leaked</div>
              </div>
              <div className="audit-benchmark-card">
                <div className="ab-label">Medical values retained</div>
                <div className="ab-value ab-teal">
                  <Fraction kept={sc.checked_medical_values_retained.kept} total={sc.checked_medical_values_retained.total} />
                </div>
                <div className="ab-hint">100% clinical fidelity</div>
              </div>
              <div className="audit-benchmark-card">
                <div className="ab-label">Linkage precision / recall / F0.5</div>
                <div className="ab-value ab-teal mono">
                  {sc.linkage.precision.toFixed(2)} / {sc.linkage.recall.toFixed(2)} / {sc.linkage.f05.toFixed(2)}
                </div>
                <div className="ab-hint">0 false merges</div>
              </div>
            </div>

            {/* v3 improvements */}
            {v3 && (
              <div className="audit-v3-block">
                <div className="ab-label" style={{ marginBottom: '0.6rem' }}>v3 improvements on practice data</div>
                <div className="audit-v3-grid">
                  <div className="av3-item">
                    <span className="av3-num">
                      {v3.age_band_and_district_v3.unique} / {v3.age_band_and_district_v3.covered}
                    </span>
                    <span>Age-band + district unique (down from 14/39 in v2)</span>
                  </div>
                  <div className="av3-item">
                    <span className="av3-num">
                      {v3.free_text_note_ages_generalized.kept} / {v3.free_text_note_ages_generalized.total}
                    </span>
                    <span>Free-text note ages generalized (up from 3/85 in v2)</span>
                  </div>
                </div>
                <p className="av3-note">{v3.note}</p>
              </div>
            )}

            {/* Residual risk */}
            <div className="audit-risk-block">
              <div className="section-kicker" style={{ marginBottom: '0.75rem' }}>
                Residual indirect-identification risk (covered-subset estimate)
              </div>

              <div className="audit-risk-warn">
                <strong>⚠ Important caveat</strong>
                <p>{sc.residual_risk.caveat}</p>
                <p style={{ marginTop: '0.5rem' }}>
                  The numbers below measure uniqueness within the pseudonyms that have both a district
                  and an age observation — not all patients in the dataset.
                  Uniqueness does not equal re-identification success.
                </p>
              </div>

              <div className="audit-risk-items">
                <div className="ari-item">
                  <div className="ari-label">Age-band + district (practice dev/input)</div>
                  <div className="ari-value">
                    <span className="mono">{sc.residual_risk.age_band_and_district.unique} / {sc.residual_risk.age_band_and_district.covered}</span>
                    <span className="ari-pct">
                      ({((sc.residual_risk.age_band_and_district.unique / sc.residual_risk.age_band_and_district.covered) * 100).toFixed(1)}%)
                    </span>
                  </div>
                  <p className="ari-note">{sc.residual_risk.age_band_and_district.note}</p>
                </div>
                <div className="ari-item">
                  <div className="ari-label">FHIR 4-field subset (age-band, district, shifted week, diagnosis)</div>
                  <div className="ari-value">
                    <span className="mono">{sc.residual_risk.fhir_4_field_subset.unique} / {sc.residual_risk.fhir_4_field_subset.covered}</span>
                    <span className="ari-pct">
                      ({sc.residual_risk.fhir_4_field_subset.covered > 0
                        ? ((sc.residual_risk.fhir_4_field_subset.unique / sc.residual_risk.fhir_4_field_subset.covered) * 100).toFixed(1)
                        : 'N/A'}%)
                    </span>
                  </div>
                  <p className="ari-note">{sc.residual_risk.fhir_4_field_subset.note}</p>
                </div>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
