import { useEffect, useRef, useState, type DragEvent } from 'react';
import { ErrorBanner } from '../components/ErrorBanner';
import { PipelineStages } from '../components/PipelineStages';
import { PolicyPanel } from '../components/PolicyPanel';
import type { ApiError } from '../hooks/useApi';
import type {
  CustomFileInput,
  InputTabId,
  PageId,
  PolicyConfig,
  PresetInfo,
  RunDetail,
  RunHistoryItem,
  RunRequestPayload,
  SecretMode,
} from '../types';
import './RunScreen.css';

interface RunScreenProps {
  runDetail: RunDetail | null;
  history: RunHistoryItem[];
  presets: PresetInfo[];
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

interface BuilderPatient {
  id: string;
  patientName: string;
  uhid: string;
  dob: string;
  age: string;
  sex: string;
  phone: string;
  nationalId: string;
  district: string;
  address: string;
  admitDate: string;
  dischargeDate: string;
  doctor: string;
  diagnosis: string;
  medication: string;
  notes: string;
  customFieldKey: string;
  customFieldVal: string;
}

const SAMPLE_BUILDER_PATIENT: BuilderPatient = {
  id: 'p-1',
  patientName: 'Aarav Mishra',
  uhid: 'HOSP-2026-90112',
  dob: '1988-05-12',
  age: '38',
  sex: 'M',
  phone: '+91 98123-45678',
  nationalId: '14-4411-8822-3399',
  district: 'Lucknow',
  address: 'House 22, Gomti Nagar, 226010',
  admitDate: '2026-07-04',
  dischargeDate: '2026-07-11',
  doctor: 'Dr. Meenakshi Rao',
  diagnosis: 'Dengue fever (A90)',
  medication: 'Paracetamol 650 mg TID, IV RL 100 mL/hr',
  notes: 'Platelet count 84,000/uL, BP 118/76 mmHg. Stable on discharge.',
  customFieldKey: 'ward_clerk',
  customFieldVal: 'Clerk-Ravi-07',
};

const PASTE_TEMPLATES: Record<string, { filename: string; content: string }> = {
  note: {
    filename: 'clinical_note.txt',
    content: `Discharge Summary (Synthetic)
Patient Name: Rajeshwar Tiwari   UHID: KGM-2026-55201
Age/Sex: 47 Y / M   District: Barabanki
DOB: 1979-03-18   Mobile: +91 98761-23450   Aadhaar: 4123-5678-9012
Admit Date: 2026-08-10   Discharge Date: 2026-08-16
Consultant: Dr. Kavita Joshi
C/O: persistent cough and fever for 5 days
Vitals: BP 126/82 mmHg, SpO2 97%, Temp 100.4 F
Rx: Azithromycin 500 mg OD x 5 days, Paracetamol 650 mg SOS`,
  },
  csv: {
    filename: 'ward_export.csv',
    content: `Patient Name,UHID,DOB,Age,District,Mobile,Admit Date,Discharge Date,Doctor,Diagnosis,Rx
Sita Verma,SW-100201,1986-04-12,40,Sitapur,9811223344,2026-05-01,2026-05-06,Dr. Anil Sen,Enteric fever (A01.0),Cefixime 200 mg BD
सीता वर्मा,SW-100202,1986-04-12,40,Sitapur,+91 98112-23344,2026-05-08,2026-05-10,Dr. Anil Sen,Follow-up,ORS + Probiotic
Sita Verma,SW-100203,1994-11-20,31,Sitapur,9899887766,2026-05-03,2026-05-05,Dr. Anil Sen,Acute URI (J06.9),Cetirizine 10 mg OD`,
  },
  json: {
    filename: 'opd_records.json',
    content: JSON.stringify(
      {
        clinic: 'City General OPD',
        visits: [
          {
            visit_id: 'OP-88412',
            patient: {
              name: 'Neha Deshmukh',
              id: 'CG-2026-88412',
              dob: '1991-09-02',
              age_sex: '34 Y / F',
              phone: '9765012345',
              email: 'neha.d.synth@example.test',
              address: { line: '18 MG Road', district: 'Hardoi', pincode: '241001' },
            },
            consultant: 'Dr. Rohit Kulkarni',
            visit_date: '2026-07-19',
            diagnosis: 'Iron deficiency anemia (D50.9)',
            rx: 'Ferrous sulfate 200 mg BD',
          },
        ],
      },
      null,
      2
    ),
  },
};

function csvEscape(v: string): string {
  if (/[",\r\n]/.test(v)) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

function readFileAsCustomInput(file: File): Promise<CustomFileInput> {
  const lower = file.name.toLowerCase();
  const inputName = file.webkitRelativePath || file.name;
  const isText = lower.endsWith('.csv') || lower.endsWith('.tsv') || lower.endsWith('.json') || lower.endsWith('.txt');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    if (isText) {
      reader.onload = () =>
        resolve({
          name: inputName,
          content: String(reader.result ?? ''),
          encoding: 'utf-8',
          sizeBytes: file.size,
        });
      reader.readAsText(file);
    } else {
      reader.onload = () => {
        const dataUrl = String(reader.result ?? '');
        const b64 = dataUrl.includes(',') ? dataUrl.split(',', 2)[1] : dataUrl;
        resolve({
          name: inputName,
          content: b64,
          encoding: 'base64',
          sizeBytes: file.size,
        });
      };
      reader.readAsDataURL(file);
    }
  });
}

export function RunScreen({
  runDetail,
  history,
  presets,
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
  const [activeTab, setActiveTab] = useState<InputTabId>('preset');
  const [runLabel, setRunLabel] = useState('');
  const [showPolicy, setShowPolicy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // Tab 1: Upload files
  const [uploadedFiles, setUploadedFiles] = useState<CustomFileInput[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  // Tab 2: Paste / Write text
  const [pasteFilename, setPasteFilename] = useState('clinical_note.txt');
  const [pasteContent, setPasteContent] = useState(PASTE_TEMPLATES.note.content);
  const [stagedPasted, setStagedPasted] = useState<CustomFileInput[]>([]);

  // Tab 3: Patient Form Builder
  const [builderForm, setBuilderForm] = useState<BuilderPatient>(SAMPLE_BUILDER_PATIENT);
  const [builderRecords, setBuilderRecords] = useState<BuilderPatient[]>([SAMPLE_BUILDER_PATIENT]);
  const [includeNotesForBuilder, setIncludeNotesForBuilder] = useState(true);

  // Tab 4: Preset selector
  const [selectedPreset, setSelectedPreset] = useState('ward_transfer');
  const [seedOverride, setSeedOverride] = useState<string | null>(null);
  const preset = presets.find((item) => item.id === selectedPreset);
  const seed = seedOverride ?? String(preset?.sample_seed ?? '');

  useEffect(() => {
    if (presets.length > 0 && !presets.some((p) => p.id === selectedPreset)) {
      setSelectedPreset(presets[0].id);
    }
  }, [presets, selectedPreset]);

  const isRunning = runDetail?.status === 'running';
  const isCompleted = runDetail?.status === 'completed';

  const handleFilesSelected = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setLocalError(null);
    try {
      const converted = await Promise.all(Array.from(fileList).map(readFileAsCustomInput));
      const byName = new Map(uploadedFiles.map((f) => [f.name, f]));
      for (const f of converted) byName.set(f.name, f);
      if (byName.size > 250) {
        setLocalError('A run can contain up to 250 files. Choose a smaller folder or split it into batches.');
        return;
      }
      setUploadedFiles(Array.from(byName.values()));
      if (fileInputRef.current) fileInputRef.current.value = '';
      if (folderInputRef.current) folderInputRef.current.value = '';
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : 'Failed to read selected files.');
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    void handleFilesSelected(e.dataTransfer.files);
  };

  const addPastedToBatch = () => {
    const cleanName = pasteFilename.trim();
    if (!cleanName) {
      setLocalError('Please enter a filename (e.g. note.txt, roster.csv, bundle.json).');
      return;
    }
    if (!pasteContent.trim()) {
      setLocalError('Please enter some text content before adding.');
      return;
    }
    setLocalError(null);
    const entry: CustomFileInput = {
      name: cleanName,
      content: pasteContent,
      encoding: 'utf-8',
      sizeBytes: new Blob([pasteContent]).size,
    };
    setStagedPasted((prev) => [...prev.filter((f) => f.name !== cleanName), entry]);
  };

  const addBuilderRecord = () => {
    if (!builderForm.patientName.trim() || !builderForm.uhid.trim()) {
      setLocalError('Patient Name and UHID/MRN are required to add a record.');
      return;
    }
    setLocalError(null);
    const rec: BuilderPatient = { ...builderForm, id: `p-${Date.now()}` };
    setBuilderRecords((prev) => [...prev, rec]);
  };

  const buildFilesFromBuilder = (): CustomFileInput[] => {
    const extraKeys = Array.from(
      new Set(builderRecords.map((r) => r.customFieldKey.trim()).filter(Boolean))
    );
    const headers = [
      'Patient Name',
      'UHID',
      'DOB',
      'Age',
      'Sex',
      'Mobile',
      'ABHA ID',
      'District',
      'Address',
      'Admit Date',
      'Discharge Date',
      'Consultant',
      'Diagnosis',
      'Rx',
      ...extraKeys,
    ];
    const csvLines = [headers.map(csvEscape).join(',')];
    for (const r of builderRecords) {
      const base = [
        r.patientName,
        r.uhid,
        r.dob,
        r.age,
        r.sex,
        r.phone,
        r.nationalId,
        r.district,
        r.address,
        r.admitDate,
        r.dischargeDate,
        r.doctor,
        r.diagnosis,
        r.medication,
      ];
      for (const ek of extraKeys) {
        base.push(r.customFieldKey.trim() === ek ? r.customFieldVal : '');
      }
      csvLines.push(base.map(csvEscape).join(','));
    }
    const out: CustomFileInput[] = [
      { name: 'patient_registry.csv', content: csvLines.join('\n') + '\n', encoding: 'utf-8' },
    ];
    if (includeNotesForBuilder) {
      builderRecords.forEach((r, idx) => {
        const extraLine = r.customFieldKey.trim()
          ? `\n${r.customFieldKey.trim()}: ${r.customFieldVal}`
          : '';
        const noteText = [
          `Clinical Discharge Note`,
          `Patient Name: ${r.patientName}   UHID: ${r.uhid}`,
          `Age/Sex: ${r.age} Y / ${r.sex}   District: ${r.district}`,
          `DOB: ${r.dob}   Mobile: ${r.phone}   ABHA: ${r.nationalId}`,
          `Address: ${r.address}`,
          `Admit Date: ${r.admitDate}   Discharge Date: ${r.dischargeDate}`,
          `Consultant: ${r.doctor}`,
          `Diagnosis: ${r.diagnosis}`,
          `Rx: ${r.medication}`,
          `Notes: ${r.notes}${extraLine}`,
        ].join('\n');
        out.push({
          name: `note_${idx + 1}_${r.uhid}.txt`,
          content: noteText + '\n',
          encoding: 'utf-8',
        });
      });
    }
    return out;
  };

  const handleExecute = async () => {
    setLocalError(null);
    if (secretMode === 'custom' && customSecret.trim().length < 4) {
      setLocalError('Custom synthetic test key must be at least 4 characters.');
      return;
    }

    let payload: RunRequestPayload;

    if (activeTab === 'preset') {
      if (!preset) {
        setLocalError('No dataset selected. Choose an available dataset or upload a file.');
        return;
      }
      if (preset.sample_seed != null && (!/^\d{1,10}$/.test(seed) || Number(seed) > 2147483647)) {
        setLocalError('Enter a whole-number seed from 0 to 2147483647.');
        return;
      }
      payload = {
        source: 'preset',
        preset_id: selectedPreset,
        seed: preset.sample_seed != null ? Number(seed) : undefined,
        label: runLabel.trim() || undefined,
        policy,
        secret_mode: secretMode,
        custom_secret: secretMode === 'custom' ? customSecret.trim() : undefined,
      };
    } else if (activeTab === 'upload') {
      if (uploadedFiles.length === 0) {
        setLocalError('Drop or select at least one file to run the pipeline.');
        return;
      }
      payload = {
        source: 'custom',
        label: runLabel.trim() || `Uploaded (${uploadedFiles.length} files)`,
        files: uploadedFiles.map(({ name, content, encoding }) => ({ name, content, encoding })),
        policy,
        secret_mode: secretMode,
        custom_secret: secretMode === 'custom' ? customSecret.trim() : undefined,
      };
    } else if (activeTab === 'paste') {
      const filesToSend =
        stagedPasted.length > 0
          ? stagedPasted
          : pasteContent.trim()
          ? [{ name: pasteFilename.trim() || 'pasted_note.txt', content: pasteContent, encoding: 'utf-8' as const }]
          : [];
      if (filesToSend.length === 0) {
        setLocalError('Paste text or add at least one file to the batch.');
        return;
      }
      payload = {
        source: 'custom',
        label: runLabel.trim() || `Pasted text (${filesToSend.length} ${filesToSend.length === 1 ? 'file' : 'files'})`,
        files: filesToSend.map(({ name, content, encoding }) => ({ name, content, encoding })),
        policy,
        secret_mode: secretMode,
        custom_secret: secretMode === 'custom' ? customSecret.trim() : undefined,
      };
    } else {
      if (builderRecords.length === 0) {
        setLocalError('Add at least one patient record in the Form Builder.');
        return;
      }
      const generated = buildFilesFromBuilder();
      payload = {
        source: 'custom',
        label: runLabel.trim() || `Form Builder (${builderRecords.length} patients)`,
        files: generated.map(({ name, content, encoding }) => ({ name, content, encoding })),
        policy,
        secret_mode: secretMode,
        custom_secret: secretMode === 'custom' ? customSecret.trim() : undefined,
      };
    }

    await onStartRun(payload);
  };

  return (
    <div className="run-layout">
      {/* Header */}
      <div className="run-header">
        <div className="run-header-copy">
          <span className="run-header-kicker">YOUR RELEASE WORKSPACE</span>
          <h2 className="section-title" style={{ marginTop: '0.3rem' }}>
            Release workbench
          </h2>
          <p className="section-subtitle">
            Choose a synthetic dataset or bring your own files. Review the privacy settings before running a release.
          </p>
        </div>
        <div className="run-header-aside">
          <img src="/clinical-privacy-hero.svg" alt="" aria-hidden="true" />
          <div className="run-header-right">
            <span className="capability-chip">Offline CPU</span>
            <span className="capability-chip">No LLM</span>
          </div>
        </div>
      </div>

      {(error || localError) && (
        <ErrorBanner
          message={localError || error?.message || 'Error'}
          requestId={error?.requestId}
          onRetry={() => void handleExecute()}
        />
      )}

      {/* Input Source Selector Card */}
      <section className="card wb-card">
        <div className="wb-tabs" role="tablist" aria-label="Input source mode">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'upload'}
            className={`wb-tab ${activeTab === 'upload' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('upload')}
          >
            📁 Upload Files
            {uploadedFiles.length > 0 && <span className="wb-tab-badge">{uploadedFiles.length}</span>}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'paste'}
            className={`wb-tab ${activeTab === 'paste' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('paste')}
          >
            📝 Paste / Write Text
            {stagedPasted.length > 0 && <span className="wb-tab-badge">{stagedPasted.length}</span>}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'builder'}
            className={`wb-tab ${activeTab === 'builder' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('builder')}
          >
            🧾 Patient Form Builder
            <span className="wb-tab-badge">{builderRecords.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'preset'}
            className={`wb-tab ${activeTab === 'preset' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('preset')}
          >
            📦 Built-in Datasets
          </button>
        </div>

        {/* TAB 1: UPLOAD FILES */}
        {activeTab === 'upload' && (
          <div className="wb-pane">
            <div
              className={`dropzone ${isDragging ? 'is-dragging' : ''}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => void handleFilesSelected(e.target.files)}
              />
              <input
                ref={(node) => {
                  folderInputRef.current = node;
                  if (node) node.setAttribute('webkitdirectory', '');
                }}
                type="file"
                multiple
                style={{ display: 'none' }}
                aria-label="Choose a folder of files"
                onChange={(e) => void handleFilesSelected(e.target.files)}
              />
              <div className="dropzone-icon">⬆</div>
              <strong>Drop files here, or choose files or a folder</strong>
              <p>
                Supported: <span className="mono">.csv</span> <span className="mono">.tsv</span>{' '}
                <span className="mono">.json</span> (nested &amp; FHIR R4){' '}
                <span className="mono">.txt</span> · Unsupported formats (
                <span className="mono">.pdf</span>, <span className="mono">.jpg</span>,{' '}
                <span className="mono">.xml</span>) are safely routed to Quarantine.
              </p>
            </div>
            <div className="upload-source-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()}>
                Choose files
              </button>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => folderInputRef.current?.click()}>
                Choose a folder
              </button>
              <span>Folder structure is retained · up to 250 files per run</span>
            </div>

            {uploadedFiles.length > 0 && (
              <div className="staged-list">
                <div className="staged-list-head">
                  <strong>Staged files ({uploadedFiles.length})</strong>
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setUploadedFiles([])}
                  >
                    Clear all
                  </button>
                </div>
                <ul>
                  {uploadedFiles.map((f) => (
                    <li key={f.name} className="staged-item">
                      <div>
                        <span className="mono">{f.name}</span>
                        <span className="staged-meta">
                          {f.encoding === 'base64' ? 'binary (will quarantine)' : 'text'}
                          {f.sizeBytes !== undefined ? ` · ${(f.sizeBytes / 1024).toFixed(1)} KB` : ''}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setUploadedFiles((prev) => prev.filter((x) => x.name !== f.name))}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* TAB 2: PASTE / WRITE TEXT */}
        {activeTab === 'paste' && (
          <div className="wb-pane">
            <div className="paste-toolbar">
              <label className="field-group" style={{ flex: '1 1 240px' }}>
                <span className="field-label">Filename (controls format parser)</span>
                <input
                  type="text"
                  className="field-input mono-input"
                  value={pasteFilename}
                  onChange={(e) => setPasteFilename(e.target.value)}
                  placeholder="e.g. discharge_note.txt, roster.csv, bundle.json"
                />
              </label>

              <div className="paste-templates">
                <span className="field-label">Load template:</span>
                <div className="paste-tpl-btns">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setPasteFilename(PASTE_TEMPLATES.note.filename);
                      setPasteContent(PASTE_TEMPLATES.note.content);
                    }}
                  >
                    Clinical Note (.txt)
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setPasteFilename(PASTE_TEMPLATES.csv.filename);
                      setPasteContent(PASTE_TEMPLATES.csv.content);
                    }}
                  >
                    Hindi+Eng CSV (.csv)
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setPasteFilename(PASTE_TEMPLATES.json.filename);
                      setPasteContent(PASTE_TEMPLATES.json.content);
                    }}
                  >
                    OPD JSON (.json)
                  </button>
                </div>
              </div>
            </div>

            <label className="field-group" style={{ marginTop: '0.75rem' }}>
              <span className="field-label">Raw record content (English, Hindi / Devanagari, Hinglish)</span>
              <textarea
                className="field-textarea mono-input"
                rows={10}
                value={pasteContent}
                onChange={(e) => setPasteContent(e.target.value)}
                placeholder="Paste any CSV rows, JSON, FHIR Bundle, or discharge summary text…"
              />
            </label>

            <div className="paste-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={addPastedToBatch}>
                + Add file to multi-file batch
              </button>
              <span className="field-hint">
                Or click <strong>Run Privacy Pipeline</strong> below to run directly on the editor content.
              </span>
            </div>

            {stagedPasted.length > 0 && (
              <div className="staged-list">
                <div className="staged-list-head">
                  <strong>Batched text files ({stagedPasted.length})</strong>
                  <button type="button" className="btn-link" onClick={() => setStagedPasted([])}>
                    Clear batch
                  </button>
                </div>
                <ul>
                  {stagedPasted.map((f) => (
                    <li key={f.name} className="staged-item">
                      <span className="mono">{f.name}</span>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setStagedPasted((prev) => prev.filter((x) => x.name !== f.name))}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: PATIENT FORM BUILDER */}
        {activeTab === 'builder' && (
          <div className="wb-pane">
            <p className="field-hint" style={{ marginBottom: '0.85rem' }}>
              Enter any new synthetic patient fields below to auto-generate a linked CSV registry + clinical discharge notes and test how Secret Wards redacts, pseudonymizes, bands ages, and shifts dates on fresh unseen records.
            </p>
            <div className="builder-grid">
              <label className="field-group">
                <span className="field-label">Patient Name *</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.patientName}
                  onChange={(e) => setBuilderForm({ ...builderForm, patientName: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">UHID / MRN *</span>
                <input
                  type="text"
                  className="field-input mono-input"
                  value={builderForm.uhid}
                  onChange={(e) => setBuilderForm({ ...builderForm, uhid: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Date of Birth</span>
                <input
                  type="date"
                  className="field-input"
                  value={builderForm.dob}
                  onChange={(e) => setBuilderForm({ ...builderForm, dob: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Age (Years)</span>
                <input
                  type="number"
                  min={0}
                  max={120}
                  className="field-input"
                  value={builderForm.age}
                  onChange={(e) => setBuilderForm({ ...builderForm, age: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Sex</span>
                <select
                  className="field-select"
                  value={builderForm.sex}
                  onChange={(e) => setBuilderForm({ ...builderForm, sex: e.target.value })}
                >
                  <option value="M">M</option>
                  <option value="F">F</option>
                  <option value="O">Other</option>
                </select>
              </label>
              <label className="field-group">
                <span className="field-label">Mobile Phone</span>
                <input
                  type="text"
                  className="field-input mono-input"
                  value={builderForm.phone}
                  onChange={(e) => setBuilderForm({ ...builderForm, phone: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Aadhaar / ABHA ID</span>
                <input
                  type="text"
                  className="field-input mono-input"
                  value={builderForm.nationalId}
                  onChange={(e) => setBuilderForm({ ...builderForm, nationalId: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">District</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.district}
                  onChange={(e) => setBuilderForm({ ...builderForm, district: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Address / Village / PIN</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.address}
                  onChange={(e) => setBuilderForm({ ...builderForm, address: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Admit Date</span>
                <input
                  type="date"
                  className="field-input"
                  value={builderForm.admitDate}
                  onChange={(e) => setBuilderForm({ ...builderForm, admitDate: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Discharge Date</span>
                <input
                  type="date"
                  className="field-input"
                  value={builderForm.dischargeDate}
                  onChange={(e) => setBuilderForm({ ...builderForm, dischargeDate: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Attending Doctor (Preserved)</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.doctor}
                  onChange={(e) => setBuilderForm({ ...builderForm, doctor: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Primary Diagnosis</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.diagnosis}
                  onChange={(e) => setBuilderForm({ ...builderForm, diagnosis: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Medication / Rx</span>
                <input
                  type="text"
                  className="field-input"
                  value={builderForm.medication}
                  onChange={(e) => setBuilderForm({ ...builderForm, medication: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Custom Extra Column Name</span>
                <input
                  type="text"
                  className="field-input mono-input"
                  placeholder="e.g. ward_clerk"
                  value={builderForm.customFieldKey}
                  onChange={(e) => setBuilderForm({ ...builderForm, customFieldKey: e.target.value })}
                />
              </label>
              <label className="field-group">
                <span className="field-label">Custom Extra Column Value</span>
                <input
                  type="text"
                  className="field-input"
                  placeholder="Value for custom column"
                  value={builderForm.customFieldVal}
                  onChange={(e) => setBuilderForm({ ...builderForm, customFieldVal: e.target.value })}
                />
              </label>
            </div>

            <label className="field-group" style={{ marginTop: '0.75rem' }}>
              <span className="field-label">Clinical Notes / Vitals</span>
              <input
                type="text"
                className="field-input"
                value={builderForm.notes}
                onChange={(e) => setBuilderForm({ ...builderForm, notes: e.target.value })}
              />
            </label>

            <div className="builder-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={addBuilderRecord}>
                + Add Patient to Batch
              </button>
              <label className="builder-check">
                <input
                  type="checkbox"
                  checked={includeNotesForBuilder}
                  onChange={(e) => setIncludeNotesForBuilder(e.target.checked)}
                />
                <span>Also generate a cross-file `.txt` discharge note per patient</span>
              </label>
            </div>

            {builderRecords.length > 0 && (
              <div className="staged-list">
                <div className="staged-list-head">
                  <strong>Patients in batch ({builderRecords.length})</strong>
                  <button type="button" className="btn-link" onClick={() => setBuilderRecords([])}>
                    Clear all
                  </button>
                </div>
                <ul>
                  {builderRecords.map((r) => (
                    <li key={r.id} className="staged-item">
                      <div>
                        <strong>{r.patientName}</strong>{' '}
                        <span className="mono">{r.uhid}</span>
                        <span className="staged-meta">
                          Age {r.age} · {r.district} · {r.diagnosis}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setBuilderRecords((prev) => prev.filter((x) => x.id !== r.id))}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* TAB 4: BUILT-IN PRESETS */}
        {activeTab === 'preset' && (
          <div className="wb-pane">
            <div className="preset-grid">
              {presets.map((p) => {
                const active = selectedPreset === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={`preset-card ${active ? 'is-selected' : ''}`}
                    aria-pressed={active}
                    onClick={() => { setSelectedPreset(p.id); setSeedOverride(null); }}
                  >
                    <div className="preset-card-head">
                      <strong>{p.name}</strong>
                      <span className="wb-tab-badge">{p.file_count} files</span>
                    </div>
                    <p className="preset-desc">{p.description}</p>
                    <div className="preset-chips">
                      {p.highlights.map((h) => (
                        <span key={h} className="preset-chip">{h}</span>
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
            {preset?.sample_seed != null && (
              <div className="seed-controls">
                <div>
                  <label htmlFor="dataset-seed">Dataset seed</label>
                  <p id="seed-help">Replay this case with the same seed, or generate new patients, dates and column layouts.</p>
                </div>
                <input id="dataset-seed" inputMode="numeric" value={seed} aria-describedby="seed-help"
                  onChange={(event) => setSeedOverride(event.target.value)} />
                <button className="btn btn-secondary" type="button"
                  onClick={() => setSeedOverride(String(crypto.getRandomValues(new Uint32Array(1))[0] >>> 1))}>
                  New variation
                </button>
              </div>
            )}
          </div>
        )}
      </section>

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

      {/* Execute Bar */}
      <section className="card wb-execute-bar">
        <label className="field-group" style={{ flex: '1 1 260px' }}>
          <span className="field-label">Optional run label (for history comparison)</span>
          <input
            type="text"
            className="field-input"
            placeholder="e.g. Chaos test k=2, Rotated secret test…"
            value={runLabel}
            onChange={(e) => setRunLabel(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="btn btn-primary wb-run-btn"
          disabled={isStarting || isRunning}
          onClick={() => void handleExecute()}
        >
          {isStarting || isRunning ? 'Running offline pipeline…' : '▶ Run Privacy Pipeline'}
        </button>
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
