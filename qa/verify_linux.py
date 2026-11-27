"""Run from Linux with an extracted official kit. Use unshare -Urn for offline testing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile

from release_risk import measure


def digest_tree(folder):
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(folder).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    args = parser.parse_args()
    kit = args.kit.resolve()
    if kit.is_file():
        with tempfile.TemporaryDirectory(prefix="wards-kit-") as work, ZipFile(kit) as archive:
            archive.extractall(work)
            verify(next(Path(work).rglob("validate_output.py")).parent)
    else:
        verify(kit)


def verify(kit):
    data = kit / "dev/input"
    root = Path(__file__).resolve().parents[1]
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])
    limit = 4 * 1024 ** 3
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    before = digest_tree(data)
    subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "qa", "-v"], cwd=root, check=True)
    with tempfile.TemporaryDirectory(prefix="wards-qa-") as temp:
        scratch = Path(temp)
        times = []
        outputs = []
        for tag in ("a", "b", "a", "a", "a"):
            out = scratch / str(len(outputs))
            secret = "release-check-" + tag
            start = time.monotonic()
            result = subprocess.run([sys.executable, "-B", str(root/"main.py"), "--input", str(data), "--output", str(out)],
                                    env={**os.environ, "RAKSHA_SECRET": secret}, capture_output=True, timeout=900, check=True)
            times.append(time.monotonic()-start)
            assert secret.encode() not in result.stdout + result.stderr
            assert all(secret.encode() not in f.read_bytes() for f in out.rglob("*") if f.is_file())
            outputs.append((digest_tree(out/"sanitized"), (out/"records.jsonl").read_bytes()))
        assert outputs[0] == outputs[2] == outputs[3] == outputs[4]
        assert all(x != y for x,y in zip(outputs[0], outputs[1]))
        assert before == digest_tree(data)
        subprocess.run([sys.executable, str(kit/"validate_output.py"), "--input", str(data), "--output", str(out)], cwd=kit, check=True)
        subprocess.run([sys.executable, str(kit/"check_dev.py"), "--output", str(out), "--show", "0"], cwd=kit, check=True)
        reports = [json.loads((scratch/str(i)/"report.json").read_bytes()) for i in range(len(outputs))]
        print("QA_SUMMARY", json.dumps({
            "python":sys.version.split()[0], "cpus":len(os.sched_getaffinity(0)),
            "network_interfaces":sorted(line.split(":", 1)[0].strip() for line in Path("/proc/net/dev").read_text().splitlines() if ":" in line),
            "median_seconds":round(statistics.median(times),3),
            "peak_rss_mb":max(r["resources"]["peak_rss_mb"] for r in reports),
            "counts":reports[0]["counts"], "risk":measure(out),
        }))


if __name__ == "__main__":
    main()
