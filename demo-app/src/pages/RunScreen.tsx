import { useState } from 'react';
import { FileUpload } from '../components/FileUpload';
import { ErrorBanner } from '../components/ErrorBanner';
import { PipelineStages } from '../components/PipelineStages';
import { PolicyPanel } from '../components/PolicyPanel';
import type { ApiError } from '../hooks/useApi';
import type {
  PageId,
  PolicyConfig,
  RunDetail,
  RunHistoryItem,
  RunRequestPayload,
  SecretMode,
} from '../types';
import './RunScreen.css';

interface RunScreenProps {
  runDetail: RunDetail | null;
  history: RunHistoryItem[];
  policy: PolicyConfig;
  defaultPolicy: PolicyConfig;
  onPolicyChange: (next: PolicyConfig) => void;
  secretMode: SecretMode;
  onSecretModeChange: (mode: SecretMode) => void;
  customSecret: string;
  onCustomSecretChange: (val: string) => void;
  error: ApiError | null;
  onStartRun: (payload: RunRequestPayload) => Promise<boolean>;
  onSelectRun: (runId: string) => Promise<void>;
  onNavigate: (page: PageId) => void;
  isStarting: boolean;
}

export function RunScreen({
  runDetail,
  history,
  policy,
  defaultPolicy,
  onPolicyChange,
  secretMode,
  onSecretModeChange,
  customSecret,
  onCustomSecretChange,
  error,
  onStartRun,
  onSelectRun,
  onNavigate,
  isStarting,
}: RunScreenProps) {
  const [showPolicy, setShowPolicy] = useState(false);
  const isRunning = runDetail?.status === 'running';
  const isCompleted = runDetail?.status === 'completed';

  return (
    <div className="run-layout">
      {/* Header */}
      <div className="run-header">
        <div>
          <h2 className="section-title" style={{ marginTop: '0.3rem' }}>
            Release workbench
          </h2>
          <p className="section-subtitle">
            Select the files or folder you want to test. Each run produces sanitized files and a report.
          </p>
        </div>
        <div className="run-header-right">
          <span className="capability-chip">Offline CPU</span>
          <span className="capability-chip">No LLM</span>
        </div>
      </div>

      {error && <ErrorBanner message={error.message} requestId={error.requestId} />}

      <FileUpload busy={isStarting || isRunning}
        onRun={files => onStartRun({ source: 'custom', files, label: 'Upload (' + files.length + (files.length === 1 ? ' file)' : ' files)') })} />

      {/* Policy & Field Settings Card */}
      <section className="card">
        <div className="policy-collapse-bar">
          <div>
            <strong>Privacy Policy &amp; Custom Field Controls</strong>
            <span className="field-hint" style={{ marginLeft: '0.6rem' }}>
              Age band {policy.age_band_years}–{policy.age_band_max_years}y (k={policy.age_k_anonymity}) · Shift ±{policy.date_shift_max_days}d · {policy.redact_categories.length} PII types · Secret: {secretMode}
            </span>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowPolicy((v) => !v)}
          >
            {showPolicy ? 'Hide settings' : 'Show settings'}
          </button>
        </div>

        {showPolicy && (
          <div style={{ marginTop: '1.1rem' }}>
            <PolicyPanel
              policy={policy}
              onChange={onPolicyChange}
              secretMode={secretMode}
              onSecretModeChange={onSecretModeChange}
              customSecret={customSecret}
              onCustomSecretChange={onCustomSecretChange}
              defaultPolicy={defaultPolicy}
            />
          </div>
        )}
      </section>

      {/* Live Pipeline Stage Progress */}
      {(isRunning || isCompleted) && runDetail && (
        <div className="card">
          <div className="run-stages-head">
            <div>
              <strong>Latest run: {runDetail.label || runDetail.run_id}</strong>
              <span className="mono" style={{ marginLeft: '0.6rem' }}>{runDetail.run_id}</span>
            </div>
            {isCompleted && <span className="run-complete-badge">Completed in {runDetail.timing?.seconds?.toFixed(2) ?? '0.00'} s</span>}
          </div>
          <div style={{ marginTop: '1rem' }}>
            <PipelineStages activeStageIndex={isCompleted ? 5 : 2} isComplete={isCompleted} />
          </div>
          {isCompleted && (
            <div className="run-results-actions" style={{ marginTop: '1rem' }}>
              <button type="button" className="btn btn-primary" onClick={() => onNavigate('results')}>
                View Results Dashboard →
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => onNavigate('files')}>
                Inspect Before / After Files
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => onNavigate('quarantine')}>
                Quarantine Log ({runDetail.counts?.files_quarantined ?? 0})
              </button>
            </div>
          )}
        </div>
      )}

      {/* Session Run History */}
      {history.length > 0 && (
        <section className="card">
          <div className="section-kicker">Session History</div>
          <h3 style={{ fontSize: '1.05rem', marginBottom: '0.75rem' }}>Switch between runs</h3>
          <div className="history-list">
            {history.map((h) => (
              <button
                key={h.run_id}
                type="button"
                className={`history-item ${runDetail?.run_id === h.run_id ? 'is-current' : ''}`}
                onClick={() => {
                  void onSelectRun(h.run_id).then(() => onNavigate('results'));
                }}
              >
                <div>
                  <strong>{h.label || h.source}</strong>
                  <span className="mono" style={{ marginLeft: '0.5rem' }}>{h.run_id}</span>
                </div>
                <div className="history-meta">
                  <span>{h.counts ? `${h.counts.files_sanitized} sanitized / ${h.counts.files_quarantined} quarantined` : h.status}</span>
                  <span className="preset-chip">key: {h.secret_mode}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
