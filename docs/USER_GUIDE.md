# Secret Wards — Complete User Guide (How to Use It)

This guide explains how to launch Secret Wards, feed **your own new data** as files or folders, configure **every privacy policy and custom field**, inspect results, and run the CLI directly for hackathon evaluation.

---

## 1. Starting the Application

### macOS / Linux
From the repository root, run:

```bash
./start-web.sh
```

Open **http://127.0.0.1:8081**. The launcher runs the included frontend and Python adapter locally; it does not need Node.js or internet access. It uses a demo-only key when `RAKSHA_SECRET` is unset, so use synthetic data with that default. To set a private key first:

```bash
export RAKSHA_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
./start-web.sh
```

Use `PORT=8082 ./start-web.sh` to change ports. Keep the terminal open while the page is in use and press **Ctrl+C** to stop the server.

This address is local to the machine where the server is running, not a hosted link. If an older page appears, update the clone (`git pull origin main`), stop the previous server, restart the launcher, and hard-refresh the browser. The launcher refuses to start on an occupied port; use a free port such as `PORT=8082 ./start-web.sh` if necessary.

### Windows (One-Click Launcher)
```powershell
cd demo-app
.\start.ps1
```
`start.ps1` automatically locates Python 3.10+, builds the React frontend if `dist/` is missing, checks that its port is available, and starts the local offline server.

Open **http://127.0.0.1:8081** in your browser.

### Manual start

From the archive root, run `python -B demo-app/server/server.py` (use `python3` on Linux) and open http://127.0.0.1:8081. The compiled frontend ships in the ZIP.

## 2. Supplying test data

Choose **Choose files** for individual files or **Choose folder** for a directory. You can also drop files or a folder on the upload area. Subfolder paths are retained relative to the chosen folder. Supported formats are CSV, TSV, JSON, single-patient FHIR Bundles and TXT. Bundles with multiple Patient resources are quarantined as `unsupported_fhir_patient_count` rather than released with unsafe record mapping. Other formats appear in the quarantine report.

Check the selected paths, then click **Run Privacy Pipeline**. For the same release key and policy, the web upload and CLI use the same source bytes. Use the CLI for batches above the browser limits of 250 files or 25 MiB of encoded request data.

## 3. Setting Privacy Policy & Custom Fields

Directly below the file selector on the **Workbench** is the **Privacy Policy & Custom Field Controls** panel. Every setting applies immediately to the next run:

### 1. Generalization & Temporal Parameters
- **Age band base width (years)** (default `5`): Starting bin size (e.g., `5` → `35-39`; set `10` for `30-39`).
- **Max adaptive age span (years)** (default `50`): Maximum width allowed when merging sparse district age bins.
- **Age k-anonymity threshold (k)** (default `2`): Minimum distinct patients per `(district, age band)`. Increase to `3` or `5` for stronger k-anonymity; set to `1` for fixed non-merging bins.
- **Max date shift (± days)** (default `180`): Range of the deterministic per-patient date offset.

### 2. Transformation Toggles
- **Per-patient date shifting**: Turn off to keep raw clinical dates (for comparison); leave on to shift dates while preserving stay lengths.
- **Adaptive age banding**: Toggle replacing exact ages with truthful bands.
- **Preserve doctor / clinician names**: Keeps `Dr.`, `Consultant`, `Physician`, and `डॉ.` names intact. Turn off if a workflow requires redacting clinicians too.
- **Hash sensitive filenames & JSON keys**: Renames files/keys containing patient names or IDs to `item-<hmac>`.
- **Hybrid Statistical ML Fallback (`ml_fallback`)**: Enables the trained offline Linear-Chain CRF (bare prose names/addresses) and Header-Blind Column-Value Classifier (unfamiliar CSV/TSV headers). Tune **ML NER CRF confidence threshold** (default `0.85`) and **ML Column Classifier threshold** (default `0.80`) right below the toggle — or turn `ml_fallback` off to compare Rules-Only vs. Hybrid ML side-by-side on files selected from **`datasets/ml_chaos_eval`**.

### 3. Active PII Redaction Categories
Toggle any of the 13 categories individually (`PHONE`, `AADHAAR`, `ABHA`, `EMAIL`, `PAN`, `NAME`, `MRN`, `ENCOUNTER`, `DOB`, `ADDRESS`, `RELATIVE`, `INSURANCE_ID`, `SOURCE_PATH`). Use **Select all** (recommended for releases) or **Core direct IDs**.

### 4. Custom Fields & Unseen Data Rules
When introducing **brand-new hospital exports** with proprietary columns or internal identifiers:
- **Extra fields / columns to redact**: Comma-separated column headers, JSON keys, or `Label:` note fields (e.g., `ward_clerk, bed_number, referral_source`) → always redacted as `[CUSTOM]`.
- **Extra fields / columns to preserve**: Comma-separated non-PII domain fields (e.g., `study_arm, protocol_code`) → explicitly exempted from redaction.
- **Custom literal terms / canaries to redact**: Comma-separated exact terms (case-insensitive whole-word) replaced with `[CUSTOM]`.
- **Custom regex pattern to redact**: Any custom regular expression (e.g., `EMP-\d{6}|BADGE-[A-Z]{2}\d{4}`) replaced with `[CUSTOM]` (validated live as you type).

