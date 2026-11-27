"""Aggregate uniqueness of linked pseudonyms in a sanitized Secret Wards release."""
import argparse
import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path


def summarize(profiles):
    groups = defaultdict(set)
    for pid, values in profiles.items():
        for value in values:
            groups[value].add(pid)
    singletons = {next(iter(members)) for members in groups.values() if len(members) == 1}
    return {"covered_pseudonyms": len(profiles), "unique_on_at_least_one_observation": len(singletons)}


def measure(out):
    by_file = defaultdict(dict)
    for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["patient"]:
            by_file[entry["file"]][entry["loc"]] = entry["patient"]
    demographics, encounters = defaultdict(set), defaultdict(set)
    for filename, records in by_file.items():
        path = out / filename
        if path.suffix.lower() in {".csv", ".tsv"}:
            with path.open(encoding="utf-8", newline="") as stream:
                header = stream.readline()
                stream.seek(0)
                sep = max((",","\t",";","|"), key=header.count)
                for i, row in enumerate(csv.DictReader(stream, delimiter=sep)):
                    labels = {re.sub(r"[\s_-]", "", k.casefold()): v for k, v in row.items() if k}
                    age = labels.get("age") or labels.get("umar")
                    district = labels.get("district") or labels.get("jila")
                    pid = records.get(f"row:{i}")
                    if pid and age and district and re.fullmatch(r"\d{1,3}-\d{1,3}", age) and "[" not in district:
                        demographics[pid].add((age, district.strip().casefold()))
        elif path.suffix.lower() == ".json" and "doc" in records:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("resourceType") != "Bundle":
                continue
            weeks, codes = set(), set()
            for entry in data.get("entry", []):
                resource = entry["resource"]
                if resource["resourceType"] == "Encounter" and "start" in resource.get("period", {}):
                    week = dt.date.fromisoformat(resource["period"]["start"][:10]).isocalendar()
                    weeks.add((week.year, week.week))
                if resource["resourceType"] == "Condition":
                    codes.update(c["code"] for c in resource.get("code", {}).get("coding", []) if "code" in c)
            if weeks and codes:
                encounters[records["doc"]].update((week, code) for week in weeks for code in codes)
    full = {pid: {(*a, *e) for a in demographics[pid] for e in encounters[pid]}
            for pid in demographics.keys() & encounters.keys()}
    return {"age_band_and_district": summarize(demographics),
            "age_band_district_shifted_admission_week_and_diagnosis": summarize(full)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(measure(parser.parse_args().output), indent=2))
