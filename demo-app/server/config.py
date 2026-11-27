"""Server-side configuration loader for the Secret Wards local application adapter.

Reads environment variables and an optional local .env file without external
dependencies. Never prints or returns RAKSHA_SECRET.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = APP_ROOT.parent


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not dotenv_path.is_file():
        return values
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def _resolve_path(raw: str, base: Path) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


@dataclass(frozen=True)
class Config:
    pipeline_path: Path
    policy_path: Path
    risk_script_path: Path
    demo_input_path: Path
    synthetic_input_path: Path
    chaos_input_path: Path
    output_dir: Path
    validation_doc_path: Path
    raksha_secret: str
    port: int
    allowed_origin: str

    @property
    def demo_configured(self) -> bool:
        return (
            self.pipeline_path.is_file()
            and self.demo_input_path.is_dir()
            and bool(self.raksha_secret)
        )


def load_config() -> Config:
    file_env = _load_dotenv(APP_ROOT / ".env")

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or file_env.get(key) or default

    default_pipeline = WORKSPACE_ROOT / "main.py"
    default_policy = WORKSPACE_ROOT / "config" / "policy.yaml"
    default_risk = WORKSPACE_ROOT / "qa" / "release_risk.py"
    default_demo = WORKSPACE_ROOT / "demo" / "input"
    default_synth = WORKSPACE_ROOT / "synthetic_case" / "input"
    default_chaos = WORKSPACE_ROOT / "datasets" / "unseen_chaos"

    pipeline_raw = os.environ.get("PIPELINE_PATH") or file_env.get("PIPELINE_PATH")
    policy_raw = os.environ.get("POLICY_PATH") or file_env.get("POLICY_PATH")
    risk_raw = os.environ.get("RISK_SCRIPT_PATH") or file_env.get("RISK_SCRIPT_PATH")
    demo_raw = os.environ.get("DEMO_INPUT_PATH") or file_env.get("DEMO_INPUT_PATH")

    pipeline_path = _resolve_path(pipeline_raw, APP_ROOT) if pipeline_raw else default_pipeline.resolve()
    policy_path = _resolve_path(policy_raw, APP_ROOT) if policy_raw else default_policy.resolve()
    risk_script_path = _resolve_path(risk_raw, APP_ROOT) if risk_raw else default_risk.resolve()
    demo_input_path = _resolve_path(demo_raw, APP_ROOT) if demo_raw else default_demo.resolve()
    output_dir = _resolve_path(get("OUTPUT_DIR", "./output"), APP_ROOT)
    validation_doc_path = (WORKSPACE_ROOT / "VALIDATION.md").resolve()

    port_str = get("PORT", "8081")
    try:
        port = int(port_str)
    except ValueError:
        port = 8081

    return Config(
        pipeline_path=pipeline_path,
        policy_path=policy_path,
        risk_script_path=risk_script_path,
        demo_input_path=demo_input_path,
        synthetic_input_path=default_synth.resolve(),
        chaos_input_path=default_chaos.resolve(),
        output_dir=output_dir,
        validation_doc_path=validation_doc_path,
        raksha_secret=get("RAKSHA_SECRET", "practice-synthetic-demo-only"),
        port=port,
        allowed_origin=get("ALLOWED_ORIGIN", f"http://127.0.0.1:{port}"),
    )
