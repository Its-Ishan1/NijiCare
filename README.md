# Secret Wards v5 — Hybrid Rules + Statistical ML

Secret Wards is an offline CPU pipeline for sanitizing synthetic Indian hospital records for research. It combines deterministic privacy rules with two trained statistical fallbacks: a multilingual linear-chain CRF for free-text names/addresses and a header-blind column-value classifier for unfamiliar CSV/TSV headers. The exported weights run with Python's standard library; no LLM, model download, network service, or third-party runtime package is used.

## Run

```powershell
$env:RAKSHA_SECRET = 'use-a-secret-provided-out-of-band'
python main.py --input path/to/input --output path/to/empty-output
```

The input path may be a single file or a directory. The output directory must be empty or not exist. Keep `RAKSHA_SECRET` outside the repository and do not reuse a practice key for real systems. On POSIX, the CLI creates output files with owner-only permissions. It writes `sanitized/`, `records.jsonl`, and `report.json`. Runtime dependencies are all in the Python standard library.

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

Age bands, date shifts, and direct identifier removal reduce risk while retaining clinical values and stay lengths, but do not guarantee anonymity. The latest practice rerun measured 2/39 covered records unique on age-band plus district and 15/15 unique on a four-field FHIR subset; the latter is a material residual-risk warning. The risk script is a uniqueness proxy, not the organizer's attack arena. Numeric JSON ages retain their exact type/value. General rare-value suppression, complete geographic generalization, full FHIR R4 profile validation, OCR, and protection from a live host breach are not implemented. The held-out models were trained on synthetic data; practice-set checks are evaluation, not model training. Review every release.

## Team declaration

- Runtime: Python standard library only; CPU-only, offline.
- Model: trained synthetic-data CRF and logistic column classifier, exported as stdlib-readable weights; deterministic rules remain primary.
- Synthetic-only development and validation data. Do not claim clinical or production validation.

## Practice-set verification

On the organiser's 200-file practice set the supplied self-check reported linkage precision 1.00, recall 0.96 and F0.5 0.99, with zero false merges. It found 0 / 3,230 labeled identifiers visible and retained 4,855 / 4,855 clinical probes. The bundled suite includes 15 generated combinations across three scenarios, independent of the organiser's practice inputs. Generate more with `python qa/case_factory.py lab_exchange --seed 778 --output sample-778`. Pass that folder to the normal CLI. Numeric ages in JSON retain their original type and exact value. Refer to the two-page Project Brief for the covered-subset privacy estimate and Linux measurements.

## Current verification

The corrected package's practice run retained 4,855 of 4,855 checked clinical values and leaked zero of 3,230 labeled identifiers. Regression coverage confirms that `K/C/O` clinical history is preserved while true care-of relatives are redacted, and that conflicting observed phone numbers block a merge based only on name and birth date. See [the verification report](VALIDATION.md) for model scores, practice results and release limitations.

Known linkage ambiguity: records with different chart IDs but identical names, dates of birth and phone numbers may be linked as one patient. Those fields cannot prove whether the records are cross-hospital charts for one person or two people sharing the same contact details. Review such cases against trusted source data; the prototype currently favors cross-hospital linkage recall in this tie.
