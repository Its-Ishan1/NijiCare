# Secret Wards v5 — Hybrid Rules + Statistical ML

Secret Wards is an offline CPU pipeline for sanitizing synthetic Indian hospital records for research. It combines deterministic privacy rules with two trained statistical fallbacks: a multilingual linear-chain CRF for free-text names/addresses and a header-blind column-value classifier for unfamiliar CSV/TSV headers. The exported weights run with Python's standard library; no LLM, model download, network service, or third-party runtime package is used.

## Run the local website

The instructor can clone the public repository and launch the offline web workbench on their own computer. Python 3.10+ is required; the built frontend is included, so Node.js and internet access are not required to run it.

### macOS / Linux

```bash
git clone https://github.com/Its-Ishan1/NijiCare.git
cd NijiCare
chmod +x start-web.sh
./start-web.sh
```

Open **http://127.0.0.1:8081** on the same computer. This is a local address, not a hosted website: it opens the server started from the clone on that laptop. The launcher uses a demo-only key if `RAKSHA_SECRET` is unset. Use synthetic data with that default; set a private key before launch for a different test run:

```bash
export RAKSHA_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
./start-web.sh
```

To use another port, run `PORT=8082 ./start-web.sh`. Keep the terminal open while testing and press **Ctrl+C** to stop the server. The adapter listens only on `127.0.0.1`; the page is local to that computer.

If an old page still appears, stop any server already running on port 8081, update the clone with `git pull origin main`, start the launcher again, then hard-refresh the browser (**Cmd+Shift+R** on macOS, **Ctrl+F5** on Windows/Linux). The launcher refuses to start on an occupied port and prints instructions instead of leaving you connected to an older server.

### Windows

```powershell
git clone https://github.com/Its-Ishan1/NijiCare.git
cd NijiCare\demo-app
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

Open **http://127.0.0.1:8081**. The launcher uses the demo-only key unless `RAKSHA_SECRET` is set in the same PowerShell session.

Choose individual files or a folder in the Workbench. Folder selection retains nested paths. Supported inputs are CSV, TSV, JSON, single-patient FHIR Bundles, and UTF text. Unsupported or unsafe inputs appear in Quarantine. The browser accepts up to 250 files and 25 MiB per run; use the CLI below for larger batches.

## Run the command-line pipeline

### macOS / Linux

```bash
git clone https://github.com/Its-Ishan1/NijiCare.git
cd NijiCare
export RAKSHA_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
python3 -B main.py --input /path/to/input --output /path/to/new-output
```

### Windows PowerShell

```powershell
$env:RAKSHA_SECRET = 'use-a-secret-provided-out-of-band'
python -B main.py --input path\to\input --output path\to\new-output
```

The input path may be a single file or a directory. The output directory must be empty or not exist. Keep `RAKSHA_SECRET` outside the repository and do not reuse a practice key for real systems. On POSIX, the CLI creates output files with owner-only permissions. It writes `sanitized/`, `records.jsonl`, and `report.json`. Runtime dependencies are all in the Python standard library.

To run the regression suite and the organizer's output contract checker:

```bash
python3 -B -m unittest discover -s qa -v
python3 /path/to/Secret-Wards-ToolKit/validate_output.py --input /path/to/input --output /path/to/new-output
```

The provided `a.json` test contains seven `Patient` resources in one FHIR Bundle. This release intentionally quarantines Bundles with more than one Patient as `unsupported_fhir_patient_count`; it does not emit partially sanitized data. Use a separate one-patient Bundle per file for the supported FHIR path.

## Design

1. **Ingestion and fail-safe handling:** recursively reads CSV, TSV, JSON (including supported FHIR-shaped Bundles), and UTF text. It recognizes UTF-8, UTF-16, and common legacy encodings, parses tables strictly, and quarantines unsupported or malformed files without copying their contents into the release. Supported FHIR Bundles are checked for impossible or malformed date, date-time, and timestamp values before sanitization; invalid dates quarantine the whole Bundle instead of silently disappearing. This is primitive date validation, not full FHIR R4 schema or profile validation. XML, PDF, and image OCR are not supported. Filenames containing detected personal data are replaced with keyed opaque labels.
2. **Detection:** multilingual label dictionaries, regex/context rules, a release-local name vocabulary, Devanagari transliteration, and the trained CRF and column classifier work together. The CRF detects free-text names/addresses; the column model infers likely PII from value shapes when table headers are unfamiliar. Clinical guards protect doctors, diagnoses, medications, doses, vitals, and eponyms. Machine-learning predictions remain fallbacks and can miss novel patterns; every release needs review.
3. **Linkage:** exact chart/encounter identifiers and corroborated name/contact/date evidence are indexed across files. Cross-script names are normalized before blocking. Conflicts and ambiguous evidence abstain; no unconstrained edit-distance match is used to merge patients. Every unresolved record gets `patient: null`.
4. **Pseudonyms and privacy:** stable pseudonyms and patient-level date offsets use HMAC-SHA256 keyed by `RAKSHA_SECRET`, never plain hashing. Age values are generalized to truthful bands; adjacent bands may merge within a district. Direct address fields are redacted, while some district/hospital context may remain. The current release engine does not implement general rare-value suppression or a geographic hierarchy service. The policy is in `config/policy.yaml`.
5. **Release contract:** `records.jsonl` maps each processed record to a pseudonym or null; `report.json` reports file hashes, quarantine status, counts, timing, and peak memory. Logs contain counts only. The CLI reads raw inputs without creating raw/intermediate copies. The optional web workbench temporarily stages raw uploads in a private OS temporary directory and removes it after processing; this temporary staging is not encrypted by the application.

## Output shape

```text
output/
  sanitized/     # sanitized files retaining relative paths and supported formats
  records.jsonl  # one JSON object per record, with file, loc, patient
  report.json    # per-file SHA-256, status, counts and runtime measurements
