import { useCallback, useEffect, useMemo, useState } from 'react';
import { BeforeAfter } from '../components/BeforeAfter';
import { StatusChip } from '../components/StatusChip';
import { apiGet } from '../hooks/useApi';
import type { PageId, PipelineFileEntry } from '../types';
import './FileViewer.css';

interface FileViewerProps {
  runId: string | null;
  files: PipelineFileEntry[];
  onNavigate: (page: PageId) => void;
}

interface FileContentResult {
  path: string;
  content: string;
}

interface BeforeContentResult {
  sha256: string;
  name: string;
  content: string;
}

export function FileViewer({ runId, files, onNavigate }: FileViewerProps) {
  const sanitizedFiles = useMemo(
    () => files.filter((f) => f.status === 'sanitized' && f.output),
    [files]
  );
  const [selectedOutput, setSelectedOutput] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [beforeData, setBeforeData] = useState<BeforeContentResult | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [contentError, setContentError] = useState<string | null>(null);
  const [showBeforeAfter, setShowBeforeAfter] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (sanitizedFiles.length > 0 && (!selectedOutput || !sanitizedFiles.some((f) => f.output === selectedOutput))) {
      setSelectedOutput(sanitizedFiles[0].output!);
    }
  }, [sanitizedFiles, selectedOutput]);

  const selectedFile = files.find((f) => f.output === selectedOutput);

  const loadFile = useCallback(
    async (outputPath: string, entry?: PipelineFileEntry) => {
      if (!runId) return;
      setLoadingContent(true);
      setContentError(null);
      setFileContent(null);
      setBeforeData(null);
      try {
        const result = await apiGet<FileContentResult>(
          `/api/runs/${encodeURIComponent(runId)}/file?path=${encodeURIComponent(outputPath)}`
        );
        setFileContent(result.content);
        if (entry?.has_before && entry.input_sha256) {
          try {
            const bef = await apiGet<BeforeContentResult>(
              `/api/runs/${encodeURIComponent(runId)}/before?sha256=${encodeURIComponent(entry.input_sha256)}`
            );
            setBeforeData(bef);
          } catch {
            setBeforeData(null);
          }
        }
      } catch {
        setContentError('Could not load sanitized file content.');
      } finally {
        setLoadingContent(false);
      }
    },
    [runId]
  );

  useEffect(() => {
    if (selectedOutput) {
      void loadFile(selectedOutput, selectedFile);
    }
  }, [selectedOutput, selectedFile, loadFile]);

  const visibleFiles = useMemo(() => {
    const q = filterText.trim().toLowerCase();
    if (!q) return files;
    return files.filter(
      (f) =>
        (f.output || '').toLowerCase().includes(q) ||
        f.input_sha256.toLowerCase().includes(q) ||
        f.status.toLowerCase().includes(q)
    );
  }, [files, filterText]);

  if (!runId || files.length === 0) {
    return (
      <div className="card">
        <p className="section-subtitle" style={{ padding: '0.5rem 0' }}>
          No completed run yet.{' '}
          <button type="button" className="btn btn-secondary" style={{ marginLeft: '0.75rem' }} onClick={() => onNavigate('run')}>
            Open Workbench →
          </button>
        </p>
      </div>
    );
  }

  const selectedName = selectedOutput ? selectedOutput.replace(/^sanitized\//, '') : null;

  const handleCopy = async () => {
    if (!fileContent) return;
    try {
      await navigator.clipboard.writeText(fileContent);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard unavailable
    }
  };

  return (
    <div className="fv-layout">
      {/* Sidebar */}
      <aside className="fv-sidebar card" aria-label="File list">
        <div className="fv-sidebar-head">
          <strong>Output files</strong>
          <span className="fv-file-count">{sanitizedFiles.length} / {files.length}</span>
        </div>
        <div style={{ padding: '0 0 0.65rem 0' }}>
          <input
            type="search"
            className="field-input"
            placeholder="Filter files…"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
        </div>
        <ul className="fv-file-list">
          {visibleFiles.map((file) => {
            const name = file.output
              ? file.output.replace(/^sanitized\//, '')
              : file.input_sha256.slice(0, 10) + '…';
            const isSelected = file.output === selectedOutput;
            return (
              <li key={file.input_sha256}>
                <button
                  type="button"
                  className={`fv-file-btn ${isSelected ? 'is-active' : ''} ${file.status !== 'sanitized' ? 'is-disabled' : ''}`}
                  disabled={file.status !== 'sanitized'}
                  onClick={() => file.output && setSelectedOutput(file.output)}
                >
                  <span className="fv-file-icon" aria-hidden="true">
                    {file.status === 'sanitized' ? '📄' : '🚫'}
                  </span>
                  <span className="fv-file-name">{name}</span>
                  <StatusChip status={file.status} />
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* Main viewer */}
      <main className="fv-main">
        {selectedName && (
          <div className="fv-viewer-head card">
            <div className="fv-viewer-title">
              <span className="fv-path mono">{selectedOutput}</span>
              {selectedFile && <StatusChip status={selectedFile.status} />}
            </div>
            <div className="fv-viewer-actions">
              {beforeData && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowBeforeAfter((v) => !v)}
                >
                  {showBeforeAfter ? 'Sanitized only' : 'Show before / after'}
                </button>
              )}
              {fileContent && (
                <button type="button" className="btn btn-secondary" onClick={() => void handleCopy()}>
                  {copied ? '✓ Copied' : 'Copy'}
                </button>
              )}
              {runId && selectedOutput && (
                <a
                  href={`/api/runs/${encodeURIComponent(runId)}/file?path=${encodeURIComponent(selectedOutput)}&download=1`}
                  download={selectedName}
                  className="btn btn-secondary"
                >
                  ↓ Download raw
                </a>
              )}
            </div>
          </div>
        )}

        {loadingContent && (
          <div className="fv-loading card">
            <div className="fv-spinner" aria-hidden="true" />
            Loading sanitized content…
          </div>
        )}

        {contentError && (
          <div className="fv-error card">
            <strong>Error:</strong> {contentError}
          </div>
        )}

        {!loadingContent && !contentError && fileContent !== null && (
          <>
            {showBeforeAfter && beforeData ? (
              <div className="card">
                <BeforeAfter
                  fileName={selectedName || ''}
                  originalName={beforeData.name}
                  beforeContent={beforeData.content}
                  afterContent={fileContent}
                />
              </div>
            ) : (
              <div className="card fv-content-card">
                <div className="fv-content-head">
                  <span className="fv-content-label">Sanitized output</span>
                </div>
                <pre className="fv-pre">{fileContent}</pre>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
