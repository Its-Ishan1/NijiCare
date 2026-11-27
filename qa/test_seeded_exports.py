"""End-to-end checks on independently generated export variations."""
import base64
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from case_factory import SCENARIOS, generate


def rows(text):
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;|\t")
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


class SeededExports(unittest.TestCase):
    def release(self, files):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        inp, out = root / "in", root / "out"
        inp.mkdir()
        for name, content in files.items():
            (inp / name).write_bytes(content.encode())
        subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "main.py"),
                        "--input", str(inp), "--output", str(out)], check=True, capture_output=True,
                       env={**os.environ, "RAKSHA_SECRET": "fixture-key"})
        records = [json.loads(line) for line in (out / "records.jsonl").read_bytes().splitlines()]
        return out / "sanitized", {(r["file"].removeprefix("sanitized/"), r["loc"]): r["patient"] for r in records}

    def test_seeded_scenarios(self):
        for scenario in SCENARIOS:
            for seed in (0, 1, 11, 2453, 2147483647):
                with self.subTest(scenario=scenario, seed=seed):
                    files = generate(scenario, seed)
                    self.assertEqual(files, generate(scenario, seed))
                    self.assertNotEqual(files, generate(scenario, seed+1))
                    out, linked = self.release(files)
                    original, released = rows(files["register.csv"]), rows((out/"register.csv").read_text("utf8"))
                    self.assertEqual(len(released), 3)
                    self.assertEqual(list(original[0]), list(released[0]))
                    ids = [linked["register.csv", f"row:{i}"] for i in range(3)]
                    self.assertTrue(all(ids))
                    self.assertEqual(len(set(ids)), 3)
                    for old, new in zip(original, released):
                        self.assertEqual(new["Diagnosis"], old["Diagnosis"])
                        self.assertEqual(new["Dose"], old["Dose"])
                        self.assertNotEqual(new["Admitted at"], old["Admitted at"])
                        self.assertEqual(dt.date.fromisoformat(new["Discharged at"])-dt.date.fromisoformat(new["Admitted at"]),
                                         dt.date.fromisoformat(old["Discharged at"])-dt.date.fromisoformat(old["Admitted at"]))
                        age_key = next(k for k in old if "age" in k.lower().split() or k == "Umar")
                        lo, hi = map(int, new[age_key].split("-"))
                        self.assertLessEqual(lo, int(old[age_key]))
                        self.assertGreaterEqual(hi, int(old[age_key]))
                    if scenario == "ward_transfer":
                        self.assertEqual([linked["transfers.tsv", f"row:{i}"] for i in range(2)], [ids[1], ids[0]])
                    elif scenario == "lab_exchange":
                        self.assertEqual(linked["callback.txt", "doc"], ids[0])
                        note = (out/"callback.txt").read_text("utf8")
                        self.assertIn("Mailbox [EMAIL]", note)
                        self.assertIn("HbA1c 6.4 % | Dose 2.5 mg", note)
                        self.assertEqual(json.loads((out/"catalog.json").read_bytes()), json.loads(files["catalog.json"]))
                    else:
                        self.assertEqual(linked["visits.json", "/visits/0"], ids[2])
                        record = json.loads((out/"visits.json").read_bytes())["visits"][0]
                        self.assertEqual(record["device_clock"], released[2]["Discharged at"]+"T09:42:10+05:45")
                        self.assertEqual(record["Landmark"], "[ADDRESS]")

    def test_hidden_text_and_clean_controls(self):
        email = "morning@example.test"
        variants = (email.replace("@", "%40"), email.replace("@", "&#64;"), email.replace("@", r"\u0040"),
                    email.encode().hex(), base64.b64encode(email.encode()).decode(), "morn\u200bing@example.test")
        files = {"reg.csv": "Patient Name,UHID\nSoren Vale,SV-32291\n",
                 "notes.json": json.dumps({"blocks": list(variants) + ["Sоren Vale", "Soren\u00ad Vale",
                     "SV-\u200b32291", "ICD J06.9", "0.5 µg | 1-0-1", "Dr. Soren Vale", "Na &amp; K",
                     "8730ac19-b6ef-4bd4-ac0c-7216bebe105b"]}),
                 "contact%40outside.test.txt": "Control\n"}
        out, _ = self.release(files)
        blocks = json.loads((out/"notes.json").read_bytes())["blocks"]
        self.assertEqual(blocks[:len(variants)], ["[EMAIL]"]*len(variants))
        self.assertEqual(blocks[len(variants):len(variants)+3], ["[NAME]", "[NAME]", "[MRN]"])
        self.assertEqual(blocks[-5:], json.loads(files["notes.json"])["blocks"][-5:])
        self.assertEqual(len(list(out.glob("item-*.txt"))), 1)

    def test_shared_callback_and_conflicting_demographics_abstain(self):
        out, linked = self.release({
            "reg.csv": "UHID,Patient Name,Mobile,DOB\nAB-31001,Nila Bari,7800012222,1970-03-01\n"
                       "AB-31002,Nila Kote,7800012222,1988-12-01\n",
            "family.txt": "Report for Nila ji\nCall back 7800012222\n",
            "conflict.csv": "Patient Name,Mobile,DOB\nNila Bari,7800012222,1999-01-01\n"})
        self.assertIsNone(linked["family.txt", "doc"])
        self.assertIsNone(linked["conflict.csv", "row:0"])
        self.assertNotEqual(linked["reg.csv", "row:0"], linked["reg.csv", "row:1"])

    def test_chartless_and_nested_json(self):
        data = {"visits": [
            {"id": "RV-55042", "name": "Indu Sen", "dob": "1990-01-01", "age": 36},
            {"name": "Indu Sen", "dob": "1990-01-01"},
            {"demographics": {"id": "RV-55042", "name": "Indu Sen"}},
        ], "catalog": {"name": "Serum sodium", "value": 142}}
        out, linked = self.release({"transfer.json": json.dumps(data)})
        obj = json.loads((out/"transfer.json").read_bytes())
        self.assertNotIn("Indu", json.dumps(obj))
        self.assertEqual(obj["catalog"], data["catalog"])
        self.assertEqual(obj["visits"][0]["age"], "35-39")
        pids = [linked["transfer.json", f"/visits/{i}"] for i in range(3)]
        self.assertTrue(pids[0])
        self.assertEqual(len(set(pids)), 1)
