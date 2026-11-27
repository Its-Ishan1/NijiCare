import { useMemo, useState } from 'react';
import type { RecordEntry } from '../types';
import './components.css';

interface LinkageViewProps {
  records: RecordEntry[];
}

export function LinkageView({ records }: LinkageViewProps) {
  const [query, setQuery] = useState('');

  const sortedGroups = useMemo(() => {
    const groups = new Map<string, RecordEntry[]>();
    for (const entry of records) {
      if (!entry.patient) continue;
      const list = groups.get(entry.patient) ?? [];
      list.push(entry);
      groups.set(entry.patient, list);
    }
    const q = query.trim().toLowerCase();
    return Array.from(groups.entries())
      .filter(([psn, entries]) => {
        if (!q) return true;
        return (
          psn.toLowerCase().includes(q) ||
          entries.some((e) => e.file.toLowerCase().includes(q) || e.loc.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => b[1].length - a[1].length);
  }, [records, query]);

  const unlinkedCount = records.filter((r) => !r.patient).length;

  if (records.length === 0) {
    return (
      <p className="section-subtitle">
        No records were emitted in <span className="mono">records.jsonl</span>.
      </p>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <input
          type="search"
          className="field-input"
          style={{ maxWidth: '340px' }}
          placeholder="Filter by PSN pseudonym, filename, or locator…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="stat-hint">
          {sortedGroups.length} unique {sortedGroups.length === 1 ? 'patient cluster' : 'patient clusters'}
          {unlinkedCount > 0 ? ` · ${unlinkedCount} unlinked / abstained` : ''}
        </span>
      </div>

      {sortedGroups.length === 0 ? (
        <p className="section-subtitle">No matching pseudonym clusters.</p>
      ) : (
        <div className="linkage-grid">
          {sortedGroups.map(([pseudonym, entries]) => (
            <div key={pseudonym} className="linkage-group">
              <div className="linkage-group-head">
                <span className="psn-badge">{pseudonym}</span>
                <span className="stat-hint">
                  {entries.length} linked {entries.length === 1 ? 'record' : 'records'}
                </span>
              </div>
              <ul className="linkage-records">
                {entries.map((rec, idx) => (
                  <li key={`${rec.file}-${rec.loc}-${idx}`} className="linkage-record-item">
                    <span className="mono">{rec.file}</span>
                    <span className="linkage-loc">{rec.loc}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
