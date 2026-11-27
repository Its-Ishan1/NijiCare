import './components.css';

interface StatusChipProps {
  status: 'sanitized' | 'quarantined' | 'suppressed' | 'running' | 'completed' | 'failed';
}

const LABELS: Record<StatusChipProps['status'], string> = {
  sanitized: 'Sanitized',
  quarantined: 'Quarantined',
  suppressed: 'Suppressed',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
};

export function StatusChip({ status }: StatusChipProps) {
  return <span className={`status-chip ${status}`}>{LABELS[status]}</span>;
}
