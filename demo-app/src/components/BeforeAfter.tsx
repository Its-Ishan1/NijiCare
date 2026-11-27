import './components.css';

interface BeforeAfterProps {
  fileName: string;
  originalName?: string;
  beforeContent: string;
  afterContent: string;
}

export function BeforeAfter({ fileName, originalName, beforeContent, afterContent }: BeforeAfterProps) {
  const renamed = originalName && originalName !== fileName;
  return (
    <div>
      <div className="before-after-grid">
        <section className="diff-panel" aria-label="Original input">
          <div className="diff-panel-head">
            <span className="diff-panel-title">Original input — {originalName || fileName}</span>
            <span className="diff-tag fictional">Original input</span>
          </div>
          <pre className="diff-pre">{beforeContent}</pre>
        </section>

        <section className="diff-panel is-after" aria-label="Sanitized output">
          <div className="diff-panel-head">
            <span className="diff-panel-title">Sanitized output — {fileName}</span>
            <span className="diff-tag sanitized">Sanitized output</span>
          </div>
          <pre className="diff-pre">{afterContent}</pre>
        </section>
      </div>

      <div className="diff-highlights">
        <h4>What changed vs. what was preserved</h4>
        <ul>
          <li>
            Direct identifiers (patient names across English/Hindi/Hinglish, chart IDs/MRNs, DOBs, phone numbers, Aadhaar/ABHA, PAN, email, addresses, and custom fields) are replaced with typed tags (<span className="mono">[NAME]</span>, <span className="mono">[MRN]</span>, <span className="mono">[PHONE]</span>, <span className="mono">[CUSTOM]</span>) or stable HMAC pseudonyms (<span className="mono">PSN-...</span>).
          </li>
          <li>
            Clinical utility (clinician names like <span className="mono">Dr. ...</span>, diagnoses, ICD codes, medications, doses, vitals, lab results, and complaints) is preserved intact.
          </li>
          <li>
            Exact ages are generalized to truthful adaptive bands, and clinical dates are shifted deterministically per patient so stay durations and event intervals remain exact.
          </li>
          {renamed && (
            <li>
              <strong>Filename sanitized:</strong> Original filename <span className="mono">{originalName}</span> contained identifying text and was hashed to <span className="mono">{fileName}</span>.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
