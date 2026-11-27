"""Generate reproducible fictional hospital exports for the workbench and CLI tests."""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import io
import json
import random
from pathlib import Path


SCENARIOS = {
    "ward_transfer": ("Ward transfers", "Match admissions to follow-ups across reordered columns and separate two same-name patients."),
    "lab_exchange": ("Lab exchange", "Trace a callback to its registration and preserve lab values across encoded messages."),
    "rural_outreach": ("Rural outreach", "Link bilingual village visits and compare shifted timestamps across two exports."),
}
NAMES = (("Nila", "नीला"), ("Ravi", "रवि"), ("Tara", "तारा"), ("Kiran", "किरण"),
         ("Lata", "लता"), ("Anil", "अनिल"), ("Maya", "माया"), ("Vijay", "विजय"))
SURNAMES = (("Das", "दास"), ("Pal", "पाल"), ("Sen", "सेन"), ("Dev", "देव"))


def table(rows, delimiter, rng):
    columns = list(rows[0])
    rng.shuffle(columns)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, columns, delimiter=delimiter, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def generate(scenario, seed):
    rng = random.Random(seed)
    first, other = rng.sample(NAMES, 2)
    last = rng.choice(SURNAMES)
    given = [first, first, other]
    ids = rng.sample(range(100000, 999999), 3)
    phones = rng.sample(range(7000000000, 7999999999), 3)
    ages = rng.sample(range(24, 79), 3)
    start = dt.date(2024, 1, 1) + dt.timedelta(days=rng.randrange(720))
    stay = rng.randint(2, 11)
    stop = start + dt.timedelta(days=stay)
    chart = rng.choice(("Chart Number", "Patient Record ID", "UHID"))
    name = rng.choice(("Patient Legal Name", "Registrant Display Name", "Beneficiary Name"))
    age = rng.choice(("Age at visit", "Patient age (yrs)", "Umar"))
    names = [" ".join((word[0], last[0])) for word in given]
    villages = [f"Cedar Meadow {n}" for n in rng.sample(range(100, 999), 3)]
    rows = [{chart: f"WR-{ids[i]}", name: names[i], "Mobile": str(phones[i]),
             age: str(ages[i]), "Village": villages[i], "District": "Hill District",
             "DOB": f"{2024-ages[i]}-03-14", "Admitted at": start.isoformat(),
             "Discharged at": stop.isoformat(), "Diagnosis": "J06.9", "Dose": "2.5 mg"}
            for i in range(3)]
    delimiter = rng.choice((",", ";", "|"))
    files = {"register.csv": table(rows, delimiter, rng)}
    if scenario == "ward_transfer":
        opaque_phone = f"Field_{rng.randrange(10, 1000)}"
        follow = [{"Patient Name": names[i], opaque_phone: str(phones[i]),
                   "Visit date": stop.isoformat(), "Medication": "2.5 mg",
                   "Consultant": "Dr. Isha Kote"} for i in (1, 0)]
        files["transfers.tsv"] = table(follow, "\t", rng)
    elif scenario == "lab_exchange":
        mail = f"callback{ids[0]}@example.test"
        encoded = rng.choice((mail.encode().hex(), base64.b64encode(mail.encode()).decode(),
                              mail.replace("@", "%40"), mail.replace("@", "&#64;")))
        files["callback.txt"] = (f"Report for {first[0]} ji\nCall back {phones[0]}\n"
                                 f"Mailbox {encoded}\nHbA1c 6.4 % | Dose 2.5 mg\n")
        files["catalog.json"] = json.dumps({"test": "HbA1c", "value": 6.4, "unit": "%",
                                             "display": "HbA1c &amp; glucose"})
    elif scenario == "rural_outreach":
        local = given[2][1] + " " + last[1]
        files["roster.tsv"] = table([{"Patient Name": local, "Chart ID": rows[2][chart],
                                       "Village": villages[2], "Age": str(ages[2])}], "\t", rng)
        files["visits.json"] = json.dumps({"visits": [{"Patient Name": local,
            "Village": villages[2], "Age": str(ages[2]), "Landmark": f"Gate {ids[2]}",
            "device_clock": f"{stop}T09:42:10+05:45", "Rx": "2.5 mg"}]}, ensure_ascii=False)
    else:
        raise ValueError("Unknown scenario")
    return files


def write_dataset(folder, scenario, seed):
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Choose an empty dataset folder")
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in generate(scenario, seed).items():
        (folder / name).write_bytes(content.encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_dataset(args.output, args.scenario, args.seed)
