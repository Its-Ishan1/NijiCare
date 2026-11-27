import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ErrorBanner } from './components/ErrorBanner';
import { Navbar } from './components/Navbar';
import { apiGet } from './hooks/useApi';
import { useRun } from './hooks/useRun';
import { Overview } from './pages/Overview';
import { Quarantine } from './pages/Quarantine';
import { Results } from './pages/Results';
import {
  DEFAULT_POLICY,
  type HealthResponse,
  type PageId,
  type PolicyConfig,
  type RunRequestPayload,
  type SecretMode,
} from './types';
import './App.css';

const RunScreen = lazy(() => import('./pages/RunScreen').then(m => ({ default: m.RunScreen })));
const FileViewer = lazy(() => import('./pages/FileViewer').then(m => ({ default: m.FileViewer })));
const PrivacyAudit = lazy(() => import('./pages/PrivacyAudit').then(m => ({ default: m.PrivacyAudit })));

export default function App() {
  const [page, setPage] = useState<PageId>('run');
  const [demoConfigured, setDemoConfigured] = useState<boolean | null>(null);
  const [defaultPolicy, setDefaultPolicy] = useState<PolicyConfig>(DEFAULT_POLICY);
  const [policy, setPolicy] = useState<PolicyConfig>(DEFAULT_POLICY);
  const [secretMode, setSecretMode] = useState<SecretMode>('default');
  const [customSecret, setCustomSecret] = useState('');

  const navigateRef = useRef<(p: PageId) => void>(() => {});

  const { runId, runDetail, files, history, error, isStarting, startRun, selectRun } = useRun(
    useCallback(() => {
      navigateRef.current('results');
    }, [])
  );

  navigateRef.current = setPage;

  const hasCompletedRun = runDetail?.status === 'completed';
  const isRunning = runDetail?.status === 'running';

  useEffect(() => {
    apiGet<HealthResponse>('/api/health')
      .then((h) => {
        setDemoConfigured(h.pipeline_available);
        if (h.default_policy) {
          setDefaultPolicy(h.default_policy);
          setPolicy(h.default_policy);
        }
      })
      .catch(() => setDemoConfigured(false));
  }, []);

  const handleStartRun = useCallback(
    async (payload: RunRequestPayload): Promise<boolean> => {
      return startRun({
        ...payload,
        policy: payload.policy ?? policy,
        secret_mode: payload.secret_mode ?? secretMode,
        custom_secret: payload.custom_secret ?? (secretMode === 'custom' ? customSecret : undefined),
      });
    },
    [startRun, policy, secretMode, customSecret]
  );

  return (
    <div className="app-shell">
      <Navbar
        activePage={page}
        onNavigate={setPage}
        hasCompletedRun={hasCompletedRun}
        isRunning={isRunning}
        demoConfigured={demoConfigured}
      />

      <main className="page-container">
        <Suspense fallback={<p role="status">Opening workspace…</p>}>
        {error && page !== 'run' && (
          <div style={{ marginBottom: '1rem' }}>
            <ErrorBanner
              message={error.message}
              requestId={error.requestId}
              onRetry={() => setPage('run')}
            />
          </div>
        )}

        {page === 'overview' && (
          <Overview
            onNavigate={setPage}
            demoConfigured={demoConfigured}
          />
        )}

        {page === 'run' && (
          <RunScreen
            runDetail={runDetail}
            history={history}
            policy={policy}
            defaultPolicy={defaultPolicy}
            onPolicyChange={setPolicy}
            secretMode={secretMode}
            onSecretModeChange={setSecretMode}
            customSecret={customSecret}
            onCustomSecretChange={setCustomSecret}
            error={error}
            onStartRun={handleStartRun}
            onSelectRun={selectRun}
            onNavigate={setPage}
            isStarting={isStarting}
          />
        )}

        {page === 'results' && (
          <Results
            runDetail={runDetail}
            history={history}
            onSelectRun={selectRun}
            onNavigate={setPage}
          />
        )}

        {page === 'files' && (
          <FileViewer runId={runId} files={files} onNavigate={setPage} />
        )}

        {page === 'quarantine' && (
          <Quarantine files={files} onNavigate={setPage} />
        )}

        {page === 'audit' && (
          <PrivacyAudit runDetail={runDetail} />
        )}
        </Suspense>
      </main>

      <footer className="app-footer">
        <div className="app-footer-inner">
          <span>
            <strong>Secret Wards v5 · Hybrid Rules + ML</strong> — Offline hospital research data privacy firewall ·
            Yugaantar DevForge Track 3
          </span>
          <span>
            100% local CPU execution · Python stdlib-only core · RAKSHA_SECRET never sent to browser
          </span>
        </div>
      </footer>
    </div>
  );
}
