import './components.css';

interface StatCardProps {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  tone?: 'default' | 'highlight' | 'saffron';
}

export function StatCard({ label, value, hint, tone = 'default' }: StatCardProps) {
  const isUnmeasured = value === null || value === undefined || value === '';
  const toneClass = tone === 'default' ? '' : tone;
  return (
    <div className={`stat-card ${toneClass}`}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${isUnmeasured ? 'is-muted' : ''}`}>
        {isUnmeasured ? 'Not measured' : value}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
