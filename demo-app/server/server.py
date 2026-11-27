"""Localhost-only HTTP adapter for the Secret Wards offline privacy pipeline.

Standard library Python 3.10+ only. Binds strictly to 127.0.0.1, restricts CORS
to configured local origins, never exposes RAKSHA_SECRET, supports preset datasets,
custom file uploads, pasted text, structured record inputs, per-run privacy policy
configuration, and ephemeral secret rotation.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from config import APP_ROOT, Config, load_config
sys.path.insert(0, str(APP_ROOT.parent))
from main import decode as decode_input
sys.path.insert(0, str(APP_ROOT.parent / "qa"))
from case_factory import SCENARIOS, write_dataset

SAMPLE_SEEDS = {"ward_transfer": 21, "lab_exchange": 37, "rural_outreach": 89}
SCENARIO_TAGS = {"ward_transfer": ["CSV + TSV", "Homonyms"], "lab_exchange": ["Encoded text", "Lab controls"],
                 "rural_outreach": ["Hindi + English", "Time zones"]}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("secret-wards-adapter")

RUN_ID_RE = re.compile(r"^run-[0-9a-f]{12}$")
MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MiB max JSON upload payload
MAX_FILES_PER_RUN = 250

ALL_CATEGORIES = [
    "PHONE", "AADHAAR", "ABHA", "EMAIL", "PAN", "NAME", "MRN",
    "ENCOUNTER", "DOB", "ADDRESS", "RELATIVE", "INSURANCE_ID", "SOURCE_PATH",
]

RUN_LOCK = threading.Lock()
RUNS: dict[str, dict[str, Any]] = {}
# Ephemeral in-memory before-content keyed by run_id -> {sha256: {name, content}}
# Never written to output/ or exported in ZIPs.
BEFORE_STORE: dict[str, dict[str, dict[str, str]]] = {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def _load_default_policy(policy_path: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "age_band_years": 5,
        "age_band_max_years": 50,
        "age_k_anonymity": 2,
        "date_shift_max_days": 180,
        "shift_dates": True,
        "generalize_ages": True,
        "preserve_doctors": True,
        "hash_sensitive_filenames": True,
        "ml_fallback": True,
        "ml_ner_threshold": 0.85,
        "ml_col_threshold": 0.80,
        "redact_categories": list(ALL_CATEGORIES),
        "extra_redact_fields": [],
        "extra_preserve_fields": [],
        "extra_redact_terms": [],
        "extra_redact_regex": "",
    }
    if not policy_path.is_file():
        return defaults
    for line in policy_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k in ("age_band_years", "age_band_max_years", "age_k_anonymity", "date_shift_max_days"):
            if v.lstrip("-").isdigit():
                defaults[k] = int(v)
        elif k in ("shift_dates", "generalize_ages", "preserve_doctors", "hash_sensitive_filenames", "ml_fallback"):
            defaults[k] = v.lower() == "true"
        elif k in ("ml_ner_threshold", "ml_col_threshold"):
            try:
                defaults[k] = max(0.50, min(0.99, float(v)))
            except ValueError:
                pass
        elif k in ("redact_categories", "extra_redact_fields", "extra_preserve_fields", "extra_redact_terms"):
            items = [x.strip() for x in v.split(",") if x.strip()]
            if k == "redact_categories":
                if items:
                    defaults[k] = items
            else:
                defaults[k] = items
        elif k == "extra_redact_regex":
            defaults[k] = v
    return defaults


def _sanitize_policy(raw_policy: Any, defaults: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    policy = dict(defaults)
    if not isinstance(raw_policy, dict):
        return policy, None

    def clamp_int(key: str, lo: int, hi: int) -> None:
        if key in raw_policy and raw_policy[key] is not None:
            try:
                val = int(raw_policy[key])
            except (TypeError, ValueError):
                return
            policy[key] = max(lo, min(hi, val))

    clamp_int("age_band_years", 1, 50)
    clamp_int("age_band_max_years", policy["age_band_years"], 100)
    clamp_int("age_k_anonymity", 1, 50)
    clamp_int("date_shift_max_days", 1, 3650)

    for bkey in ("shift_dates", "generalize_ages", "preserve_doctors", "hash_sensitive_filenames", "ml_fallback"):
        if bkey in raw_policy and isinstance(raw_policy[bkey], bool):
            policy[bkey] = raw_policy[bkey]

    for fkey in ("ml_ner_threshold", "ml_col_threshold"):
        if fkey in raw_policy and raw_policy[fkey] is not None:
            try:
                policy[fkey] = round(max(0.50, min(0.99, float(raw_policy[fkey]))), 2)
            except (TypeError, ValueError):
                pass

    if "redact_categories" in raw_policy and isinstance(raw_policy["redact_categories"], list):
        cats = [str(c).strip().upper() for c in raw_policy["redact_categories"] if str(c).strip().upper() in ALL_CATEGORIES]
        policy["redact_categories"] = cats

    for lkey in ("extra_redact_fields", "extra_preserve_fields", "extra_redact_terms"):
        if lkey in raw_policy:
            val = raw_policy[lkey]
            if isinstance(val, list):
                policy[lkey] = [str(x).strip() for x in val if str(x).strip()][:100]
            elif isinstance(val, str):
                policy[lkey] = [x.strip() for x in val.split(",") if x.strip()][:100]

    if "extra_redact_regex" in raw_policy and isinstance(raw_policy["extra_redact_regex"], str):
        rx = raw_policy["extra_redact_regex"].strip()
        if len(rx) > 300:
            return policy, "Custom regex pattern is too long (max 300 characters)."
        if rx:
            try:
                re.compile(rx)
            except re.error as exc:
                return policy, f"Invalid custom regex pattern: {exc}"
        policy["extra_redact_regex"] = rx

    return policy, None


def _write_policy_yaml(policy: dict[str, Any], path: Path) -> None:
    lines = [
        f"age_band_years: {policy['age_band_years']}",
        f"age_band_max_years: {policy['age_band_max_years']}",
        f"age_k_anonymity: {policy['age_k_anonymity']}",
        f"date_shift_max_days: {policy['date_shift_max_days']}",
        f"shift_dates: {'true' if policy['shift_dates'] else 'false'}",
        f"generalize_ages: {'true' if policy['generalize_ages'] else 'false'}",
        f"preserve_doctors: {'true' if policy['preserve_doctors'] else 'false'}",
        f"hash_sensitive_filenames: {'true' if policy['hash_sensitive_filenames'] else 'false'}",
        f"ml_fallback: {'true' if policy['ml_fallback'] else 'false'}",
        f"ml_ner_threshold: {policy['ml_ner_threshold']}",
        f"ml_col_threshold: {policy['ml_col_threshold']}",
        f"redact_categories: {','.join(policy['redact_categories'])}",
        f"extra_redact_fields: {','.join(policy['extra_redact_fields'])}",
        f"extra_preserve_fields: {','.join(policy['extra_preserve_fields'])}",
        f"extra_redact_terms: {','.join(policy['extra_redact_terms'])}",
        f"extra_redact_regex: {policy['extra_redact_regex']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_rel_path(name: str) -> Path | None:
    cleaned = name.replace("\\", "/").strip().lstrip("/")
    if not cleaned or "\x00" in cleaned:
        return None
    parts = [p for p in cleaned.split("/") if p and p != "."]
    if not parts or any(p == ".." or ":" in p for p in parts):
        return None
    return Path(*parts)


def _preset_catalog(cfg: Config) -> list[dict[str, Any]]:
    return [
        {
            "id": "demo",
            "name": "Prescription Cross-Script Demo",
            "description": "English + Devanagari registration CSV & prescription note with homonym separation and 9-day stay preservation.",
            "path": cfg.demo_input_path,
            "highlights": ["2 files", "Hindi + English", "Homonym trap", "9-day stay"],
        },
        {
            "id": "synthetic_case",
            "name": "Multi-Hospital Synthetic Benchmark",
            "description": "Ward roster TSV, clinic follow-up CSV, handoff note, and 2 FHIR R4 Bundles with unseen column labels.",
            "path": cfg.synthetic_input_path,
            "highlights": ["5 files", "FHIR R4 Bundles", "Changed labels", "Adaptive age bands"],
        },
        {
            "id": "unseen_chaos",
            "name": "Unseen Multi-Script Chaos Pack",
            "description": "Brand-new dataset with Devanagari digits, masked Aadhaar, ABHA, Hinglish notes, base64 attachment, FHIR Bundle, and a raw PDF scan (triggers quarantine).",
            "path": cfg.chaos_input_path,
            "highlights": ["5 files", "Devanagari digits", "ABHA + Masked Aadhaar", "Live Quarantine (.pdf)"],
        },
        {
            "id": "ml_chaos_eval",
            "name": "Hybrid ML Bare Prose & Scrambled Headers",
            "description": "Held-out evaluation pack with bare unlabeled English/Hindi prose names & addresses plus scrambled CSV column headers — toggle Hybrid ML on/off to compare!",
            "path": APP_ROOT.parent / "datasets" / "ml_chaos_eval",
            "highlights": ["2 files", "Linear-Chain CRF", "Column Classifier", "Clinical Eponym Traps"],
        },
    ] + [{"id": key, "name": name, "description": desc, "path": APP_ROOT.parent / "datasets" / key,
          "highlights": SCENARIO_TAGS[key], "sample_seed": SAMPLE_SEEDS[key]}
         for key, (name, desc) in SCENARIOS.items()]


def _available_presets(cfg: Config) -> list[dict[str, Any]]:
    result = []
    for item in _preset_catalog(cfg):
        folder: Path = item["path"]
        if folder.is_dir():
            files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
            result.append({
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "file_count": len(files),
                "files": files,
                "highlights": item["highlights"],
                "sample_seed": item.get("sample_seed"),
            })
    return sorted(result, key=lambda item: item["sample_seed"] is None)


def _preset_dir(cfg: Config, preset_id: str) -> Path | None:
    p = next((item["path"] for item in _preset_catalog(cfg) if item["id"] == preset_id), None)
    return p if p and p.is_dir() else None


def _index_before_text(input_dir: Path) -> dict[str, dict[str, str]]:
    """Decode before-previews using the pipeline's encoding rules."""
    store: dict[str, dict[str, str]] = {}
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".txt", ".csv", ".tsv", ".json"}:
            continue
        try:
            raw = p.read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                continue
            sha = hashlib.sha256(raw).hexdigest()
            text = decode_input(raw)
            if text is None:
                continue
            store[sha] = {
                "name": p.relative_to(input_dir).as_posix(),
                "content": text,
            }
        except (OSError, UnicodeError):
            continue
    return store


