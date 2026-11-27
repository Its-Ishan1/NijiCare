"""Regressions for the privacy and linkage failures in the comprehensive audit."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class ReportedFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.source.mkdir()

    def run_model(self):
        output = self.root / "output"
        subprocess.run(
            [sys.executable, str(MAIN), "--input", str(self.source), "--output", str(output)],
            check=True, capture_output=True,
            env={**os.environ, "RAKSHA_SECRET": "reported-failure-regression-key"},
        )
        records = [json.loads(line) for line in (output / "records.jsonl").read_text().splitlines()]
        report = json.loads((output / "report.json").read_text())
        return output, records, report

    def test_patient_links_through_mixed_records_and_hides_keys_and_paths(self):
        (self.source / "hospital_01").mkdir()
        (self.source / "hospital_01" / "Meera_Iyer_register.csv").write_text(
            "patient_name,mrn,phone,dob,age\n"
            "Meera Iyer,H01-0001,+91 98765 43210,1991-08-14,34\n",
            encoding="utf-8",
        )
        keyed = {
            "Meera_Iyer": {
                "patient_identifiers": {"uhid": "UHID/H01/0001", "mrn": "MRN-778812"},
                "demographics": {"phone": "+91 (98765) 43210", "age": 34},
                "relationship": "Meera, W/o Rajan",
                "clinical_note": "S/o Rajan Iyer. Hb 8.9 g/dL; Ferrous sulfate 200 mg OD.",
            }
        }
        (self.source / "hospital_01" / "ward.json").write_text(
            json.dumps(keyed, ensure_ascii=False), encoding="utf-8"
        )
        (self.source / "hospital_01" / "doctor_notes.tsv").write_text(
            "patient\tnote_text\tprescription\n"
            '"Meera, W/o Rajan"\tMeera didi reviewed; C/O fever.\tFerrous sulfate 200 mg OD\n',
            encoding="utf-8",
        )
        (self.source / "hospital_02").mkdir()
        (self.source / "hospital_02" / "meera_discharge_note.txt").write_text(
            "Meera Iyer, W/o Rajan Iyer. Phone +91 98765 43210. "
            "C/O fever for 2 days. BP 118/76 mmHg; Hb 8.9 g/dL. "
            "Ramipril 5 mg; Dolo 650 BD x 5 days; 1-0-1.\n",
            encoding="utf-8",
        )

        output, records, report = self.run_model()
        meera = [r for r in records if "Meera" in r["file"] or "Meera" in r["loc"]]
        # All four records are found by their source kind, not by untrusted names
        # in the emitted locators (which must already be private).
        meera = [r for r in records if r["patient"]]
        self.assertEqual(len({r["patient"] for r in meera}), 1)
        self.assertEqual(len(meera), 4)
        sanitized = "\n".join(p.read_text(encoding="utf-8") for p in (output / "sanitized").rglob("*.*"))
        sidecars = (output / "records.jsonl").read_text() + (output / "report.json").read_text()
        paths = "\n".join(str(p.relative_to(output)) for p in (output / "sanitized").rglob("*"))
        for private in ("Meera_Iyer", "Meera Iyer", "9876543210", "98765 43210", "Rajan Iyer"):
            self.assertNotIn(private, sanitized + sidecars + paths)
        self.assertIn("Ferrous sulfate 200 mg OD", sanitized)
        self.assertIn("Hb 8.9 g/dL", sanitized)
        self.assertIn("C/O fever", sanitized)
        self.assertEqual(report["counts"]["files_total"], 4)

    def test_relative_span_preserves_clinical_values_and_phone_formats(self):
        (self.source / "clinical.txt").write_text(
            "Patient Name: Nisha Khan\nMRN: 12345678901234\n"
            "S/o: Salim Khan. BP 150/95 mmHg. Ramipril 5 mg; "
            "Dolo 650 BD x 5 days; 1-0-1. Parkinson's disease.\n"
            "C/O Ramesh; C/O fever. Reviewed by Dr. Ramesh.\n",
            encoding="utf-8",
        )
        (self.source / "phones.tsv").write_text(
            "case\tmention\tcontext\tclinical\n"
            "P1\t09876543211\tPatient mobile\tBP 118/76 mmHg\n"
            "P2\t0091-98765-43211\tPatient mobile\tRamipril 5 mg BD\n"
            "P3\t98765.43212\tPhone from registration\tDolo 650 BD x 5 days\n"
            'P4\t1-0-1\tMedication schedule\tMetformin 500 mg\n',
            encoding="utf-8",
        )
        output, records, _ = self.run_model()
        text = (output / "sanitized" / "clinical.txt").read_text()
        phone_table = (output / "sanitized" / "phones.tsv").read_text()
        self.assertIn("S/o: [RELATIVE]. BP 150/95 mmHg.", text)
        self.assertIn("Ramipril 5 mg", text)
        self.assertIn("Dolo 650 BD x 5 days", text)
        self.assertIn("1-0-1", text)
        self.assertIn("Parkinson's disease", text)
        self.assertIn("C/O [RELATIVE]; C/O fever", text)
        self.assertIn("Dr. Ramesh", text)
        for phone in ("09876543211", "0091-98765-43211", "98765.43212"):
            self.assertNotIn(phone, phone_table)
        self.assertIn("1-0-1", phone_table)
        self.assertIn("PSN-", (output / "sanitized" / "clinical.txt").read_text())
        self.assertEqual(len(records), 5)


if __name__ == "__main__":
    unittest.main()
