# Secret Wards v5 — Hybrid ML Training Pipeline, Generated Datasets & Artifacts

This folder contains the reproducible offline training pipeline, generated synthetic multilingual training/validation datasets, standard `scikit-learn` model artifacts, and held-out benchmark report for **Secret Wards v5 (Hybrid Rules + Statistical ML)**.

---

## Re-run Training & Dataset Generation

Requires Python 3.10+ with `numpy`, `scipy`, and `scikit-learn` (used **offline at training time only**; the deployed competition engine in `repository root` runs **100% Python standard library only** with zero pip dependencies):

```bash
python training/train_models.py
```

---

## Generated Datasets (`training/generated_datasets/`)

All datasets are 100% synthetic (seed `20261126`) with **strictly disjoint** train, validation, and held-out evaluation entity pools and **zero overlap** with `dev/input`:

| File | Records | Contents |
|---|---:|---|
| `ner_train.jsonl` | 4,000 sequences | BIO-tagged English, Hindi (Devanagari), and Hinglish clinical notes + hard clinical negatives (`Dr.`, eponyms, drugs, doses, wards) |
| `ner_val.jsonl` | 1,000 sequences | Strictly disjoint held-out validation split (incl. 256 clinical negative controls) |
| `col_train.jsonl` | 3,150 columns | Header-blind synthetic column value distributions across 7 classes (`NAME`, `ADDRESS`, `PHONE`, `EMAIL`, `MRN`, `CLINICAL`, `OTHER`) |
| `col_val.jsonl` | 840 columns | Strictly disjoint held-out validation columns (incl. 120 clinical columns) |

Plus a live held-out demo pack exported to `datasets/ml_chaos_eval/` (`scrambled_headers_export.csv` + `unlabeled_ward_prose.txt`).

---

## Trained Models & Held-Out Benchmark (`training_report.json`)

### 1. Free-Text Multilingual NER (Disjoint Held-Out Validation, 1,000 Sequences)

| Model | Artifact | Precision | Recall | F1 | Clinical Negative FPs |
|---|---|---:|---:|---:|---:|
| **Linear-Chain CRF (Deployed, stdlib)** | `models/ner_crf.json.gz` (19.8 KB) | **1.0000** | **0.9743** | **0.9870** | **0 / 256** |
| `sklearn` LinearSVC (normal baseline) | `training/artifacts/sklearn_token_linearsvc.pkl` | 0.9971 | 0.9729 | 0.9848 | 0 / 256 |
| `sklearn` LogisticRegression (normal baseline) | `training/artifacts/sklearn_token_logreg.pkl` | 0.9970 | 0.9530 | 0.9745 | 0 / 256 |

### 2. Header-Blind Column-Value Classifier (Disjoint Held-Out Validation, 840 Columns)

| Model | Artifact | Accuracy | Macro F1 | Clinical Misclassified as PII |
|---|---|---:|---:|---:|
| **`sklearn` LogisticRegression (Deployed, stdlib)** | `models/col_clf.json.gz` (30.3 KB) + `.pkl` | **1.0000** | **1.0000** | **0 / 120** |
| `sklearn` LinearSVC (normal baseline) | `training/artifacts/sklearn_col_linearsvc.pkl` | 1.0000 | 1.0000 | 0 / 120 |
| `sklearn` MLPClassifier (normal baseline) | `training/artifacts/sklearn_col_mlp.pkl` | 1.0000 | 1.0000 | 0 / 120 |
| `sklearn` RandomForestClassifier (normal baseline) | `training/artifacts/sklearn_col_random_forest.pkl` | 0.9988 | 0.9988 | 0 / 120 |

### Why Zero-Dependency Deployment?
During training we benchmark standard `scikit-learn` models and train an exact L2-regularized Linear-Chain CRF via `scipy.optimize.minimize(..., method="L-BFGS-B")`. The winning weights are exported to gzipped JSON (`50.1 KB` total) and executed via exact Viterbi + Forward-Backward marginal decoding and softmax linear scoring in `ml_models.py` using **Python standard library only**.
