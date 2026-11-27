# Secret Wards v5 - Engineering Brief

**Team:** Chiya and Coders  
**Members:** Ganesh Sah, Ishan Joshi, Anupam Poudel  
**Public repository:** https://github.com/Its-Ishan1/NijiCare

## Mission and USP

Secret Wards prepares hospital records for privacy-reviewed research release. Its differentiator is an offline, CPU-only hybrid pipeline that combines deterministic privacy rules with small trained multilingual text and table models. It links records conservatively across English, Hindi, and Hinglish while preserving clinical values and separating homonyms. The deployed engine uses Python's standard library and local model weights; it makes no external model or network calls.

## Architecture

```text
CSV / TSV / JSON / FHIR-shaped JSON / TXT
                    |
                    v
       Strict decode, parse, quarantine
                    |
                    v
     Rules + multilingual labels + CRF
       + header-blind column classifier
                    |
                    v
  Evidence blocking + conflict-checked linkage
                    |
                    v
 HMAC pseudonyms + identifier removal + age/date transforms
                    |
                    v
 Sanitized release + records.jsonl + report.json

Deployment boundary: encrypted scratch/output storage and an external key manager
are required. The demo does not implement encryption at rest or protect a live host.
```

The deterministic layer handles identifiers, multilingual labels, dates, ages, and clinical safeguards. A release-local name vocabulary and cross-script normalization support linking. A conflicting pair of observed phone numbers blocks a merge based only on a shared name and birth date; weak fragments abstain. The CRF is a free-text name/address fallback; the column model classifies likely PII from column values when a CSV/TSV header is unfamiliar. ML predictions supplement the rules and require release review.

## Setup and operation

Requires Python 3.10+. The competition CLI runs offline with no third-party runtime dependencies:

```bash
export RAKSHA_SECRET='supply-a-secret-out-of-band'
python3 main.py --input /path/to/input --output /path/to/empty-output
```

The output folder contains `sanitized/`, `records.jsonl`, and `report.json`. The optional local web workbench is started from `demo-app/server` with `python3 -B server.py`. Use synthetic records only in the demo. Select a file or folder in the workbench, then run the pipeline.

## Privacy and utility evidence

The corrected model was checked on the organizer's 200-file practice set: 0/3,230 labeled identifiers visible, 0/4 canaries, and 4,855/4,855 clinical probes retained. Linkage precision/recall/F0.5 measured 1.00/0.96/0.99, with zero false merges. It produced 193 sanitized files and seven quarantines. A regression now preserves the clinical shorthand `K/C/O` (“known case of”) while continuing to redact relative names in genuine `C/O` contexts. These are results on the supplied synthetic practice set, not a guarantee for unseen records.

That baseline had 2/39 covered records unique on age-band plus district, but 15/15 unique on a four-field FHIR subset that added shifted admission week and diagnosis. This is a residual-risk warning, not a privacy pass. The risk script measures simple uniqueness and is not the competition attack arena. Numeric JSON ages retain their exact values. Date shifts preserve intervals; age bands trade detail for lower demographic precision.

## Security design and limitations

The CLI processes raw input without creating raw/intermediate copies. The web demo temporarily stages uploads in an owner-restricted temporary directory and removes it after processing; this temporary disk storage is not application-encrypted. Sanitized outputs are sensitive and are written without application-level encryption. `RAKSHA_SECRET` is supplied through the process environment and is not kept in a separate KMS/HSM. Logs contain counts, and quarantine output contains a digest and reason rather than raw content.

For deployment, use encrypted scratch and output volumes, a dedicated service account, and an external secret manager with least-privilege key access. Avoid snapshots/backups of temporary input. A live server compromise can expose in-memory raw records and the running process key; this prototype does not claim to withstand active host compromise.

The engine supports CSV, TSV, JSON/FHIR-shaped JSON, and text; unsupported types such as PDF, images, and XML are quarantined. It does not provide OCR, full FHIR R4 profile validation, general rare-value suppression, or a comprehensive geographic hierarchy for location generalization. District/hospital context can remain. Novel labels and name constructions can still escape detection. The v5 models were trained on synthetic data; practice records are for evaluation, not training.