```

Unsupported formats are listed as quarantined in the report with no output path. CSV/TSV record locations use zero-based `row:N`; JSON uses a JSON pointer; text and FHIR files use `doc`.

## Local checks

```powershell
python -m unittest discover -s qa -v
$env:RAKSHA_SECRET = 'practice'
python main.py --input path/to/practice/input --output out
python path/to/Secret-Wards-ToolKit/validate_output.py --input path/to/practice/input --output out
python path/to/Secret-Wards-ToolKit/check_dev.py --output out
```

Regression tests use invented records. The official toolkit is distributed separately and is not included in this repository. For Linux resource, network-isolation, and final submission checks, use `qa/verify_linux.py` on the organizer-like Linux host with the toolkit available. The release verification passed on Ubuntu under WSL with two CPUs, a 4 GiB address-space limit and a loopback-only network namespace.

## Security boundary and threat model

The CLI does not write raw or intermediate input files; the web demo does briefly stage uploaded bytes under a mode-restricted temporary directory and cleans it up. Sanitized outputs are still sensitive research data and are not application-encrypted at rest. The demo's `RAKSHA_SECRET` is available to the running process; it is not backed by a separate KMS/HSM. Owner-only file permissions are defense in depth, not encryption. For deployment, place scratch and output paths on encrypted storage, keep the HMAC key in a separate secret manager with least-privilege access, use a dedicated service account, and avoid backups/snapshots of scratch files. A compromise of a live server can expose in-memory raw input and the process key; this prototype does not claim to resist active host compromise.

## Privacy/utility trade-off and limitations

Age bands, date shifts, and direct identifier removal reduce risk while retaining clinical values and stay lengths, but do not guarantee anonymity. The attached 14-file synthetic multi-hospital fixture produced 11 sanitized files and three quarantines; all 17 emitted records linked across English, Hindi and text cases. Integer JSON ages are emitted as truthful string ranges (for example, `25-29`) because an integer cannot represent an interval. Date shifts preserved the fixture's 9-day stay length, and checked clinical values survived. General rare-value suppression, complete geographic generalization, full FHIR R4 profile validation, OCR, and protection from a live host breach are not implemented. The held-out models were trained on synthetic data; practice-set checks are evaluation, not model training. Review every release.

## Team declaration

- Runtime: Python standard library only; CPU-only, offline.
- Model: trained synthetic-data CRF and logistic column classifier, exported as stdlib-readable weights; deterministic rules remain primary.
- Synthetic-only development and validation data. Do not claim clinical or production validation.

## Practice-set verification

An earlier run on the organiser's 200-file practice set reported linkage precision 1.00, recall 0.96 and F0.5 0.99, with zero false merges. It found 0 / 3,230 labeled identifiers visible and retained 4,855 / 4,855 clinical probes. These are measurements from that run, not a claim about the newer synthetic fixture. The bundled suite includes 15 generated combinations across three scenarios, independent of the organiser's practice inputs. Generate more with `python qa/case_factory.py lab_exchange --seed 778 --output sample-778`. Pass that folder to the normal CLI. Refer to the two-page Project Brief for current fixture results and scope limitations.

## Current verification

The current 35-test regression suite passes. The comprehensive 24-file synthetic audit produced 20 sanitized files and quarantined 4 malformed or unsupported files; targeted checks confirmed six corroborated Meera records share one pseudonym, Rahul homonyms remain separate, ambiguous fragments abstain, and tested relative-name rules preserve clinical values. The earlier 200-file practice metrics are documented separately in [the verification report](VALIDATION.md).

Known linkage ambiguity: records with different chart IDs but identical names, dates of birth and phone numbers may be linked as one patient. Those fields cannot prove whether the records are cross-hospital charts for one person or two people sharing the same contact details. Review such cases against trusted source data; the prototype currently favors cross-hospital linkage recall in this tie.
