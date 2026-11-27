"""Black-box tests for v4 unseen-data generalization and custom policy overrides."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "main.py"


class V4PolicyAndUnseenTests(unittest.TestCase):
    def _run(self, inp: Path, out: Path, *, secret: str = "test-secret-v4", policy: Path | None = None):
        env = {**os.environ, "RAKSHA_SECRET": secret}
        cmd = [sys.executable, "-B", str(MAIN_PY), "--input", str(inp), "--output", str(out)]
        if policy is not None:
            cmd.extend(["--policy", str(policy)])
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr} stdout={proc.stdout}")
        return proc

    def test_unseen_chaos_dataset_cross_script_and_quarantine(self):
        chaos_dir = REPO_ROOT / "qa" / "fixtures" / "unseen_chaos"
        self.assertTrue(chaos_dir.is_dir())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            self._run(chaos_dir, out)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["files_total"], 5)
            self.assertEqual(report["counts"]["files_sanitized"], 4)
            self.assertEqual(report["counts"]["files_quarantined"], 1)
            self.assertIn("entities", report)
            self.assertGreater(report["entities"].get("NAME", 0), 0)

            records = [
                json.loads(line)
                for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_file_loc = {(r["file"], r["loc"]): r["patient"] for r in records}
            csv_row0 = by_file_loc[("sanitized/new_hospital_roster.csv", "row:0")]
            csv_row1 = by_file_loc[("sanitized/new_hospital_roster.csv", "row:1")]
            csv_row2 = by_file_loc[("sanitized/new_hospital_roster.csv", "row:2")]
            csv_row3 = by_file_loc[("sanitized/new_hospital_roster.csv", "row:3")]

            # Homonym separation: Mohd. Tariq Ansari (row 0) vs Tariq Ansari (row 1)
            self.assertIsNotNone(csv_row0)
            self.assertIsNotNone(csv_row1)
            self.assertNotEqual(csv_row0, csv_row1)

            # Cross-script Hindi note linked to English CSV row 0, and filename hashed
            txt_entries = [r for r in records if r["file"].endswith(".txt")]
            self.assertEqual(len(txt_entries), 1)
            self.assertNotIn("Tariq", txt_entries[0]["file"])
            self.assertEqual(txt_entries[0]["patient"], csv_row0)

            # JSON followup linked to row 2; FHIR Bundle linked to row 3
            self.assertEqual(by_file_loc[("sanitized/followup_export.json", "/visits/0")], csv_row2)
            fhir_record = next(r for r in records if r["loc"] == "doc" and r["file"].endswith(".json"))
            self.assertEqual(fhir_record["patient"], csv_row3)
            self.assertNotIn("Farhan", fhir_record["file"])

            # Verify no raw PII leaked in sanitized Hindi note, while doctor & clinical values survived
            note_text = (out / txt_entries[0]["file"]).read_text(encoding="utf-8")
            for forbidden in ("मोहम्मद", "तारिक़", "९८११२", "8821", "Tariq sahab"):
                self.assertNotIn(forbidden, note_text)
            for kept in ("Dr. Shalini Verma", "Paracetamol 650 mg", "78,000/uL", "118/76 mmHg"):
                self.assertIn(kept, note_text)

    def test_custom_policy_fields_and_secret_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "in"
            inp.mkdir()
            (inp / "custom.csv").write_text(
                "Patient Name,UHID,Age,Ward Clerk,Study Arm,Notes\n"
                "Zoya Khan,NEW-77001,34,Clerk-Amina,ARM-BETA,Badge EMP-123456 and CANARY-ALPHA ok\n",
                encoding="utf-8",
            )
            pol = root / "custom_policy.yaml"
            pol.write_text(
                "\n".join([
                    "age_band_years: 10",
                    "age_band_max_years: 20",
                    "age_k_anonymity: 1",
                    "date_shift_max_days: 90",
                    "shift_dates: true",
                    "generalize_ages: true",
                    "preserve_doctors: true",
                    "hash_sensitive_filenames: true",
                    "extra_redact_fields: Ward Clerk",
                    "extra_preserve_fields: Study Arm",
                    "extra_redact_terms: CANARY-ALPHA",
                    r"extra_redact_regex: EMP-\d{6}",
                ]) + "\n",
                encoding="utf-8",
            )
            out1 = root / "out1"
            out2 = root / "out2"
            self._run(inp, out1, secret="key-alpha", policy=pol)
            self._run(inp, out2, secret="key-beta", policy=pol)

            csv1 = (out1 / "sanitized" / "custom.csv").read_text(encoding="utf-8")
            self.assertIn("30-39", csv1)  # 10-year custom age band
            self.assertNotIn("Clerk-Amina", csv1)
            self.assertNotIn("EMP-123456", csv1)
            self.assertNotIn("CANARY-ALPHA", csv1)
            self.assertIn("ARM-BETA", csv1)
            self.assertIn("[CUSTOM]", csv1)

            # Unlinkability across rotated secrets
            r1 = json.loads((out1 / "records.jsonl").read_text(encoding="utf-8").strip())
            r2 = json.loads((out2 / "records.jsonl").read_text(encoding="utf-8").strip())
            self.assertNotEqual(r1["patient"], r2["patient"])


if __name__ == "__main__":
    unittest.main()