def _execute_pipeline(
    run_id: str,
    cfg: Config,
    request_id: str,
    input_dir: Path,
    cleanup_dir: Path | None,
    policy: dict[str, Any],
    effective_secret: str,
) -> None:
    out_dir = (cfg.output_dir / run_id).resolve()
    policy_tmp: Path | None = None
    try:
        if not cfg.pipeline_path.is_file() or not input_dir.is_dir():
            with RUN_LOCK:
                RUNS[run_id].update(
                    status="failed",
                    finished_at=_now_iso(),
                    error_message="Pipeline script or input directory is unavailable.",
                    request_id=request_id,
                )
            return

        # Store in-memory before previews before cleaning up temp input
        before_map = _index_before_text(input_dir)
        with RUN_LOCK:
            BEFORE_STORE[run_id] = before_map
            # Keep memory bounded to last 20 runs
            if len(BEFORE_STORE) > 20:
                oldest = next(iter(BEFORE_STORE))
                if oldest != run_id:
                    BEFORE_STORE.pop(oldest, None)

        fd, tmp_pol = tempfile.mkstemp(prefix="sw-policy-", suffix=".yaml")
        os.close(fd)
        policy_tmp = Path(tmp_pol)
        _write_policy_yaml(policy, policy_tmp)

        env = {k: v for k, v in os.environ.items() if k != "RAKSHA_SECRET"}
        env["RAKSHA_SECRET"] = effective_secret

        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(cfg.pipeline_path),
                "--input",
                str(input_dir),
                "--output",
                str(out_dir),
                "--policy",
                str(policy_tmp),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            with RUN_LOCK:
                RUNS[run_id].update(
                    status="failed",
                    finished_at=_now_iso(),
                    error_message="The offline sanitization pipeline returned a non-zero exit code.",
                    request_id=request_id,
                )
            LOGGER.warning("request_id=%s run_id=%s status=failed exit_code=%d", request_id, run_id, proc.returncode)
            return

        report_path = out_dir / "report.json"
        records_path = out_dir / "records.jsonl"
        if not report_path.is_file():
            with RUN_LOCK:
                RUNS[run_id].update(
                    status="failed",
                    finished_at=_now_iso(),
                    error_message="Pipeline completed without producing report.json.",
                    request_id=request_id,
                )
            return

        report = _safe_read_json(report_path)
        records = _safe_read_jsonl(records_path)

        risk_summary: dict[str, Any] | None = None
        if cfg.risk_script_path.is_file():
            risk_proc = subprocess.run(
                [sys.executable, "-B", str(cfg.risk_script_path), "--output", str(out_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if risk_proc.returncode == 0 and risk_proc.stdout.strip():
                try:
                    risk_summary = json.loads(risk_proc.stdout)
                except json.JSONDecodeError:
                    risk_summary = None

        with RUN_LOCK:
            RUNS[run_id].update(
                status="completed",
                finished_at=_now_iso(),
                report=report,
                records=records,
                risk=risk_summary,
                error_message=None,
            )
        counts = report.get("counts", {})
        LOGGER.info(
            "request_id=%s run_id=%s status=completed files=%s sanitized=%s quarantined=%s",
            request_id,
            run_id,
            counts.get("files_total"),
            counts.get("files_sanitized"),
            counts.get("files_quarantined"),
        )
    except subprocess.TimeoutExpired:
        with RUN_LOCK:
            RUNS[run_id].update(
                status="failed",
                finished_at=_now_iso(),
                error_message="Sanitization timed out (120 s limit).",
                request_id=request_id,
            )
    except OSError:
        with RUN_LOCK:
            RUNS[run_id].update(
                status="failed",
                finished_at=_now_iso(),
                error_message="Local execution error while launching the sanitization process.",
                request_id=request_id,
            )
    finally:
        if policy_tmp and policy_tmp.exists():
            try:
                policy_tmp.unlink()
            except OSError:
                pass
        if cleanup_dir and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def _build_scorecard_payload(cfg: Config) -> dict[str, Any]:
    payload = {
        "label": "Practice data; not hidden competition results.",
        "v2_practice_benchmark": {
            "dataset": "Official 200-file practice dataset (dev/input)",
            "labeled_identifiers_visible": {"found": 0, "total": 3230},
            "planted_canaries_exposed": {"found": 0, "total": 4},
            "checked_medical_values_retained": {"kept": 4855, "total": 4855},
            "linkage": {"precision": 1.00, "recall": 0.96, "f05": 0.99},
            "residual_risk": {
                "age_band_and_district": {
                    "unique": 2,
                    "covered": 39,
                    "note": "Two covered pseudonyms have at least one unique age-band and district combination.",
                },
                "fhir_4_field_subset": {
                    "unique": 15,
                    "covered": 15,
                    "note": "15 of 15 in the smaller covered FHIR subset were unique on at least one combination after adding shifted admission week and diagnosis.",
                },
                "caveat": "This is a covered-subset uniqueness estimate, not an attacker success rate.",
            },
        },
        "v3_local_verification": {
            "available": cfg.validation_doc_path.is_file(),
            "age_band_and_district_v3": {"unique": 2, "covered": 39},
            "free_text_note_ages_generalized": {"kept": 85, "total": 85},
                "note": "Adaptive per-district age bands reduced age-band+district uniqueness on the covered practice subset to 2 of 39.",
        },
    }
    payload["practice_benchmark"] = payload["v2_practice_benchmark"]
    return payload


def make_handler(cfg: Config) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SecretWardsAdapter/2.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_cors_headers(self) -> None:
            origin = self.headers.get("Origin", "")
            allowed = {cfg.allowed_origin, f"http://127.0.0.1:{cfg.port}", "http://127.0.0.1:5173", "http://localhost:5173"}
            if origin in allowed:
                self.send_header("Access-Control-Allow-Origin", origin)
            else:
                self.send_header("Access-Control-Allow-Origin", cfg.allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")

        def _send_json(self, status_code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status_code: int, message: str, request_id: str | None = None) -> None:
            rid = request_id or uuid.uuid4().hex[:10]
            self._send_json(status_code, {"error": message, "request_id": rid})

        def _get_run(self, run_id: str) -> dict[str, Any] | None:
            if not RUN_ID_RE.fullmatch(run_id):
                return None
            with RUN_LOCK:
                run = RUNS.get(run_id)
                if run is not None:
                    return dict(run)
            out_dir = (cfg.output_dir / run_id).resolve()
            if out_dir.is_dir() and (out_dir / "report.json").is_file():
                try:
                    report = _safe_read_json(out_dir / "report.json")
                    records = _safe_read_jsonl(out_dir / "records.jsonl")
                    return {
                        "run_id": run_id,
                        "source": "Saved run",
                        "label": run_id,
                        "status": "completed",
                        "started_at": None,
                        "finished_at": None,
                        "report": report,
                        "records": records,
                        "risk": None,
                        "policy_used": None,
                        "secret_mode": "default",
                        "error_message": None,
                    }
                except (OSError, json.JSONDecodeError):
                    return None
            return None

        def _serialize_run(self, run: dict[str, Any]) -> dict[str, Any]:
            report = run.get("report") or {}
            resources = report.get("resources") or {}
            raw_rss = resources.get("peak_rss_mb")
            peak_rss_mb = raw_rss if isinstance(raw_rss, (int, float)) and raw_rss > 0 else None
            return {
                "run_id": run["run_id"],
                "source": run.get("source") or "Custom input",
                "label": run.get("label") or run["run_id"],
                "status": run["status"],
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "counts": report.get("counts"),
                "entities": report.get("entities") or {},
                "timing": report.get("timing"),
                "resources": {"peak_rss_mb": peak_rss_mb},
                "records": run.get("records") if run["status"] == "completed" else [],
                "risk": run.get("risk"),
                "policy_used": run.get("policy_used"),
                "secret_mode": run.get("secret_mode", "default"),
                "error_message": run.get("error_message"),
                "request_id": run.get("request_id"),
            }

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            request_id = uuid.uuid4().hex[:10]

            if path == "/api/health":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "demo_configured": cfg.demo_configured,
                        "pipeline_available": cfg.pipeline_path.is_file(),
                        "demo_input_available": cfg.demo_input_path.is_dir(),
                        "supports_custom_input": True,
                        "supports_policy_config": True,
                        "presets": _available_presets(cfg),
                        "default_policy": _load_default_policy(cfg.policy_path),
                    },
                )
                return

            if path == "/api/presets":
                self._send_json(200, {"presets": _available_presets(cfg)})
                return

            if path == "/api/policy/defaults":
                self._send_json(
                    200,
                    {
                        "defaults": _load_default_policy(cfg.policy_path),
                        "all_categories": ALL_CATEGORIES,
                    },
                )
                return

            if path == "/api/scorecard":
                self._send_json(200, _build_scorecard_payload(cfg))
                return

            if path == "/api/demo-inputs":
                self._serve_preset_inputs("demo", request_id)
                return

            parts = [p for p in path.split("/") if p]

            # GET /api/presets/{id}/inputs
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "presets" and parts[3] == "inputs":
                self._serve_preset_inputs(parts[2], request_id)
                return

            # GET /api/runs (history list)
            if path == "/api/runs":
                with RUN_LOCK:
                    items = [
                        {
                            "run_id": r["run_id"],
                            "source": r.get("source"),
                            "label": r.get("label"),
                            "status": r["status"],
                            "started_at": r.get("started_at"),
                            "finished_at": r.get("finished_at"),
                            "secret_mode": r.get("secret_mode", "default"),
                            "counts": (r.get("report") or {}).get("counts"),
                        }
                        for r in reversed(list(RUNS.values()))
                    ]
                self._send_json(200, {"runs": items[:30]})
                return

            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "runs":
                run_id = parts[2]
                run = self._get_run(run_id)
                if run is None:
                    self._send_error_json(404, "Run not found.", request_id)
                    return

                # GET /api/runs/{run_id}
                if len(parts) == 3:
                    self._send_json(200, self._serialize_run(run))
                    return

                # GET /api/runs/{run_id}/files
                if len(parts) == 4 and parts[3] == "files":
                    if run["status"] != "completed":
                        self._send_json(200, {"run_id": run_id, "files": []})
                        return
                    report = run.get("report") or {}
                    with RUN_LOCK:
                        before_map = BEFORE_STORE.get(run_id, {})
                    safe_files = []
                    for f in report.get("files", []):
                        sha = f.get("input_sha256")
                        item: dict[str, Any] = {
                            "input_sha256": sha,
                            "output": f.get("output"),
                            "status": f.get("status"),
                            "has_before": bool(sha and sha in before_map),
                        }
                        if f.get("reason"):
                            item["reason"] = f.get("reason")
                        safe_files.append(item)
                    self._send_json(200, {"run_id": run_id, "files": safe_files})
                    return

                # GET /api/runs/{run_id}/before?sha256=...
                if len(parts) == 4 and parts[3] == "before":
                    query = urllib.parse.parse_qs(parsed.query)
                    sha = (query.get("sha256") or [""])[0].strip()
                    with RUN_LOCK:
                        entry = BEFORE_STORE.get(run_id, {}).get(sha)
                    if not entry:
                        self._send_error_json(404, "Original input preview is not available for this file.", request_id)
                        return
                    self._send_json(200, {"sha256": sha, "name": entry["name"], "content": entry["content"]})
                    return

                # GET /api/runs/{run_id}/file?path=...(&download=1)
                if len(parts) == 4 and parts[3] == "file":
                    if run["status"] != "completed":
                        self._send_error_json(409, "Run has not completed yet.", request_id)
                        return
                    query = urllib.parse.parse_qs(parsed.query)
                    rel_raw = (query.get("path") or [""])[0].strip()
                    download_flag = (query.get("download") or ["0"])[0] == "1"
                    if not rel_raw:
                        self._send_error_json(400, "Missing file path parameter.", request_id)
                        return
                    sanitized_root = (cfg.output_dir / run_id / "sanitized").resolve()
                    rel_clean = rel_raw.replace("\\", "/").lstrip("/")
                    if rel_clean.startswith("sanitized/"):
                        rel_clean = rel_clean[len("sanitized/"):]
                    target = (sanitized_root / rel_clean).resolve()
                    try:
                        target.relative_to(sanitized_root)
                    except ValueError:
                        self._send_error_json(403, "Invalid sanitized file path.", request_id)
                        return
                    if not target.is_file() or target.suffix.lower() not in {".txt", ".csv", ".tsv", ".json"}:
                        self._send_error_json(404, "Sanitized file not found.", request_id)
                        return
                    raw_bytes = target.read_bytes()
                    if download_flag:
                        self.send_response(200)
                        self._send_cors_headers()
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header(
                            "Content-Disposition",
                            f'attachment; filename="{target.name}"',
                        )
                        self.send_header("Content-Length", str(len(raw_bytes)))
                        self.end_headers()
                        self.wfile.write(raw_bytes)
                        return
                    self._send_json(
                        200,
                        {
                            "path": f"sanitized/{target.relative_to(sanitized_root).as_posix()}",
                            "content": raw_bytes.decode("utf-8"),
                        },
                    )
                    return

                # GET /api/runs/{run_id}/export
                if len(parts) == 4 and parts[3] == "export":
                    if run["status"] != "completed":
                        self._send_error_json(409, "Run is not ready for export.", request_id)
                        return
                    out_dir = (cfg.output_dir / run_id).resolve()
                    sanitized_root = out_dir / "sanitized"
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for meta_name in ("report.json", "records.jsonl"):
                            meta_path = out_dir / meta_name
                            if meta_path.is_file():
                                zf.write(meta_path, arcname=meta_name)
                        if sanitized_root.is_dir():
                            for item in sorted(sanitized_root.rglob("*")):
                                if item.is_file():
                                    arcname = f"sanitized/{item.relative_to(sanitized_root).as_posix()}"
                                    zf.write(item, arcname=arcname)
                    zip_bytes = buf.getvalue()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/zip")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="secret-wards-{run_id}-sanitized.zip"',
                    )
                    self.send_header("Content-Length", str(len(zip_bytes)))
                    self.end_headers()
                    self.wfile.write(zip_bytes)
                    return

            # Static file fallback: serve built React app from dist/
            dist_root = (APP_ROOT / "dist").resolve()
            if dist_root.is_dir():
                rel = path.lstrip("/") or "index.html"
                static_path = (dist_root / rel).resolve()
                try:
                    static_path.relative_to(dist_root)
                except ValueError:
                    self._send_error_json(403, "Forbidden.", request_id)
                    return
                if not static_path.is_file():
                    static_path = dist_root / "index.html"
                if static_path.is_file():
                    _MIME = {
                        ".html": "text/html; charset=utf-8",
                        ".js": "application/javascript; charset=utf-8",
                        ".css": "text/css; charset=utf-8",
                        ".svg": "image/svg+xml",
                        ".ico": "image/x-icon",
                        ".png": "image/png",
                        ".woff2": "font/woff2",
                        ".woff": "font/woff",
                        ".json": "application/json; charset=utf-8",
                    }
                    content_type = _MIME.get(static_path.suffix.lower(), "application/octet-stream")
                    data = static_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    if static_path.suffix.lower() != ".html":
                        self.send_header("Cache-Control", "public, max-age=3600")
                    else:
                        self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(data)
                    return

            self._send_error_json(404, "Endpoint not found.", request_id)

        def _serve_preset_inputs(self, preset_id: str, request_id: str) -> None:
            folder = _preset_dir(cfg, preset_id)
            if folder is None:
                self._send_error_json(404, f"Preset '{preset_id}' not found.", request_id)
                return
            items: list[dict[str, str]] = []
            for entry in sorted(folder.rglob("*")):
                if entry.is_file() and entry.suffix.lower() in {".txt", ".csv", ".tsv", ".json"}:
                    items.append({
                        "name": entry.relative_to(folder).as_posix(),
                        "label": f"Preset: {preset_id}",
                        "content": entry.read_text(encoding="utf-8", errors="replace"),
                    })
            self._send_json(200, {"source": preset_id, "label": f"Preset: {preset_id}", "files": items})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            request_id = uuid.uuid4().hex[:10]
            if parsed.path != "/api/runs":
                self._send_error_json(404, "Endpoint not found.", request_id)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_error_json(400, "Invalid Content-Length header.", request_id)
                return

            if length <= 0 or length > MAX_BODY_BYTES:
                self._send_error_json(400, "Request body is empty or exceeds 25 MiB limit.", request_id)
                return

            raw_body = self.rfile.read(length)
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error_json(400, "Malformed JSON payload.", request_id)
                return

            if not isinstance(payload, dict):
                self._send_error_json(400, "JSON payload must be an object.", request_id)
                return

            if not cfg.pipeline_path.is_file():
                self._send_error_json(503, "Offline sanitization pipeline is not configured.", request_id)
                return

            defaults = _load_default_policy(cfg.policy_path)
            policy, policy_err = _sanitize_policy(payload.get("policy"), defaults)
            if policy_err:
                self._send_error_json(400, policy_err, request_id)
                return

            # Secret handling: never logged, never returned
            secret_mode = str(payload.get("secret_mode") or "default").strip().lower()
            if secret_mode == "rotate":
                effective_secret = secrets.token_hex(32)
            elif secret_mode == "custom":
                custom_secret = str(payload.get("custom_secret") or "").strip()
                if len(custom_secret) < 4:
                    self._send_error_json(400, "Custom test key must be at least 4 characters.", request_id)
                    return
                effective_secret = custom_secret
            else:
                secret_mode = "default"
                effective_secret = cfg.raksha_secret

            source = str(payload.get("source") or "demo").strip().lower()
            cleanup_dir: Path | None = None
            input_dir: Path
            source_display: str
            label = str(payload.get("label") or "").strip()[:80]

            if source in ("demo", "preset"):
                preset_id = "demo" if source == "demo" else str(payload.get("preset_id") or "demo").strip()
                found = _preset_dir(cfg, preset_id)
                if found is None:
                    self._send_error_json(400, f"Unknown preset dataset '{preset_id}'.", request_id)
                    return
                input_dir = found
                source_display = f"Preset dataset ({preset_id})"
                label = label or preset_id
                if "seed" in payload:
                    seed = payload["seed"]
                    if preset_id not in SCENARIOS or type(seed) is not int or not 0 <= seed <= 2147483647:
                        self._send_error_json(400, "Choose a seeded dataset and an integer seed from 0 to 2147483647.", request_id)
                        return
                    cleanup_dir = Path(tempfile.mkdtemp(prefix="sw-scenario-"))
                    try:
                        write_dataset(cleanup_dir, preset_id, seed)
                    except (ValueError, OSError):
                        shutil.rmtree(cleanup_dir, ignore_errors=True)
                        self._send_error_json(500, "Could not prepare synthetic dataset.", request_id)
                        return
                    input_dir = cleanup_dir
                    source_display = f"{SCENARIOS[preset_id][0]} · seed {seed}"
                    label = str(payload.get("label") or source_display)[:80]
            elif source == "custom":
                raw_files = payload.get("files")
                if not isinstance(raw_files, list) or not raw_files:
                    self._send_error_json(400, "Custom run requires at least one file in 'files'.", request_id)
                    return
                if len(raw_files) > MAX_FILES_PER_RUN:
                    self._send_error_json(400, f"Maximum {MAX_FILES_PER_RUN} files per run.", request_id)
                    return
                tmp_dir = Path(tempfile.mkdtemp(prefix="sw-in-"))
                cleanup_dir = tmp_dir
                written = 0
                try:
                    for fobj in raw_files:
                        if not isinstance(fobj, dict):
                            continue
                        rel = _safe_rel_path(str(fobj.get("name") or ""))
                        if rel is None:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            self._send_error_json(400, "Invalid filename in upload.", request_id)
                            return
                        enc = str(fobj.get("encoding") or "utf-8").lower()
                        content = fobj.get("content", "")
                        if enc == "base64":
                            try:
                                raw_bytes = base64.b64decode(str(content), validate=True)
                            except ValueError:
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                                self._send_error_json(400, f"Invalid base64 payload for {rel.name}.", request_id)
                                return
                        else:
                            raw_bytes = str(content).encode("utf-8")
                        dest = (tmp_dir / rel).resolve()
                        try:
                            dest.relative_to(tmp_dir.resolve())
                        except ValueError:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                            self._send_error_json(400, "Path traversal rejected.", request_id)
                            return
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with dest.open("xb") as staged:
                            staged.write(raw_bytes)
                        written += 1
                except (FileExistsError, NotADirectoryError, IsADirectoryError):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    self._send_error_json(400, "Two uploaded paths conflict. Select distinct file paths.", request_id)
                    return
                except OSError:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    self._send_error_json(500, "Failed to stage input files.", request_id)
                    return
                if written == 0:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    self._send_error_json(400, "No valid files were provided.", request_id)
                    return
                input_dir = tmp_dir
                source_display = f"Custom input ({written} {'file' if written == 1 else 'files'})"
                label = label or f"custom ({written} files)"
            else:
                self._send_error_json(400, "Unsupported source. Use 'demo', 'preset', or 'custom'.", request_id)
                return

            cfg.output_dir.mkdir(parents=True, exist_ok=True)
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            with RUN_LOCK:
                RUNS[run_id] = {
                    "run_id": run_id,
                    "source": source_display,
                    "label": label,
                    "status": "running",
                    "started_at": _now_iso(),
                    "finished_at": None,
                    "report": None,
                    "records": [],
                    "risk": None,
                    "policy_used": policy,
                    "secret_mode": secret_mode,
                    "error_message": None,
                    "request_id": request_id,
                }

            LOGGER.info("request_id=%s run_id=%s source=%s status=running", request_id, run_id, source)
            worker = threading.Thread(
                target=_execute_pipeline,
                args=(run_id, cfg, request_id, input_dir, cleanup_dir, policy, effective_secret),
                daemon=True,
            )
            worker.start()

            self._send_json(202, {"run_id": run_id, "status": "running"})

    return Handler


def main() -> None:
    cfg = load_config()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    dist_root = (APP_ROOT / "dist").resolve()
    if dist_root.is_dir():
        LOGGER.info("Serving React app from dist/ — open http://127.0.0.1:%d in your browser", cfg.port)
    else:
        LOGGER.info("No dist/ found — run 'npm run build' in demo-app/ first, or use 'npm run dev' (port 5173)")

    server = ThreadingHTTPServer(("127.0.0.1", cfg.port), make_handler(cfg))
    LOGGER.info("Secret Wards local adapter listening on http://127.0.0.1:%d", cfg.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down local adapter")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