### 5. Release Key (`RAKSHA_SECRET`) & Cross-Release Unlinkability Demo
- **Default server secret**: Uses the server's configured `RAKSHA_SECRET` (deterministic across runs).
- **Rotate fresh ephemeral secret**: Generates a random 256-bit one-time secret on the server. Run the same dataset twice — once with *Default* and once with *Rotate* — then switch between them in **Results** to prove that **every `PSN-...` pseudonym and shifted date changes completely**.
- **Custom synthetic test key**: Enter your own non-production test key to verify deterministic repeatability.

---

## 4. Inspecting Results & Exporting

Once a run completes, you are taken automatically to the **Results** dashboard:

- **Results Tab**:
  - **KPI Cards**: Files processed/sanitized/quarantined, records processed/linked/generalized, total identifiers detected, and runtime.
  - **Entity Detection Breakdown**: Exact counts per redacted category (`NAME`, `PHONE`, `MRN`, `DOB`, `NATIONAL_ID`, `ADDRESS`, `ATTACHMENT`, `CUSTOM`, etc.).
  - **Active Policy Snapshot**: Confirms the exact policy settings and secret mode used for that run.
  - **Indirect-Identification Risk Card**: Live output from `qa/release_risk.py`.
  - **Pseudonym Linkage Explorer**: Search/filter by `PSN-...`, filename, or locator (`row:N`, `/visits/0`, `doc`).
  - **Run Switcher Dropdown** (top right): Jump between any runs in your session to compare policy changes or key rotations.
  - **↓ Download ZIP**: Downloads the complete release package (`sanitized/`, `report.json`, `records.jsonl`) with zero raw input data.
- **File Viewer Tab**:
  - Filter files in the left sidebar and click any sanitized file.
  - Toggle **Show before / after** for side-by-side comparison.
  - Click **Copy** to copy sanitized text or **↓ Download raw** to save the clean file directly.
- **Quarantine Tab**:
  - Lists every file that could not be safely released by its truncated SHA-256 and exact quarantine reason (never exposes raw filenames or raw quarantined bytes).
- **Privacy & Audit Tab**:
  - Compares your current run metrics against the separately measured organiser practice benchmark.

---

## 5. Using the CLI Directly (Automation & Hackathon Submission)

The competition evaluator runs `main.py` offline via CLI:

```powershell
# 1. Run on a single file or folder of new data
$env:RAKSHA_SECRET = "my-release-secret"
python repo\main.py --input path\to\new_data --output path\to\empty_out

# 2. Run with a custom policy file
python repo\main.py --input path\to\new_data --output path\to\empty_out2 --policy my_policy.yaml

# 3. Measure indirect-identification risk
python repo\qa\release_risk.py --output path\to\empty_out

# 4. Run all regression tests
cd repo
python -m unittest discover -s qa -v
```

### Policy File Format (`config/policy.yaml`)
```yaml
age_band_years: 5
age_band_max_years: 50
age_k_anonymity: 2
date_shift_max_days: 180
shift_dates: true
generalize_ages: true
preserve_doctors: true
hash_sensitive_filenames: true
redact_categories: PHONE,AADHAAR,ABHA,EMAIL,PAN,NAME,MRN,ENCOUNTER,DOB,ADDRESS,RELATIVE,INSURANCE_ID,SOURCE_PATH
extra_redact_fields: ward_clerk,bed_number
extra_preserve_fields: study_arm
extra_redact_terms: CANARY-001
extra_redact_regex: EMP-\d{6}
```

---

## 6. Troubleshooting

| Issue | Solution |
|---|---|
| **"Adapter offline"** pill in the UI | Start `server.py` (`cd demo-app && .\start.ps1` or `python server\server.py`). Verify `http://127.0.0.1:8081/api/health` responds. |
| **CLI exits with code `2`** | Ensure `RAKSHA_SECRET` is set, `--input` exists, and `--output` is either nonexistent or completely empty. |
| **A file went to Quarantine** | Check the **Quarantine** tab for the reason (`unsupported_format`, `empty_file`, `undecodable_text`, `ambiguous_table_shape`, `duplicate_json_key`, `unresolved_fhir_reference`, etc.). |
| **Unseen custom column wasn't redacted** | Add the column name under **Extra fields / columns to redact** in the Workbench Policy panel (or `extra_redact_fields` in `policy.yaml`). |
| **A domain column was accidentally redacted** | Add it to **Extra fields / columns to preserve** (or `extra_preserve_fields` in `policy.yaml`). |
