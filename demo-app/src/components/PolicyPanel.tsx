import { useMemo } from 'react';
import {
  ALL_PII_CATEGORIES,
  DEFAULT_POLICY,
  type PolicyConfig,
  type SecretMode,
} from '../types';
import './PolicyPanel.css';

interface PolicyPanelProps {
  policy: PolicyConfig;
  onChange: (next: PolicyConfig) => void;
  secretMode: SecretMode;
  onSecretModeChange: (mode: SecretMode) => void;
  customSecret: string;
  onCustomSecretChange: (val: string) => void;
  defaultPolicy?: PolicyConfig;
}

function parseCsvList(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

export function PolicyPanel({
  policy,
  onChange,
  secretMode,
  onSecretModeChange,
  customSecret,
  onCustomSecretChange,
  defaultPolicy = DEFAULT_POLICY,
}: PolicyPanelProps) {
  const regexError = useMemo(() => {
    if (!policy.extra_redact_regex.trim()) return null;
    try {
      new RegExp(policy.extra_redact_regex);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : 'Invalid regular expression';
    }
  }, [policy.extra_redact_regex]);

  const toggleCategory = (cat: string) => {
    const has = policy.redact_categories.includes(cat);
    const next = has
      ? policy.redact_categories.filter((c) => c !== cat)
      : [...policy.redact_categories, cat];
    onChange({ ...policy, redact_categories: next });
  };

  return (
    <div className="policy-panel">
      <div className="policy-panel-head">
        <div>
          <div className="section-kicker">Policy &amp; Field Settings</div>
          <h3 className="policy-title">Configure privacy parameters &amp; custom fields</h3>
          <p className="policy-sub">
            Tune quasi-identifier generalization, date shifting, PII categories, custom column rules, and key rotation for this run.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => {
            onChange({ ...defaultPolicy });
            onSecretModeChange('default');
            onCustomSecretChange('');
          }}
        >
          Reset defaults
        </button>
      </div>

      {/* 1. Quasi-identifiers & Temporal */}
      <div className="policy-section">
        <h4 className="policy-section-title">1. Generalization &amp; Temporal Parameters</h4>
        <div className="policy-num-grid">
          <label className="field-group">
            <span className="field-label">Age band base width (years)</span>
            <input
              type="number"
              min={1}
              max={50}
              className="field-input"
              value={policy.age_band_years}
              onChange={(e) => {
                const v = Math.max(1, Math.min(50, Number(e.target.value) || 1));
                onChange({
                  ...policy,
                  age_band_years: v,
                  age_band_max_years: Math.max(v, policy.age_band_max_years),
                });
              }}
            />
            <span className="field-hint">Initial bin width (e.g. 5 → 35-39).</span>
          </label>

          <label className="field-group">
            <span className="field-label">Max adaptive age span (years)</span>
            <input
              type="number"
              min={policy.age_band_years}
              max={100}
              className="field-input"
              value={policy.age_band_max_years}
              onChange={(e) => {
                const v = Math.max(policy.age_band_years, Math.min(100, Number(e.target.value) || 50));
                onChange({ ...policy, age_band_max_years: v });
              }}
            />
            <span className="field-hint">Upper cap when merging sparse district tails.</span>
          </label>

          <label className="field-group">
            <span className="field-label">Age k-anonymity threshold (k)</span>
            <input
              type="number"
              min={1}
              max={50}
              className="field-input"
              value={policy.age_k_anonymity}
              onChange={(e) => {
                const v = Math.max(1, Math.min(50, Number(e.target.value) || 1));
                onChange({ ...policy, age_k_anonymity: v });
              }}
            />
            <span className="field-hint">Min patients per (district, age band). Use 1 for fixed bins.</span>
          </label>

          <label className="field-group">
            <span className="field-label">Max date shift (± days)</span>
            <input
              type="number"
              min={1}
              max={3650}
              className="field-input"
              value={policy.date_shift_max_days}
              onChange={(e) => {
                const v = Math.max(1, Math.min(3650, Number(e.target.value) || 180));
                onChange({ ...policy, date_shift_max_days: v });
              }}
            />
            <span className="field-hint">Per-patient HMAC offset; preserves stay lengths.</span>
          </label>
        </div>
      </div>

      {/* 2. Pipeline Behavior Toggles */}
      <div className="policy-section">
        <h4 className="policy-section-title">2. Transformation Toggles</h4>
        <div className="policy-toggle-grid">
          <label className="toggle-item">
            <input
              type="checkbox"
              checked={policy.shift_dates}
              onChange={(e) => onChange({ ...policy, shift_dates: e.target.checked })}
            />
            <span>
              <strong>Per-patient date shifting</strong>
              <small>Shift clinical dates deterministically while preserving stay duration.</small>
            </span>
          </label>

          <label className="toggle-item">
            <input
              type="checkbox"
              checked={policy.generalize_ages}
              onChange={(e) => onChange({ ...policy, generalize_ages: e.target.checked })}
            />
            <span>
              <strong>Adaptive age banding</strong>
              <small>Replace exact ages in tables, JSON, and notes with truthful bands.</small>
            </span>
          </label>

          <label className="toggle-item">
            <input
              type="checkbox"
              checked={policy.preserve_doctors}
              onChange={(e) => onChange({ ...policy, preserve_doctors: e.target.checked })}
            />
            <span>
              <strong>Preserve doctor / clinician names</strong>
              <small>Keep Dr. / Consultant / Physician references intact for clinical utility.</small>
            </span>
          </label>

          <label className="toggle-item">
            <input
              type="checkbox"
              checked={policy.hash_sensitive_filenames}
              onChange={(e) => onChange({ ...policy, hash_sensitive_filenames: e.target.checked })}
            />
            <span>
              <strong>Hash sensitive filenames &amp; JSON keys</strong>
              <small>Rename files/keys containing PII or IDs to opaque item-&lt;hmac&gt; labels.</small>
            </span>
          </label>

          <label className="toggle-item">
            <input
              type="checkbox"
              checked={policy.ml_fallback ?? true}
              onChange={(e) => onChange({ ...policy, ml_fallback: e.target.checked })}
            />
            <span>
              <strong>Hybrid Statistical ML Fallback (CRF + ColClf)</strong>
              <small>Use trained offline Linear-Chain CRF for bare prose &amp; Column-Value Classifier for unfamiliar headers.</small>
            </span>
          </label>
        </div>

        {(policy.ml_fallback ?? true) && (
          <div className="policy-num-grid" style={{ marginTop: '0.85rem' }}>
            <label className="field-group">
              <span className="field-label">ML NER CRF confidence threshold</span>
              <input
                type="number"
                min={0.5}
                max={0.99}
                step={0.05}
                className="field-input"
                value={policy.ml_ner_threshold ?? 0.85}
                onChange={(e) => {
                  const v = Math.max(0.5, Math.min(0.99, Number(e.target.value) || 0.85));
                  onChange({ ...policy, ml_ner_threshold: Number(v.toFixed(2)) });
                }}
              />
              <span className="field-hint">Min Forward-Backward marginal probability (0.50–0.99).</span>
            </label>

            <label className="field-group">
              <span className="field-label">ML Column Classifier threshold</span>
              <input
                type="number"
                min={0.5}
                max={0.99}
                step={0.05}
                className="field-input"
                value={policy.ml_col_threshold ?? 0.80}
                onChange={(e) => {
                  const v = Math.max(0.5, Math.min(0.99, Number(e.target.value) || 0.80));
                  onChange({ ...policy, ml_col_threshold: Number(v.toFixed(2)) });
                }}
              />
              <span className="field-hint">Min softmax probability to infer an unknown CSV/TSV column.</span>
            </label>
          </div>
        )}
      </div>

      {/* 3. PII Categories */}
      <div className="policy-section">
        <div className="policy-section-row">
          <h4 className="policy-section-title">3. Active PII Redaction Categories</h4>
          <div className="policy-mini-actions">
            <button
              type="button"
              className="btn-link"
              onClick={() => onChange({ ...policy, redact_categories: [...ALL_PII_CATEGORIES] })}
            >
              Select all
            </button>
            <span>·</span>
            <button
              type="button"
              className="btn-link"
              onClick={() => onChange({ ...policy, redact_categories: ['NAME', 'MRN', 'PHONE', 'DOB', 'AADHAAR', 'ABHA'] })}
            >
              Core direct IDs
            </button>
          </div>
        </div>
        <div className="category-chip-grid">
          {ALL_PII_CATEGORIES.map((cat) => {
            const active = policy.redact_categories.includes(cat);
            return (
              <label key={cat} className={`cat-chip ${active ? 'is-on' : ''}`}>
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => toggleCategory(cat)}
                />
                <span>{cat}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* 4. Custom Field & Unseen Schema Rules */}
      <div className="policy-section">
        <h4 className="policy-section-title">4. Custom Fields &amp; Unseen Data Rules</h4>
        <div className="policy-custom-grid">
          <label className="field-group">
            <span className="field-label">Extra fields / columns to redact (comma-separated)</span>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. ward_clerk, bed_number, referral_source"
              value={policy.extra_redact_fields.join(', ')}
              onChange={(e) => onChange({ ...policy, extra_redact_fields: parseCsvList(e.target.value) })}
            />
            <span className="field-hint">Any matching CSV header, JSON key, or `Field:` label in notes becomes `[CUSTOM]`.</span>
          </label>

          <label className="field-group">
            <span className="field-label">Extra fields / columns to preserve (comma-separated)</span>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. study_arm, protocol_code, clinical_site"
              value={policy.extra_preserve_fields.join(', ')}
              onChange={(e) => onChange({ ...policy, extra_preserve_fields: parseCsvList(e.target.value) })}
            />
            <span className="field-hint">Exempt specific non-PII domain columns from automatic redaction.</span>
          </label>

          <label className="field-group">
            <span className="field-label">Custom literal terms / canaries to redact (comma-separated)</span>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. CANARY-991, WardSecretCode"
              value={policy.extra_redact_terms.join(', ')}
              onChange={(e) => onChange({ ...policy, extra_redact_terms: parseCsvList(e.target.value) })}
            />
            <span className="field-hint">Case-insensitive whole-word matches replaced with `[CUSTOM]`.</span>
          </label>

          <label className="field-group">
            <span className="field-label">Custom regex pattern to redact</span>
            <input
              type="text"
              className={`field-input mono-input ${regexError ? 'is-invalid' : ''}`}
              placeholder="e.g. EMP-\d{6}|BADGE-[A-Z]{2}\d{4}"
              value={policy.extra_redact_regex}
              onChange={(e) => onChange({ ...policy, extra_redact_regex: e.target.value })}
            />
            {regexError ? (
              <span className="field-error">{regexError}</span>
            ) : (
              <span className="field-hint">Python/JS-compatible regex redacted as `[CUSTOM]`.</span>
            )}
          </label>
        </div>
      </div>

      {/* 5. Release Secret / Key Rotation */}
      <div className="policy-section">
        <h4 className="policy-section-title">5. Release Key (`RAKSHA_SECRET`) &amp; Unlinkability</h4>
        <div className="secret-mode-row">
          <label className={`secret-option ${secretMode === 'default' ? 'is-selected' : ''}`}>
            <input
              type="radio"
              name="secret_mode"
              checked={secretMode === 'default'}
              onChange={() => onSecretModeChange('default')}
            />
            <span>
              <strong>Default server secret</strong>
              <small>Deterministic pseudonyms across repeated runs.</small>
            </span>
          </label>

          <label className={`secret-option ${secretMode === 'rotate' ? 'is-selected' : ''}`}>
            <input
              type="radio"
              name="secret_mode"
              checked={secretMode === 'rotate'}
              onChange={() => onSecretModeChange('rotate')}
            />
            <span>
              <strong>Rotate fresh ephemeral secret</strong>
              <small>Generates a one-time random key — all PSN IDs &amp; date shifts change.</small>
            </span>
          </label>

          <label className={`secret-option ${secretMode === 'custom' ? 'is-selected' : ''}`}>
            <input
              type="radio"
              name="secret_mode"
              checked={secretMode === 'custom'}
              onChange={() => onSecretModeChange('custom')}
            />
            <span>
              <strong>Custom synthetic test key</strong>
              <small>Test determinism with your own non-production key.</small>
            </span>
          </label>
        </div>

        {secretMode === 'custom' && (
          <div style={{ marginTop: '0.75rem', maxWidth: '420px' }}>
            <label className="field-group">
              <span className="field-label">Synthetic test key (min 4 chars — never logged or stored)</span>
              <input
                type="password"
                className="field-input"
                placeholder="Enter synthetic test secret…"
                value={customSecret}
                onChange={(e) => onCustomSecretChange(e.target.value)}
              />
            </label>
          </div>
        )}
      </div>
    </div>
  );
}
