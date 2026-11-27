import type { PageId } from '../types';
import './Navbar.css';

interface NavbarProps {
  activePage: PageId;
  onNavigate: (page: PageId) => void;
  hasCompletedRun: boolean;
  isRunning: boolean;
  demoConfigured: boolean | null;
}

const NAV_ITEMS: Array<{ id: PageId; label: string; requiresRun?: boolean }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'run', label: 'Workbench' },
  { id: 'results', label: 'Results', requiresRun: true },
  { id: 'files', label: 'File Viewer', requiresRun: true },
  { id: 'quarantine', label: 'Quarantine', requiresRun: true },
  { id: 'audit', label: 'Privacy & Audit' },
];

export function Navbar({
  activePage,
  onNavigate,
  hasCompletedRun,
  isRunning,
  demoConfigured,
}: NavbarProps) {
  return (
    <header className="sw-header">
      <div className="sw-nav-inner">
        <button
          type="button"
          className="sw-brand"
          onClick={() => onNavigate('overview')}
        >
          <span className="sw-brand-icon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="18" height="18" rx="4" stroke="currentColor" strokeWidth="2" />
              <path d="M12 7.5V16.5M7.5 12H16.5" stroke="#0D9488" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          </span>
          <span className="sw-brand-text">
            <strong>Secret Wards</strong>
            <small>Clinical Data Privacy Console</small>
          </span>
        </button>

        <nav className="sw-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const disabled = item.requiresRun && !hasCompletedRun;
            const isActive = activePage === item.id;
            return (
              <button
                key={item.id}
                type="button"
                disabled={disabled}
                aria-current={isActive ? 'page' : undefined}
                className={`sw-nav-btn ${isActive ? 'is-active' : ''}`}
                onClick={() => onNavigate(item.id)}
              >
                {item.label}
                {item.id === 'run' && isRunning && (
                  <span className="sw-nav-dot" aria-label="Running" />
                )}
              </button>
            );
          })}
        </nav>

        <div className="sw-header-status">
          <span
            className={`sw-health-pill ${
              demoConfigured === true
                ? 'is-ready'
                : demoConfigured === false
                ? 'is-warn'
                : ''
            }`}
            title="Local Python pipeline adapter status"
          >
            <span className="sw-health-dot" aria-hidden="true" />
            {demoConfigured === null
              ? 'Connecting…'
              : demoConfigured
              ? 'Pipeline ready'
              : 'Adapter offline'}
          </span>
        </div>
      </div>
    </header>
  );
}
