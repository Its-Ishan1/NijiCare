"""Black-box checks on invented records. Run with python -m unittest discover -s qa."""
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


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "input"
        self.data.mkdir()

    def write(self, filename, text, encoding="utf-8"):
        path = self.data / filename
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(text.encode(encoding))

    def release(self, tag="A", secret="synthetic-test-key"):
        out = self.root / tag
        result = subprocess.run(
            [sys.executable, str(MAIN), "--input", str(self.data), "--output", str(out)],
            capture_output=True, env={**os.environ, "RAKSHA_SECRET": secret}, check=True,
        )
        self.assertNotIn(secret.encode(), result.stdout + result.stderr)
        report = json.loads((out / "report.json").read_bytes())
        self.assertEqual(len(report["files"]), len(list(self.data.rglob("*.*"))))
        records = [json.loads(line) for line in (out / "records.jsonl").read_text().splitlines()]
        return out / "sanitized", records, report

    def test_single_file_matches_folder_and_skips_siblings(self):
        self.write("ward.csv", "Patient name,UHID,Dose\nRavi Sharma,WX-45891,2.5 mg\n", "utf-16")
        expected, _, report = self.release()
        self.write("scan.pdf", "%PDF-test")
        for name, status in (("ward.csv", "sanitized"), ("scan.pdf", "quarantined")):
            out = self.root / ("single-" + name)
            subprocess.run([sys.executable, str(MAIN), "--input", str(self.data / name), "--output", str(out)],
                           env={**os.environ, "RAKSHA_SECRET": "synthetic-test-key"}, check=True, capture_output=True)
            result = json.loads((out / "report.json").read_bytes())
            self.assertEqual(result["counts"]["files_total"], 1)
            self.assertEqual(result["files"][0]["status"], status)
            if status == "sanitized":
                self.assertEqual(result["files"], report["files"])
                self.assertEqual((out / "sanitized" / name).read_bytes(), (expected / name).read_bytes())
                self.assertEqual((out / "records.jsonl").read_bytes(), (expected.parent / "records.jsonl").read_bytes())
            else:
                self.assertFalse(list((out / "sanitized").iterdir()))

    def test_table_dialect_dates_and_names(self):
        self.write("ward.csv", "Medical record number;PatientFullName;Admitted On;Discharged On;Dose\r\n"
                   '"xy/5a82";"Nirali Vale";22 Nov 2026;1 Dec 2026;"2.5 mg; once daily"\r\n', "utf-16")
        out, records, _ = self.release()
        rows = list(csv.reader(io.StringIO((out / "ward.csv").read_text()), delimiter=";"))
        self.assertEqual(len(rows[0]), 5)
        self.assertTrue(records[0]["patient"])
        self.assertIn(records[0]["patient"], rows[1])
        self.assertNotIn("Nirali Vale", rows[1])
        self.assertNotIn("xy/5a82", rows[1])
        start, end = map(dt.date.fromisoformat, rows[1][2:4])
        self.assertNotEqual(start, dt.date(2026, 11, 22))
        self.assertEqual((end-start).days, 9)
        self.assertEqual(rows[1][-1], "2.5 mg; once daily")

    def test_hindi_registration_header_redacts_mrn_and_links_row(self):
        self.write(
            "hindi_registration.csv",
            "रोगी का नाम,पंजीकरण संख्या,जन्मतिथि,मोबाइल,नोट\n"
            "काव्या शर्मा,TEST-CSV-102,1996-05-12,9876501102,बुखार ३ दिन से; दवा 5 mg\n",
        )
        out, records, _ = self.release()
        cleaned = (out / "hindi_registration.csv").read_text(encoding="utf-8")
        self.assertNotIn("TEST-CSV-102", cleaned)
        self.assertIn("[MRN]", cleaned)
        self.assertNotIn("काव्या शर्मा", cleaned)
        self.assertTrue(records[0]["patient"])
        self.assertIn("बुखार ३ दिन से; दवा 5 mg", cleaned)

    def test_common_misspelled_headers_still_redact_patient_fields(self):
        self.write(
            "misspelled_headers.csv",
            "pateent_id,naame,date_of_birht,doctar,admit_datte,phonne_number,diagonosis\n"
            "PID-2001,Arif Khan,1979-04-20,Dr. Ramesh Srivastava,2026-03-10,9811223344,High BP\n"
            "PID-2002,Arif Khan,1979-04-20,Dr. Amit Verma,2026-03-12,9811223344,Chest Pain\n"
            "PID-2001,Arif Khan,1979-04-20,Dr. Neha Singh,2026-03-15,9811223344,Hypertension\n",
        )
        out, records, _ = self.release()
        cleaned = (out / "misspelled_headers.csv").read_text(encoding="utf-8")
        for leaked in ("PID-2001", "PID-2002", "Arif Khan", "1979-04-20", "2026-03-10",
                       "2026-03-12", "2026-03-15", "9811223344"):
            self.assertNotIn(leaked, cleaned)
        for kept in ("Dr. Ramesh Srivastava", "Dr. Amit Verma", "Dr. Neha Singh",
                     "High BP", "Chest Pain", "Hypertension"):
            self.assertIn(kept, cleaned)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(record["patient"] for record in records))
        self.assertEqual(records[0]["patient"], records[2]["patient"])

    def test_nested_and_top_level_arrays(self):
        rows = [{"Full Patient Name": "Ritu Kandel", "chartNumber": "CH-22A63", "pulse": 72},
                {"Full Patient Name": "Ritu Kandel", "chartNumber": "CH-22A64", "pulse": 84}]
        self.write("list.json", json.dumps(rows))
        self.write("wrap.json", json.dumps({"payload": {"cases/v2": rows}}))
        out, records, _ = self.release()
        pids = {(r["file"],r["loc"]):r["patient"] for r in records}
        for i in (0, 1):
            pid = pids["sanitized/list.json", f"/{i}"]
            self.assertTrue(pid)
            self.assertEqual(pid, pids["sanitized/wrap.json", f"/payload/cases~1v2/{i}"])
            self.assertIn(pid, json.loads((out/"list.json").read_text())[i].values())
        self.assertNotEqual(pids["sanitized/list.json","/0"], pids["sanitized/list.json","/1"])
        self.assertNotIn("Ritu Kandel", (out/"wrap.json").read_text())

    def test_names_in_paths_keys_notes_and_clinician_context(self):
        self.write("reg.csv", "UHID,Patient Name\nAB-77881,Mitra Vyom\n")
        self.write("Mitra_Vyom/Handoff-Mitra-Vyom.txt", "Mitra Vyom arrived.\nReviewed by Dr. Mitra Vyom.\nDolo 650 BD\n")
        self.write("index.json", json.dumps({"Mitra Vyom": {"pulse": 61}}))
        out, records, report = self.release()
        names = [p.relative_to(out).as_posix() for p in out.rglob("*")]
        self.assertFalse(any("Mitra" in p for p in names))
        note = next(out.rglob("*.txt")).read_text()
        self.assertNotIn("Mitra Vyom arrived", note)
        self.assertIn("Dr. Mitra Vyom", note)
        self.assertIn("Dolo 650 BD", note)
        self.assertNotIn("Mitra", str(records) + str(report) + (out / "index.json").read_text())

    def test_filename_scrubbing_keyed_json_attachments_and_integer_age_banding(self):
        self.write(
            "register.csv",
            "patient_name,patient_id,age,phone\nAarav Mehta,H-A-1001,27,9000000001\n",
        )
        self.write(
            "Aarav_followup_bundle.json",
            json.dumps({
                "Aarav_Mehta": {
                    "hospital_patient_id": "H-A-1001",
                    "contact": {"phone": "9000000001"},
                    "age": 27,
                }
            }),
        )
        self.write(
            "aarav_mehta_discharge_note.txt",
            "Discharge note for Aarav Mehta. Phone: 9000000001. Follow-up advised.\n",
        )
        out, records, report = self.release()
        by_file = {}
        for record in records:
            by_file.setdefault(Path(record["file"]).name, []).append(record["patient"])
        outputs = [entry["output"] for entry in report["files"] if entry["output"]]
        self.assertFalse(any("Aarav" in path or "aarav" in path for path in outputs))
        self.assertTrue(all("Aarav" not in str(record) for record in records))
        self.assertEqual(len(records), 3)
        self.assertEqual(len({record["patient"] for record in records}), 1)
        self.assertNotIn("Aarav", (out.parent / "report.json").read_text(encoding="utf-8"))
        json_path = next(out.rglob("*.json"))
        sanitized = json.loads(json_path.read_text(encoding="utf-8"))
        keyed_record = next(iter(sanitized.values()))
        self.assertEqual(keyed_record["age"], "25-29")
        self.assertIn("PSN-", keyed_record["hospital_patient_id"])

    def test_unsafe_rows_and_invalid_json(self):
        self.write("bad.csv", "Name,UHID,Dose\nunexpected,extra,Someone Private,XR-12345,5 mg\n")
        self.write("dupe.json", '{"name":"one","name":"two"}')
        self.write("invalid.json", '{"pulse":NaN}')
        self.write("binary.txt", "MZ\x00\x00other")
        out, records, report = self.release()
        self.assertEqual(report["counts"]["files_quarantined"], 4)
        self.assertEqual(list(out.iterdir()), [])
        self.assertEqual(records, [])

    def test_conflicting_identifiers_abstain(self):
        self.write("reg.csv", "UHID,Patient Name,DOB,Aadhaar\n"
                   "AB-12345,Neel Roy,1990-01-01,123456789012\n"
                   "CD-12345,Neel Roy,1990-01-01,234567890123\n")
        _, records, _ = self.release()
        a, b = [r["patient"] for r in records]
        self.assertFalse(a and a == b)

    def test_clean_clinical_values_and_repeats(self):
        self.write("reg.csv", "Patient ID,Patient Name,Mobile\nCR-91234,Zita Kanu,9876500001\n")
        self.write("vitals.txt", "Dr. Zita Kanu recorded BP 120/80.\nRx: 0.5 mg, 1-0-1.\n")
        first, records, _ = self.release()
        second, again, _ = self.release("B")
        self.assertEqual((first/"vitals.txt").read_bytes(), (self.data/"vitals.txt").read_bytes())
        self.assertEqual(records, again)
        self.assertEqual((first/"reg.csv").read_bytes(), (second/"reg.csv").read_bytes())
        _, rekeyed, _ = self.release("C", "second-key")
        self.assertNotEqual(records, rekeyed)

    def test_meaning_trap_care_of_vs_complaint_of_and_clinical_values(self):
        self.write(
            "meaning.txt",
            "Patient Name: Kavya Rao\nMRN: MEANING-601\nDOB: 1991-06-12\n"
            "Relative Name: Ramesh\nC/O Ramesh\nC/O fever for 3 days\n"
            "Reviewed by Dr. Ramesh.\nDiagnosis: Parkinson's disease.\n"
            "Rx: Ramipril 5 mg; Dolo 650 BD x 5 days; 1-0-1.\n",
        )
        self.write(
            "meaning_hinglish.txt",
            "Patient ka naam: Kavya Rao\nUHID: MEANING-601\nDOB: 1991-06-12\n"
            "C/O Ramesh, bukhar 3 din se. C/O fever. Dr. Ramesh ne review kiya.\n"
            "Parkinson's disease. Rx: Ramipril 5 mg, Dolo 650 BD x 5 days, 1-0-1.\n",
        )
        out, _, _ = self.release()
        english = (out / "meaning.txt").read_text(encoding="utf-8")
        hinglish = (out / "meaning_hinglish.txt").read_text(encoding="utf-8")
        for text in (english, hinglish):
            self.assertIn("C/O [RELATIVE]", text)
            self.assertIn("C/O fever", text)
            self.assertIn("Dr. Ramesh", text)
            self.assertIn("Parkinson's disease", text)
            self.assertIn("Ramipril 5 mg", text)
            self.assertIn("Dolo 650 BD x 5 days", text)
            self.assertIn("1-0-1", text)
        self.assertIn("Relative Name: [RELATIVE]", english)

    def test_known_case_of_shorthand_preserves_clinical_conditions(self):
        self.write(
            "outpatient.json",
            json.dumps({
                "patient_name": "Nisha Khan",
                "mrn": "KCO-701",
                "history": (
                    "K/C/O HTN on treatment. K / C / O diabetes mellitus. "
                    "C/O Ramesh, family attendant. C/O fever for 3 days."
                ),
            }, ensure_ascii=False),
        )
        out, _, _ = self.release()
        result = json.loads((out / "outpatient.json").read_text(encoding="utf-8"))
        self.assertIn("K/C/O HTN on treatment", result["history"])
        self.assertIn("K / C / O diabetes mellitus", result["history"])
        self.assertIn("C/O [RELATIVE]", result["history"])
        self.assertIn("C/O fever for 3 days", result["history"])

    def test_fragmented_name_and_spouse_clue_attaches_only_when_unambiguous(self):
        self.write(
            "charts.csv",
            "Patient Name,MRN,DOB,Phone,Relative Name\n"
            "Meera Shah,FRAG-101,1988-04-17,9876509101,Rajan Das\n"
            "Meera Shah,FRAG-102,1991-09-22,9876509102,Karan Das\n"
            "Meera Shah,FRAG-103,1994-02-11,9876509103,Suresh Das\n"
            "Meera Shah,FRAG-104,1995-03-12,9876509104,Suresh Das\n",
        )
        self.write("fragment.txt", "Meera, W/o Rajan. Follow-up for hypertension.\n")
        self.write("ambiguous.txt", "Meera, W/o Suresh. Reviewed today.\n")
        _, records, _ = self.release()
        by_locator = {(record["file"], record["loc"]): record["patient"] for record in records}
        first = by_locator[("sanitized/charts.csv", "row:0")]
        second = by_locator[("sanitized/charts.csv", "row:1")]
        fragment = by_locator[("sanitized/fragment.txt", "doc")]
        ambiguous = by_locator[("sanitized/ambiguous.txt", "doc")]
        self.assertNotEqual(first, second)
        self.assertEqual(fragment, first)
        self.assertNotEqual(first, by_locator[("sanitized/charts.csv", "row:2")])
        self.assertIsNone(ambiguous)

    def test_three_script_name_variants_link_as_one_patient_group(self):
        self.write(
            "variants.csv",
            "Patient Name,MRN,DOB,Phone,Clinical Note\n"
            "Mohammad Arif Khan,LANG-301,1979-04-20,9811223344,High BP\n"
            "Mohd Arif Khan,LANG-302,1979-04-20,9811223344,Hypertension\n"
            "मोहम्मद आरिफ खान,LANG-303,1979-04-20,9811223344,बीपी उच्च\n",
        )
        out, records, _ = self.release()
        self.assertEqual(len(records), 3)
        self.assertEqual(len({record["patient"] for record in records}), 1)
        sanitized = (out / "variants.csv").read_text(encoding="utf-8")
        self.assertNotIn("Mohammad Arif Khan", sanitized)
        self.assertNotIn("मोहम्मद आरिफ खान", sanitized)

    def test_same_name_and_same_phone_share_id_but_mismatches_do_not(self):
        self.write(
            "phone_name.csv",
            "Patient Name,MRN,Phone,Clinical Note\n"
            "Arjun Mehta,PAIR-101,9876509301,BP 120/80\n"
            "Arjun Mehta,PAIR-102,9876509301,Hb 13 g/dL\n"
            "Arjun Mehta,PAIR-103,9876509302,Fever for 2 days\n"
            "Karan Mehta,PAIR-104,9876509301,Pulse 82/min\n",
        )
        _, records, _ = self.release()
        ids = [record["patient"] for record in records]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])
        self.assertNotEqual(ids[0], ids[3])

    def test_phone_conflicts_separate_same_name_homonyms_across_nested_json_and_hindi_tsv(self):
        nested = {
            "patients": [
                {"patient": {"name": "Meera Nair", "mrn": "NEST-HOM-101",
                             "dob": "1990-06-14", "phone": "9000000301"}},
                {"patient": {"name": "Meera Nair", "mrn": "NEST-HOM-102",
                             "dob": "1990-06-14", "phone": "9000000302"}},
                {"patient": {"name": "Meera Nair", "mrn": "NEST-HOM-103",
                             "dob": "1990-06-14", "phone": "9000000301"}},
            ]
        }
        self.write("nested.json", json.dumps(nested, ensure_ascii=False))
        self.write(
            "hindi.tsv",
            "रोगी का नाम\tपंजीकरण संख्या\tजन्मतिथि\tमोबाइल\tनोट\n"
            "मीरा नायर\tHIN-HOM-201\t1990-06-14\t9000000401\tबुखार ३ दिन से\n"
            "मीरा नायर\tHIN-HOM-202\t1990-06-14\t9000000402\tBP 120/80\n",
        )
        _, records, _ = self.release()
        linked = {(r["file"], r["loc"]): r["patient"] for r in records}
        nested_ids = [linked[("sanitized/nested.json", f"/patients/{i}")] for i in range(3)]
        self.assertEqual(nested_ids[0], nested_ids[2])
        self.assertNotEqual(nested_ids[0], nested_ids[1])
        hindi_ids = [linked[("sanitized/hindi.tsv", f"row:{i}")] for i in range(2)]
        self.assertNotEqual(hindi_ids[0], hindi_ids[1])

    def test_fhir_rotation_and_dangling_reference(self):
        entries = [
            {"fullUrl":"urn:uuid:47cb1f1b-936d-4681-b6ae-d7e7d6cb8dc2",
             "resource":{"resourceType":"Patient","id":"p-old","identifier":[{"value":"PX-55314"}],
                         "name":[{"text":"Anvi Taro"}]}},
            {"resource":{"resourceType":"Observation","id":"obs-old","status":"final",
                         "code":{"text":"pulse"},"valueQuantity":{"value":72,"unit":"/min"},
                         "subject":{"reference":"Patient/p-old","display":"Anvi Taro"}}},
        ]
        bundle = {"resourceType":"Bundle","type":"collection","entry":entries}
        self.write("ok.json", json.dumps(bundle))
        entries[1]["resource"]["subject"]["reference"] = "Patient/missing"
        self.write("bad.json", json.dumps(bundle))
        first, _, report = self.release()
        second, _, _ = self.release("B","different-demo-secret")
        self.assertEqual(report["counts"]["files_quarantined"], 1)
        new = json.loads((first/"ok.json").read_text())["entry"]
        obs = new[1]["resource"]
        self.assertEqual(obs["subject"]["reference"], "Patient/" + new[0]["resource"]["id"])
        self.assertEqual(obs["valueQuantity"]["value"], 72)
        self.assertNotIn("obs-old", (first/"ok.json").read_text())
        self.assertNotIn(obs["id"], (second/"ok.json").read_text())

    def test_fhir_impossible_or_malformed_dates_are_quarantined(self):
        cases = [
            ("bad_birth.json", "1975-02-30", "2026-03-10"),
            ("bad_encounter.json", "1975-02-28", "2026-13-45"),
            ("timezone_missing.json", "1975-02-28", "2026-03-10T09:30:00"),
        ]
        for filename, birth_date, start in cases:
            bundle = {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {"resource": {
                        "resourceType": "Patient", "id": "patient-1",
                        "identifier": [{"system": "urn:test", "value": filename}],
                        "name": [{"text": "Synthetic Patient"}],
                        "birthDate": birth_date,
                    }},
                    {"resource": {
                        "resourceType": "Encounter", "id": "encounter-1",
                        "status": "finished",
                        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                                  "code": "AMB"},
                        "subject": {"reference": "Patient/patient-1"},
                        "period": {"start": start},
                    }},
                ],
            }
            self.write(filename, json.dumps(bundle))

        out, records, report = self.release()
        self.assertEqual(report["counts"]["files_quarantined"], 3)
        self.assertEqual(report["counts"]["files_sanitized"], 0)
        self.assertEqual(records, [])
        self.assertEqual(
            {item["reason"] for item in report["files"]},
            {"invalid_fhir_date"},
        )
        self.assertEqual(list(out.iterdir()), [])

    def test_json_payloads_and_field_types(self):
        self.write("wrapped.json", json.dumps({"attachmentBase64":"dGVzdC1wcml2YXRl",
                                                "patient":{"name":"Lal Miro", "aadhar_no":123456789012},
                                                "lab":{"name":"sodium","value":142}}))
        out, _, _ = self.release()
        obj = json.loads((out/"wrapped.json").read_text())
        self.assertEqual(obj["attachmentBase64"], "")
        self.assertIs(type(obj["patient"]["aadhar_no"]), int)
        self.assertNotEqual(obj["patient"]["aadhar_no"], 123456789012)
        self.assertEqual(obj["lab"], {"name":"sodium","value":142})

    def test_dialect_encoding_matrix(self):
        header = ["BeneficiaryFullName","PatientRecordNumber","Gender","dose"]
        for i, sep in enumerate((",","\t",";","|")):
            for j, encoding in enumerate(("utf-8-sig","utf-16-be","utf-16-le","cp1252")):
                buf = io.StringIO(newline="")
                writer = csv.writer(buf, delimiter=sep)
                writer.writerows([header, ["José Borel", "KF-83A79", "M", "0.25 mg"]])
                self.write(f"ward{i}{j}.csv", buf.getvalue(), encoding)
        out, records, report = self.release()
        self.assertEqual(report["counts"]["files_sanitized"], 16)
        pids = {record["patient"] for record in records}
        self.assertEqual(len(pids), 1)
        self.assertNotIn(None, pids)
        for i, sep in enumerate((",","\t",";","|")):
            for j in range(4):
                text = (out / f"ward{i}{j}.csv").read_text(encoding="utf-8")
                rows = list(csv.reader(io.StringIO(text), delimiter=sep))
                self.assertEqual(rows[0], header)
                self.assertEqual(rows[1][-1], "0.25 mg")
                self.assertNotIn("Borel", text)

    def test_sparse_age_bands_contain_age(self):
        self.write("district.csv","UHID,Patient Name,Age,District\n"
                   "XP-44101,Lina Bora,21,East county\nXP-44102,Amal Iyer,28,East county\n")
        out, _, _ = self.release()
        with (out/"district.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["Age"], rows[1]["Age"])
        for actual, row in zip((21,28),rows):
            lo, hi = map(int,row["Age"].split("-"))
            self.assertLessEqual(lo, actual)
            self.assertGreaterEqual(hi, actual)

    def test_clinical_catalog_names_are_not_patients(self):
        self.write("formulary.csv","Name,Unit\nSodium Chloride,mmol/L\n")
        self.write("note.txt","Rx: Sodium Chloride 5 mg.\n")
        out, _, _ = self.release()
        self.assertEqual((out/"note.txt").read_bytes(), (self.data/"note.txt").read_bytes())

    def test_shift_handoff_uses_role_context(self):
        self.write("night.txt", "20:31 - Elin Mero - H/O cough.\n"
                   "20:32 - Dr. Elin Mero completed rounds.\n")
        out, _, _ = self.release()
        text = (out/"night.txt").read_text()
        self.assertEqual(text.count("Elin Mero"), 1)
        self.assertIn("Dr. Elin Mero", text)
        self.assertIn("H/O cough", text)

    def test_adaptive_age_bands_and_changed_labels(self):
        self.write(
            "ward_roster.tsv",
            "Beneficiary Chart ID\tRegistrant Legal Name\tBirth Date\tEmergency Callback\tUmar\tJila\tAdmit Date\tDischarge Date\tDaily Dose\n"
            "NW-81001\tTaran Vaid\t1952-03-14\t9812304411\t74\tKheri\t2026-08-10\t2026-08-19\tAmlodipine 5 mg 1-0-1\n"
            "NW-81002\tTaran Vaid\t2004-07-19\t9812304422\t22\tKheri\t2026-09-01\t2026-09-06\tCetirizine 10 mg 0-0-1\n"
            "NW-81003\tKomal Sahu\t1997-11-05\t9812304433\t28\tKheri\t2026-09-12\t2026-09-15\tParacetamol 650 mg BD\n"
            "NW-81004\tOmkar Negi\t1933-01-22\t9812304444\t93\tKheri\t2026-10-03\t2026-10-09\tRamipril 2.5 mg OD\n"
            "NW-81005\tDevika Bist\t2001-05-09\t9812304455\t25\tPilibhit\t2026-10-14\t2026-10-18\tPantoprazole 40 mg 1-0-0\n"
            "NW-81006\tNalin Rawat\t1958-09-30\t9812304466\t67\tPilibhit\t2026-10-20\t2026-10-27\tMetformin 500 mg 1-0-1\n",
        )
        self.write(
            "clinic_followup.csv",
            "Patient Identifier,Beneficiary Display Name,Birth Date,Emergency Callback,Patient Age (Yrs),Home District,Consultant,Visit Dt,Prescribed Dose\n"
            "CL-92001,Taran Vaid,1952-03-14,+91 98123-04411,74,Kheri,Dr. Taran Vaid,2026-08-26,Amlodipine 5 mg 1-0-1\n"
            "NW-81004,ओमकार नेगी,1933-01-22,9812304444,93,Kheri,Dr. Meenal Joshi,2026-10-16,Ramipril 2.5 mg OD\n"
            "NW-81006,Nalin Rawat,1958-09-30,9812304466,68,Pilibhit,Dr. Meenal Joshi,2026-11-02,Metformin 500 mg 1-0-1\n",
        )
        self.write(
            "handoff_note.txt",
            "Registrant Legal Name: तरन वैद   Beneficiary Chart ID: NW-81001\n"
            "Patient Age (Yrs): 74\n"
            "Admit Date: 10 Aug 2026\n"
            "Discharge Date: 19 Aug 2026\n"
            "Consultant: Dr. Taran Vaid\n"
            "Rx: Tab Amlodipine 5 mg 1-0-1 x 14 days\n",
        )
        out, records, _ = self.release()
        pids = {(r["file"], r["loc"]): r["patient"] for r in records}
        self.assertEqual(pids["sanitized/ward_roster.tsv", "row:0"], pids["sanitized/clinic_followup.csv", "row:0"])
        self.assertEqual(pids["sanitized/ward_roster.tsv", "row:0"], pids["sanitized/handoff_note.txt", "doc"])
        self.assertNotEqual(pids["sanitized/ward_roster.tsv", "row:0"], pids["sanitized/ward_roster.tsv", "row:1"])

        roster = list(csv.DictReader(io.StringIO((out / "ward_roster.tsv").read_text(encoding="utf-8")), delimiter="\t"))
        followup = list(csv.DictReader(io.StringIO((out / "clinic_followup.csv").read_text(encoding="utf-8"))))
        note = (out / "handoff_note.txt").read_text(encoding="utf-8")

        self.assertEqual(roster[0]["Umar"], roster[3]["Umar"])
        self.assertEqual(roster[4]["Umar"], roster[5]["Umar"])
        self.assertEqual(followup[0]["Patient Age (Yrs)"], roster[0]["Umar"])
        self.assertEqual(followup[2]["Patient Age (Yrs)"], roster[5]["Umar"])
        self.assertIn(f"Patient Age (Yrs): {roster[0]['Umar']}", note)
        for row, actual in zip(roster, (74, 22, 28, 93, 25, 67)):
            lo, hi = map(int, row["Umar"].split("-"))
            self.assertTrue(lo <= actual <= hi)
        lo68, hi68 = map(int, followup[2]["Patient Age (Yrs)"].split("-"))
        self.assertTrue(lo68 <= 68 <= hi68)

        for row, stay in zip(roster, (9, 5, 3, 6, 4, 7)):
            start = dt.date.fromisoformat(row["Admit Date"])
            end = dt.date.fromisoformat(row["Discharge Date"])
            self.assertEqual((end - start).days, stay)
        self.assertEqual(roster[0]["Daily Dose"], "Amlodipine 5 mg 1-0-1")
        self.assertIn("Consultant: Dr. Taran Vaid", note)
        self.assertNotIn("तरन वैद", note)
        self.assertNotIn("1952-03-14", (out / "ward_roster.tsv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
