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

The attached 14-file synthetic multi-hospital fixture produced 11 sanitized files and three quarantines (two unsupported formats and one malformed JSON). All 17 emitted records received a patient pseudonym, including text attachments and patient-keyed JSON. Aarav and Sana linked consistently across hospitals and scripts; Kiran's unmatched note received a stable chartless pseudonym. Filenames and JSON keys containing names were neutralized. The test preserved clinical values and the 9-day stay interval; integer JSON ages 27 and 42 became `25-29` and `40-44`. These results describe this small fixture, not a guarantee for unseen records.

Age bands trade detail for lower demographic precision. JSON age values are emitted as string ranges because a numeric integer cannot represent an interval; the range contains the observed age. Date shifts preserve stay lengths and event intervals. The current risk tooling measures simple uniqueness and is not a substitute for the competition's re-identification attack evaluation.

## Security design and limitations

The CLI processes raw input without creating raw/intermediate copies. The web demo temporarily stages uploads in an owner-restricted temporary directory and removes it after processing; this temporary disk storage is not application-encrypted. Sanitized outputs are sensitive and are written without application-level encryption. `RAKSHA_SECRET` is supplied through the process environment and is not kept in a separate KMS/HSM. Logs contain counts, and quarantine output contains a digest and reason rather than raw content.

For deployment, use encrypted scratch and output volumes, a dedicated service account, and an external secret manager with least-privilege key access. Avoid snapshots/backups of temporary input. A live server compromise can expose in-memory raw records and the running process key; this prototype does not claim to withstand active host compromise.

The engine supports CSV, TSV, JSON/FHIR-shaped JSON, and text; unsupported types such as PDF, images, and XML are quarantined. It does not provide OCR, full FHIR R4 profile validation, general rare-value suppression, or a comprehensive geographic hierarchy for location generalization. District/hospital context can remain. Novel labels and name constructions can still escape detection. The v5 models were trained on synthetic data; practice records are for evaluation, not training.
