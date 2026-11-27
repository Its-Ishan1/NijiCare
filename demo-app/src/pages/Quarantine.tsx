import { StatusChip } from '../components/StatusChip';
import type { PageId, PipelineFileEntry } from '../types';
import './Quarantine.css';

interface QuarantineProps {
  files: PipelineFileEntry[];
  onNavigate: (page: PageId) => void;
}

const REASON_LABELS: Record<string, string> = {
  unsupported_format: 'Unsupported file format (e.g. binary, PDF, image)',
  empty_file: 'File was empty',
  undecodable_text: 'File could not be decoded as UTF-8 text',
  mislabeled_table: 'Table structure did not match expected schema',
  ambiguous_table_shape: 'Table column layout was ambiguous',
  duplicate_json_key: 'JSON file contained duplicate keys',
  invalid_json_number: 'JSON file contained an out-of-range number',
  unresolved_fhir_reference: 'FHIR Bundle contained an unresolved internal reference',
  unsupported_fhir_patient_count: 'FHIR Bundle contained more than one Patient resource',
  invalid_fhir_date: 'FHIR Bundle contained an invalid date, date-time, or timestamp',
};

export function Quarantine({ files, onNavigate }: QuarantineProps) {
  const quarantined = files.filter((f) => f.status === 'quarantined');

  if (files.length === 0) {
    return (
      <div className="card">
        <p className="section-subtitle" style={{ padding: '0.5rem 0' }}>
          No completed run yet.{' '}
          <button type="button" className="btn btn-secondary" style={{ marginLeft: '0.75rem' }} onClick={() => onNavigate('run')}>
            Go to Run Demo →
          </button>
        </p>
      </div>
    );
  }

  return (
    <div className="quarantine-layout">
      <div className="section-heading">
        <div className="section-kicker">Safety routing</div>
        <h2 className="section-title">Quarantine log</h2>
        <p className="section-subtitle" style={{ marginTop: '0.4rem' }}>
          Files that could not be safely processed are listed here by their SHA-256 identifier.
          Original filenames are intentionally omitted as they may contain patient names.
          Raw quarantined content is never displayed.
        </p>
      </div>

      {quarantined.length === 0 ? (
        <div className="card quarantine-empty">
          <div className="qe-icon" aria-hidden="true">✓</div>
          <div>
            <strong>No quarantined files</strong>
            <p>All {files.length} input {files.length === 1 ? 'file' : 'files'} were processed successfully.</p>
            <p style={{ marginTop: '0.4rem', fontSize: '0.84rem', color: 'var(--text-muted)' }}>
              The synthetic demo inputs contain only plain text and CSV, so nothing triggers quarantine.
              Add a <span className="mono">.jpg</span>, <span className="mono">.pdf</span>, or{' '}
              <span className="mono">.dat</span> binary to the input folder to see quarantine in action.
            </p>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="clinical-table-wrap">
            <table className="clinical-table" aria-label="Quarantined files">
              <thead>
                <tr>
                  <th>SHA-256 (truncated)</th>
                  <th>Quarantine reason</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {quarantined.map((file) => (
                  <tr key={file.input_sha256}>
                    <td>
                      <span className="mono q-sha">{file.input_sha256.slice(0, 20)}…</span>
                    </td>
                    <td>
                      {file.reason
                        ? REASON_LABELS[file.reason] || file.reason
                        : 'Unspecified reason'}
                    </td>
                    <td>
                      <StatusChip status="quarantined" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card quarantine-info">
        <h3 style={{ fontSize: '1rem', marginBottom: '0.6rem' }}>About quarantine routing</h3>
        <p>
          Files are quarantined rather than discarded to give operators full visibility into what was not
          released. The pipeline never copies raw quarantined content into the sanitized output directory.
        </p>
        <ul className="q-reason-list">
          {Object.entries(REASON_LABELS).map(([key, label]) => (
            <li key={key}>
              <span className="mono q-reason-key">{key}</span>
              <span>{label}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
