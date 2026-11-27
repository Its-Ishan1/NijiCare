"""Black-box tests for v5 hybrid ML fallback (Linear-Chain CRF + Column Classifier) and edge-case fixes."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "main.py"
APP_ROOT = REPO_ROOT.parent


class V5HybridMLTests(unittest.TestCase):
    def _run(self, inp: Path, out: Path, *, policy: Path | None = None):
        env = {**os.environ, "RAKSHA_SECRET": "hybrid-v5-key"}
        cmd = [sys.executable, "-B", str(MAIN_PY), "--input", str(inp), "--output", str(out)]
        if policy is not None:
            cmd.extend(["--policy", str(policy)])
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr} stdout={proc.stdout}")
        return proc

    def test_hybrid_ml_catches_bare_prose_and_scrambled_headers_while_preserving_clinical(self):
        eval_dir = REPO_ROOT / "datasets" / "ml_chaos_eval"
        if not eval_dir.is_dir():
            self.skipTest("ml_chaos_eval dataset not present in repository")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_hybrid = root / "out_hybrid"
            out_rules = root / "out_rules"

            # 1. Run with Hybrid ML ON (default)
            self._run(eval_dir, out_hybrid)
            csv_text = (out_hybrid / "sanitized" / "scrambled_headers_export.csv").read_text(encoding="utf-8")
            note_text = (out_hybrid / "sanitized" / "unlabeled_ward_prose.txt").read_text(encoding="utf-8")

            # Scrambled CSV headers: names, addresses, phones, MRNs redacted via Column-Value Classifier!
            for leaked in ("Devika Deshpande", "Prakash Sengupta", "Nandini Awasthi", "Rajendra Bhandari",
                           "House 41 Azad Nagar", "Flat 108 Ashok Vihar", "9811445566", "HYB-80101"):
                self.assertNotIn(leaked, csv_text)
            # Clinical values & doctors in CSV preserved 100%!
            for kept in ("Tab Paracetamol 650 mg 1-1-1", "Tab Cefixime 200 mg BD",
                         "IV Normal Saline 100 mL/hr", "Dr. Vivek Kulkarni", "Dr. Meera Gokhale"):
                self.assertIn(kept, csv_text)

            # Bare prose note: unseen English & Hindi bare names & addresses redacted via Linear-Chain CRF!
            for leaked in ("Raghav Chauhan", "Kalpana Bisht", "सुरेश रावत", "House 41, Azad Nagar", "मकान 45, आजाद नगर"):
                self.assertNotIn(leaked, note_text)
            # Clinical eponyms, doctors, vitals, drugs, wards preserved 100%!
            for kept in ("Parkinson's disease (G20)", "Dr. Tushar Rathore", "Medical Ward 4B",
                         "BP 122/78 mmHg", "SpO2 98%", "HbA1c 6.4%", "डॉ. केशव ठाकुर",
                         "Tab Paracetamol 650 mg 1-1-1", "IV Normal Saline 100 mL/hr",
                         "Hodgkin lymphoma (C81.9)", "Bell's palsy (G51.0)"):
                self.assertIn(kept, note_text)

            # 2. Verify ml_fallback: false policy switch cleanly disables ML fallback
            pol_off = root / "rules_only.yaml"
            pol_off.write_text("ml_fallback: false\n", encoding="utf-8")
            self._run(eval_dir, out_rules, policy=pol_off)
            note_rules = (out_rules / "sanitized" / "unlabeled_ward_prose.txt").read_text(encoding="utf-8")
            # Confirm Hybrid ML actually caught bare names that pure rules alone missed
            self.assertIn("Raghav Chauhan", note_rules)
            self.assertNotIn("Raghav Chauhan", note_text)

    def test_unpadded_base64_and_all_digit_uuid_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            unpadded_b64 = base64.b64encode(b"hidden.user@clinic.test").decode().rstrip("=")
            (inp / "edge.json").write_text(
                json.dumps({
                    "encoded": unpadded_b64,
                    "uuid_digits": "550e8400-e29b-41d4-a716-446655440000",
                    "real_aadhaar": "4123-5678-9012",
                }),
                encoding="utf-8",
            )
            self._run(inp, out)
            res = json.loads((out / "sanitized" / "edge.json").read_text(encoding="utf-8"))
            self.assertEqual(res["encoded"], "[EMAIL]")
            self.assertEqual(res["uuid_digits"], "550e8400-e29b-41d4-a716-446655440000")
            self.assertIn(res["real_aadhaar"], ("[AADHAAR]", "[NATIONAL_ID]"))

    def test_dynamic_cross_script_and_swapped_order_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp, out = root / "in", root / "out"
            inp.mkdir()
            # 1. Free-text note mixing Hinglish, English-in-Hindi, swapped word order, typos, & clinical guards
            note = (
                "patient ka name : Vikram Solanki\n"
                "name patient ka: Sunita Rathore\n"
                "patient ka naam: Rajeshwar Tiwari\n"
                "naam patient ka: Kavita Chauhan\n"
                "mareez ka naam: दिनेश यादव\n"
                "rogi ka name: Meera Nair\n"
                "पेशेंट का नेम: रमेश कुमार\n"
                "नेम पेशेंट का: Ananya Gupta\n"
                "pesant ka nam: Farhan Siddiqui\n"
                "pita ka naam: Harishchandra Verma\n"
                "फादर का नेम: सुरेश मिश्रा\n"
                "ghar ka pata patient ka: House 22, Azad Nagar\n"
                "एड्रेस पेशेंट का: मकान 14, सिविल लाइन्स\n"
                "janam ki tarikh mareez ki: 1988-05-12\n"
                "डेट ऑफ बर्थ पेशेंट की: 14/09/1982\n"
                "phone patient ka: 9876543210\n"
                "मोबाइल नंबर पेशेंट का: +91 98112-33445\n"
                "patient ki umar: 42\n"
                "एज पेशेंट की: 37\n"
                "doctor ka naam: Dr. Arvind Joshi\n"
                "डॉक्टर का नेम: डॉ. शालिनी वर्मा\n"
                "dawa ka naam: Paracetamol 650 mg 1-1-1\n"
                "दवा का नेम: Amoxicillin 500 mg TDS\n"
                "hospital ka naam: City General Hospital\n"
                "अस्पताल का नाम: जिला अस्पताल\n"
                "bimari ka naam: Dengue fever (A90)\n"
            )
            (inp / "mixed_labels.txt").write_text(note, encoding="utf-8")

            # 2. Cross-file linkage using English-in-Hindi CSV headers + Hinglish follow-up note
            (inp / "eng_in_hindi_reg.csv").write_text(
                "पेशेंट का नेम,पेशेंट आईडी,डेट ऑफ बर्थ,मोबाइल नंबर,एज पेशेंट की,डिस्ट्रिक्ट पेशेंट का\n"
                "Vikram Solanki,DYN-88001,1988-05-12,9811223344,38,Sitapur\n"
                "Meera Nair,DYN-88002,1984-07-19,9822334455,42,Sitapur\n",
                encoding="utf-8",
            )
            (inp / "hinglish_followup.txt").write_text(
                "name patient ka: Vikram Solanki\n"
                "phone patient ka: +91 98112-23344\n"
                "patient ki umar: 38\n"
                "doctor ka naam: Dr. Arvind Joshi\n"
                "dawa ka naam: Tab Cefixime 200 mg BD\n",
                encoding="utf-8",
            )

            self._run(inp, out)
            san_note = (out / "sanitized" / "mixed_labels.txt").read_text(encoding="utf-8")
            san_csv = (out / "sanitized" / "eng_in_hindi_reg.csv").read_text(encoding="utf-8")
            san_fu = (out / "sanitized" / "hinglish_followup.txt").read_text(encoding="utf-8")

            # All patient/relative/address/DOB/phone values redacted across Hinglish & English-in-Hindi!
            for leaked in (
                "Vikram Solanki", "Sunita Rathore", "Rajeshwar Tiwari", "Kavita Chauhan",
                "दिनेश यादव", "Meera Nair", "रमेश कुमार", "Ananya Gupta", "Farhan Siddiqui",
                "Harishchandra Verma", "सुरेश मिश्रा", "House 22, Azad Nagar", "मकान 14, सिविल लाइन्स",
                "1988-05-12", "14/09/1982", "9876543210", "98112-33445",
            ):
                self.assertNotIn(leaked, san_note, f"Leaked {leaked} in:\n{san_note}")

            # Dynamic ages banded & Hindi-English label itself stays intact (not redacted into [NAME])
            self.assertIn("patient ki umar: 40-44", san_note)
            self.assertIn("एज पेशेंट की: 35-39", san_note)
            self.assertIn("एड्रेस पेशेंट का: [ADDRESS]", san_note)

            # All clinician, medicine, hospital, & diagnosis controls preserved 100%!
            for kept in (
                "Dr. Arvind Joshi", "डॉ. शालिनी वर्मा",
                "Paracetamol 650 mg 1-1-1", "Amoxicillin 500 mg TDS",
                "City General Hospital", "जिला अस्पताल", "Dengue fever (A90)",
            ):
                self.assertIn(kept, san_note, f"Lost clinical control {kept} in:\n{san_note}")

            # CSV with English-in-Hindi headers sanitized & linked with Hinglish follow-up note!
            self.assertNotIn("Vikram Solanki", san_csv)
            self.assertNotIn("DYN-88001", san_csv)
            self.assertNotIn("9811223344", san_csv)
            self.assertNotIn("Vikram Solanki", san_fu)
            self.assertIn("Dr. Arvind Joshi", san_fu)
            self.assertIn("Tab Cefixime 200 mg BD", san_fu)

            recs = [json.loads(l) for l in (out / "records.jsonl").read_text("utf-8").splitlines() if l.strip()]
            by_fl = {(r["file"], r["loc"]): r["patient"] for r in recs}
            p_csv0 = by_fl[("sanitized/eng_in_hindi_reg.csv", "row:0")]
            p_fu = by_fl[("sanitized/hinglish_followup.txt", "doc")]
            self.assertIsNotNone(p_csv0)
            self.assertEqual(p_csv0, p_fu)


if __name__ == "__main__":
    unittest.main()
