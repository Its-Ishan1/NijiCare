"""Evaluate before/after metrics on the fresh synthetic case with changed field labels."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import itertools
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KIT = ROOT.parent / "toolkit" / "Secret-Wards-ToolKit-main"

TRUTH_PATIENTS = {
    ("sanitized/ward_roster.tsv", "row:0"): "P1",
    ("sanitized/ward_roster.tsv", "row:1"): "P2",
    ("sanitized/ward_roster.tsv", "row:2"): "P3",
    ("sanitized/ward_roster.tsv", "row:3"): "P4",
    ("sanitized/ward_roster.tsv", "row:4"): "P5",
    ("sanitized/ward_roster.tsv", "row:5"): "P6",
    ("sanitized/clinic_followup.csv", "row:0"): "P1",
    ("sanitized/clinic_followup.csv", "row:1"): "P4",
    ("sanitized/clinic_followup.csv", "row:2"): "P6",
    ("sanitized/handoff_note.txt", "doc"): "P1",
    ("sanitized/fhir_visit_1.json", "doc"): "P1",
    ("sanitized/fhir_visit_2.json", "doc"): "P4",
}

EXPECTED_STAYS = {
    ("ward_roster.tsv", 0): 9,
    ("ward_roster.tsv", 1): 5,
    ("ward_roster.tsv", 2): 3,
    ("ward_roster.tsv", 3): 6,
    ("ward_roster.tsv", 4): 4,
    ("ward_roster.tsv", 5): 7,
    ("handoff_note.txt", 0): 9,
    ("fhir_visit_1.json", 0): 9,
    ("fhir_visit_2.json", 0): 6,
}

EXPECTED_AGES = [
    ("ward_roster.tsv", 0, "Umar", 74),
    ("ward_roster.tsv", 1, "Umar", 22),
    ("ward_roster.tsv", 2, "Umar", 28),
    ("ward_roster.tsv", 3, "Umar", 93),
    ("ward_roster.tsv", 4, "Umar", 25),
    ("ward_roster.tsv", 5, "Umar", 67),
    ("clinic_followup.csv", 0, "Patient Age (Yrs)", 74),
    ("clinic_followup.csv", 1, "Patient Age (Yrs)", 93),
    ("clinic_followup.csv", 2, "Patient Age (Yrs)", 68),
]


def parse_iso(text: str) -> dt.date | None:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return dt.date.fromisoformat(m[1]) if m else None


def evaluate(repo_dir: Path, out_dir: Path, runs: int = 5, kit: Path = KIT) -> dict:
    inp_dir = ROOT / "input"
    sys.path.insert(0, str(repo_dir / "qa"))
    import release_risk

    times = []
    with tempfile.TemporaryDirectory(prefix="syn-bench-") as scratch:
        for i in range(runs):
            target = out_dir if i == 0 else Path(scratch) / str(i)
            t0 = time.monotonic()
            subprocess.run(
                [sys.executable, "-B", str(repo_dir / "main.py"), "--input", str(inp_dir), "--output", str(target)],
                env={**os.environ, "RAKSHA_SECRET": "synthetic-eval-secret"},
                check=True,
                capture_output=True,
            )
            times.append(time.monotonic() - t0)

    contract = subprocess.run(
        [sys.executable, str(kit / "validate_output.py"), "--input", str(inp_dir), "--output", str(out_dir)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    official_risk = release_risk.measure(out_dir)

    san = out_dir / "sanitized"
    recs = {(r["file"], r["loc"]): r["patient"] for r in map(json.loads, (out_dir / "records.jsonl").read_text("utf-8").splitlines())}

    # Check all-table uniqueness including changed-label columns (Patient Age (Yrs) + Home District)
    all_table_profiles = defaultdict(set)
    banded_age_cells = 0
    truthful_age_cells = 0
    total_age_cells = len(EXPECTED_AGES) + 1  # +1 for handoff_note.txt

    roster_rows = list(csv.DictReader(io.StringIO((san / "ward_roster.tsv").read_text(encoding="utf-8")), delimiter="\t"))
    followup_rows = list(csv.DictReader(io.StringIO((san / "clinic_followup.csv").read_text(encoding="utf-8"))))
    note_text = (san / "handoff_note.txt").read_text(encoding="utf-8")

    for row_idx, row in enumerate(roster_rows):
        pid = recs.get(("sanitized/ward_roster.tsv", f"row:{row_idx}"))
        if pid:
            all_table_profiles[pid].add((row["Umar"], row["Jila"].strip().casefold()))
    for row_idx, row in enumerate(followup_rows):
        pid = recs.get(("sanitized/clinic_followup.csv", f"row:{row_idx}"))
        if pid:
            all_table_profiles[pid].add((row["Patient Age (Yrs)"], row["Home District"].strip().casefold()))

    for fname, idx, col, actual in EXPECTED_AGES:
        rows = roster_rows if fname == "ward_roster.tsv" else followup_rows
        val = rows[idx][col].strip()
        m = re.fullmatch(r"(\d{1,3})-(\d{1,3})", val)
        if m:
            banded_age_cells += 1
            lo, hi = int(m[1]), int(m[2])
            if lo <= actual <= hi:
                truthful_age_cells += 1
        elif val == str(actual):
            truthful_age_cells += 1  # exact age contains actual, though unbanded

    note_age_m = re.search(r"Patient Age \(Yrs\):\s*(\S+)", note_text)
    if note_age_m:
        m = re.fullmatch(r"(\d{1,3})-(\d{1,3})", note_age_m[1])
        if m:
            banded_age_cells += 1
            if int(m[1]) <= 74 <= int(m[2]):
                truthful_age_cells += 1
        elif note_age_m[1] == "74":
            truthful_age_cells += 1

    # Clinical accuracy: doses, clinicians, diagnoses, complaints
    clinical_checks = [
        roster_rows[0]["Daily Dose"] == "Amlodipine 5 mg 1-0-1",
        roster_rows[1]["Daily Dose"] == "Cetirizine 10 mg 0-0-1",
        roster_rows[2]["Daily Dose"] == "Paracetamol 650 mg BD",
        roster_rows[3]["Daily Dose"] == "Ramipril 2.5 mg OD",
        roster_rows[4]["Daily Dose"] == "Pantoprazole 40 mg 1-0-0",
        roster_rows[5]["Daily Dose"] == "Metformin 500 mg 1-0-1",
        followup_rows[0]["Prescribed Dose"] == "Amlodipine 5 mg 1-0-1",
        followup_rows[1]["Prescribed Dose"] == "Ramipril 2.5 mg OD",
        followup_rows[2]["Prescribed Dose"] == "Metformin 500 mg 1-0-1",
        followup_rows[0]["Consultant"] == "Dr. Taran Vaid",
        followup_rows[1]["Consultant"] == "Dr. Meenal Joshi",
        followup_rows[2]["Consultant"] == "Dr. Meenal Joshi",
        "Consultant: Dr. Taran Vaid" in note_text,
        "giddiness x 3 days" in note_text,
        "Tab Amlodipine 5 mg 1-0-1 x 14 days" in note_text,
        '"I10"' in (san / "fhir_visit_1.json").read_text("utf-8"),
        '"I10"' in (san / "fhir_visit_2.json").read_text("utf-8"),
    ]

    # Hospital-stay lengths & date shifting
    stay_checks = []
    dates_shifted = []
    orig_admits = ["2026-08-10", "2026-09-01", "2026-09-12", "2026-10-03", "2026-10-14", "2026-10-20"]
    for i, row in enumerate(roster_rows):
        d1, d2 = parse_iso(row["Admit Date"]), parse_iso(row["Discharge Date"])
        stay_ok = bool(d1 and d2 and (d2 - d1).days == EXPECTED_STAYS[("ward_roster.tsv", i)])
        stay_checks.append(stay_ok)
        dates_shifted.append(row["Admit Date"] != orig_admits[i])

    nd1 = parse_iso(re.search(r"Admit Date:\s*(.+)", note_text)[1])
    nd2 = parse_iso(re.search(r"Discharge Date:\s*(.+)", note_text)[1])
    stay_checks.append(bool(nd1 and nd2 and (nd2 - nd1).days == 9))
    dates_shifted.append("2026-08-10" not in note_text and "10 Aug 2026" not in note_text)

    for j, exp_days in ((1, 9), (2, 6)):
        b = json.loads((san / f"fhir_visit_{j}.json").read_text("utf-8"))
        enc = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Encounter")
        fd1 = dt.date.fromisoformat(enc["period"]["start"][:10])
        fd2 = dt.date.fromisoformat(enc["period"]["end"][:10])
        stay_checks.append((fd2 - fd1).days == exp_days)

    # Direct identifier hygiene
    all_san_text = "\n".join(p.read_text("utf-8") for p in sorted(san.rglob("*")) if p.is_file())
    scrubbed_for_taran = all_san_text.replace("Dr. Taran Vaid", "")
    pii_tokens = [
        "Taran Vaid", "तरन वैद", "Komal Sahu", "Omkar Negi", "ओमकार नेगी", "Devika Bist", "Nalin Rawat",
        "NW-81001", "NW-81002", "NW-81003", "NW-81004", "NW-81005", "NW-81006", "CL-92001",
        "9812304411", "9812304422", "9812304433", "9812304444", "9812304455", "9812304466",
        "1952-03-14", "2004-07-19", "1997-11-05", "1933-01-22", "2001-05-09", "1958-09-30",
    ]
    pii_leaks = [tok for tok in pii_tokens if tok in scrubbed_for_taran]

    # Pairwise linkage precision / recall / F0.5
    items = [(TRUTH_PATIENTS[k], recs.get(k)) for k in sorted(TRUTH_PATIENTS)]
    by_true = defaultdict(list)
    by_pred = defaultdict(list)
    for idx_u, (tp_id, yp_id) in enumerate(items):
        by_true[tp_id].append(idx_u)
        if yp_id:
            by_pred[yp_id].append(idx_u)
    true_pairs = sum(len(v) * (len(v) - 1) // 2 for v in by_true.values())
    tp = fp = 0
    for members in by_pred.values():
        for i, j in itertools.combinations(members, 2):
            if items[i][0] == items[j][0]:
                tp += 1
            else:
                fp += 1
    fn = true_pairs - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f05 = (1.25 * prec * rec / (0.25 * prec + rec)) if prec + rec else 0.0
    homonym_separated = recs.get(("sanitized/ward_roster.tsv", "row:0")) != recs.get(("sanitized/ward_roster.tsv", "row:1"))

    return {
        "contract": contract,
        "official_release_risk": official_risk,
        "all_tables_including_changed_labels": release_risk.summarize(all_table_profiles),
        "age_cells_banded": f"{banded_age_cells}/{total_age_cells}",
        "age_cells_truthful": f"{truthful_age_cells}/{total_age_cells}",
        "clinical_probes_kept": f"{sum(clinical_checks)}/{len(clinical_checks)}",
        "stay_lengths_preserved": f"{sum(stay_checks)}/{len(stay_checks)}",
        "admit_dates_shifted": f"{sum(dates_shifted)}/{len(dates_shifted)}",
        "direct_pii_leaks": pii_leaks,
        "linkage": {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 4), "recall": round(rec, 4), "f05": round(f05, 4),
            "homonym_separated": homonym_separated,
        },
        "median_seconds": round(statistics.median(times), 4),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--kit", type=Path, default=KIT)
    args = ap.parse_args()
    print(json.dumps(evaluate(args.repo.resolve(), args.output.resolve(), kit=args.kit.resolve()), indent=2))
