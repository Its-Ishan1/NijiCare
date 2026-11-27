# Secret Wards verification and review

Tested on 27 November 2026 using the supplied model artifacts and synthetic validation data. CLI and web upload API checks used the default policy with ML enabled. The two deployed models and six scikit-learn artifacts were loaded for inference. The training script was never run. After the initial review, the relative-name rule was fixed to protect the clinical `K/C/O` (“known case of”) shorthand. A later twist-pack run also exposed homonym false merges when name and birth date matched but phone numbers conflicted; the linker now blocks those soft-evidence merges. The regression suite, full practice set, output contract, and submission checker were rerun after the fixes.

## Model results

The free-text test contains 1,000 notes. Scores use exact BIO token labels and the saved benchmark's 0.85 confidence threshold for models that return probabilities. A missed token can leave part of a name or address visible.

| Free-text model | Precision | Recall | Token F1 | Missed labeled tokens | False positives in 256 clinical-only notes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Deployed linear-chain CRF | 100.00% | 97.43% | 98.70% | 90 of 3,507 | 0 |
| Token LinearSVC | 99.71% | 97.29% | 98.48% | 95 of 3,507 | 0 |
| Token logistic regression | 99.70% | 95.30% | 97.45% | 165 of 3,507 | 0 |

| Column model | Correct labels on 840 columns | Macro F1 |
| --- | ---: | ---: |
| Deployed logistic regression, compressed JSON export | 840 | 1.0000 |
| Same logistic regression, scikit-learn artifact | 840 | 1.0000 |
| Column LinearSVC | 840 | 1.0000 |
| Column MLP | 840 | 1.0000 |
| Column random forest | 839 | 0.9988 |

The random forest labeled one address column as a name. All classifiers protected all 120 clinical columns on this split. With the actual column fallback's threshold and guards enabled, it returned the expected sensitive category for **599 of 600** sensitive columns and abstained on one address column. It selected none of the 240 clinical or other columns for redaction. Rules can still process a column when the model abstains.

The reported model scores reproduce to the precision published in the original training report. The supplied split contains 58 clinical-only validation notes and one `OTHER` validation column that match training rows exactly. The name and address examples in the validation set come from the project’s synthetic generator. Evaluate new sources and unseen note templates before extending these scores to other hospitals.

## End-to-end correctness

All 200 organizer practice files matched their ground-truth SHA-256 values. The organizer's output validator returned `CONTRACT OK`. With the practice key, 193 files were sanitized, seven quarantined, and 815 records indexed.

| Organizer practice measurement | Observed |
| --- | ---: |
| Labeled identifiers still visible | 0 / 3,230 |
| Planted canaries exposed | 0 / 4 |
| Checked medical values retained | 4,855 / 4,855 (100%) |
| Linkage precision / recall / F0.5 | 1.00 / 0.96 / 0.99 |
| Pseudonyms merging different ground-truth patients | 0 |
| Broken or unsupported files copied through | 0 |

The five-file synthetic case also passed the contract. All 10 true record pairs linked, with zero extra or missed pairs. All 17 clinical probes, nine stay lengths and ten truthful age bands passed. All seven checked admission dates shifted. No checked direct identifier appeared in the output. The rerun measured zero unique records on age-band plus district across six covered pseudonyms; both covered FHIR pseudonyms were unique on at least one four-field observation.

All 32 regression tests passed on the corrected project. The organizer's Linux submission checker confirmed the output contract, identical releases with the same key, different releases after key rotation, intact input files and no release key in the logs or output. The latest full practice run produced 193 sanitized files, seven quarantines and 815 indexed records; the official output validator returned `CONTRACT OK`, and the submission checker returned `READY TO SUBMIT`.

The web upload API has been exercised with mixed-format synthetic batches. The browser picker automation is available at `demo-app/tools/check-ui.mjs`; a full browser UI run was not repeated in this final verification pass.

## Remaining limitations and review priorities

1. **Report model coverage alongside accuracy.** Include abstentions and full-entity recall in future benchmarks. Split validation templates and clinical controls by source, deduplicate whole rows against training, and retain a separate test set for novel layouts.
2. **Review ambiguous linkage and indirect identification.** Precision was 1.00 on the practice labels, while 0.96 recall means some true links were missed. Records with different chart IDs but matching names, birth dates and phone numbers may represent either cross-hospital records for one patient or different people sharing contact data. The current rerun measured 2/39 unique on age-band plus district and 15/15 unique on a four-field FHIR subset that also includes shifted admission week and diagnosis. Review that field combination before release.
3. **Keep deployment controls external to this prototype.** Use encrypted scratch/output storage, a separate secret manager, least-privilege service accounts and a documented incident response plan. The web demo's temporary upload staging is not application-encrypted, and a live host compromise can expose in-memory records and the process key.
4. **Validate new formats and sources conservatively.** The engine supports CSV, TSV, JSON/FHIR-shaped JSON and text; unsupported formats are quarantined. It does not provide OCR, complete FHIR R4 profile validation, broad rare-value suppression or a comprehensive geographic generalization hierarchy.

## Reproducing the checks

From the extracted archive root, with Python 3.10+ and scikit-learn available for the saved training artifacts, run:

```sh
python -B training/check_models.py
python -B -m unittest discover -s qa -v
python -B synthetic_case/evaluate_synthetic.py --repo . --kit /path/to/Secret-Wards-ToolKit --output /path/to/new-synthetic-output
```

For the organizer practice report, use `RAKSHA_SECRET=practice`, run the CLI on the toolkit's `dev/input`, then pass the output to the toolkit's `validate_output.py` and `check_dev.py`. The submission checker can be run with `check_submission.py --repo . --run`. The local web demo and CLI run with Python's standard library. The optional browser verification command is in the workbench README.
