export type PageId =
  | 'overview'
  | 'run'
  | 'results'
  | 'files'
  | 'quarantine'
  | 'audit';

export interface PolicyConfig {
  age_band_years: number;
  age_band_max_years: number;
  age_k_anonymity: number;
  date_shift_max_days: number;
  shift_dates: boolean;
  generalize_ages: boolean;
  preserve_doctors: boolean;
  hash_sensitive_filenames: boolean;
  ml_fallback: boolean;
  ml_ner_threshold: number;
  ml_col_threshold: number;
  redact_categories: string[];
  extra_redact_fields: string[];
  extra_preserve_fields: string[];
  extra_redact_terms: string[];
  extra_redact_regex: string;
}

export const ALL_PII_CATEGORIES = [
  'PHONE',
  'AADHAAR',
  'ABHA',
  'EMAIL',
  'PAN',
  'NAME',
  'MRN',
  'ENCOUNTER',
  'DOB',
  'ADDRESS',
  'RELATIVE',
  'INSURANCE_ID',
  'SOURCE_PATH',
] as const;

export const DEFAULT_POLICY: PolicyConfig = {
  age_band_years: 5,
  age_band_max_years: 50,
  age_k_anonymity: 2,
  date_shift_max_days: 180,
  shift_dates: true,
  generalize_ages: true,
  preserve_doctors: true,
  hash_sensitive_filenames: true,
  ml_fallback: true,
  ml_ner_threshold: 0.85,
  ml_col_threshold: 0.80,
  redact_categories: [...ALL_PII_CATEGORIES],
  extra_redact_fields: [],
  extra_preserve_fields: [],
  extra_redact_terms: [],
  extra_redact_regex: '',
};

export interface PresetInfo {
  sample_seed?: number | null;
  id: string;
  name: string;
  description: string;
  file_count: number;
  files: string[];
  highlights: string[];
}

export interface HealthResponse {
  status: string;
  demo_configured: boolean;
  pipeline_available: boolean;
  demo_input_available: boolean;
  supports_custom_input?: boolean;
  supports_policy_config?: boolean;
  presets?: PresetInfo[];
  default_policy?: PolicyConfig;
}

export interface CustomFileInput {
  name: string;
  content: string;
  encoding: 'utf-8' | 'base64';
  sizeBytes?: number;
}

export type SecretMode = 'default' | 'rotate' | 'custom';

export interface RunRequestPayload {
  source: 'demo' | 'preset' | 'custom';
  preset_id?: string;
  seed?: number;
  label?: string;
  files?: Array<{ name: string; content: string; encoding: 'utf-8' | 'base64' }>;
  policy?: PolicyConfig;
  secret_mode?: SecretMode;
  custom_secret?: string;
}

export interface RunCounts {
  files_total: number;
  files_sanitized: number;
  files_quarantined: number;
  records_processed: number;
  identifiers_detected: number;
  records_linked: number;
  records_generalized: number;
  records_suppressed: number;
  records_quarantined: number;
}

export interface RecordEntry {
  file: string;
  loc: string;
  patient: string | null;
}

export interface RiskSubset {
  covered_pseudonyms: number;
  unique_on_at_least_one_observation: number;
}

export interface RiskSummary {
  age_band_and_district?: RiskSubset;
  age_band_district_shifted_admission_week_and_diagnosis?: RiskSubset;
}

export interface RunDetail {
  run_id: string;
  source: string;
  label?: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string | null;
  finished_at: string | null;
  counts: RunCounts | null;
  entities?: Record<string, number>;
  timing: { seconds: number } | null;
  resources: { peak_rss_mb: number | null };
  records: RecordEntry[];
  risk: RiskSummary | null;
  policy_used?: PolicyConfig | null;
  secret_mode?: string;
  error_message: string | null;
  request_id?: string | null;
}

export interface RunHistoryItem {
  run_id: string;
  source: string;
  label: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string | null;
  finished_at: string | null;
  secret_mode: string;
  counts: RunCounts | null;
}

export interface PipelineFileEntry {
  input_sha256: string;
  output: string | null;
  status: 'sanitized' | 'quarantined' | 'suppressed';
  reason?: string;
  has_before?: boolean;
}

export interface RunFilesResponse {
  run_id: string;
  files: PipelineFileEntry[];
}

export interface DemoInputFile {
  name: string;
  label: string;
  content: string;
}

export interface ScorecardResponse {
  practice_benchmark: ScorecardResponse['v2_practice_benchmark'];
  label: string;
  v2_practice_benchmark: {
    dataset: string;
    labeled_identifiers_visible: { found: number; total: number };
    planted_canaries_exposed: { found: number; total: number };
    checked_medical_values_retained: { kept: number; total: number };
    linkage: { precision: number; recall: number; f05: number };
    residual_risk: {
      age_band_and_district: { unique: number; covered: number; note: string };
      fhir_4_field_subset: { unique: number; covered: number; note: string };
      caveat: string;
    };
  };
  v3_local_verification: {
    available: boolean;
    age_band_and_district_v3: { unique: number; covered: number };
    free_text_note_ages_generalized: { kept: number; total: number };
    note: string;
  };
}
