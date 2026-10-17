"""Build contracts/validation_report.json and contracts/validation_report_schema.json.

Merges optional section files from backend/validation/results/ (flood_summary.json,
wildfire_summary.json, benchmarks.json), each validated against its section model. A missing file
means a null section (or an empty benchmark list) and a PARTIAL or PENDING status.

Run from the repo root:  uv run --directory backend python scripts/build_validation_report.py
Idempotent: with unchanged inputs and commit the output is byte-identical (generated_at is kept).
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import TypeAdapter

from app.actuarial.constants import CAL, REGISTRY
from app.models.validation import (
    BenchmarkRow,
    FloodValidation,
    ModelCard,
    SourceRef,
    ValidationReport,
    WildfireValidation,
)

BACKEND = Path(__file__).resolve().parents[1]
RESULTS = BACKEND / "validation" / "results"
CONTRACTS = BACKEND.parent / "contracts"
REPORT_PATH = CONTRACTS / "validation_report.json"
SCHEMA_PATH = CONTRACTS / "validation_report_schema.json"
PERILS = ("flood", "wildfire", "wind")


def model_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def model_card() -> ModelCard:
    prefixes = {k.split(".", 1)[0] for k in REGISTRY}
    sources: dict[str, SourceRef] = {}
    for key, c in REGISTRY.items():
        if c.source_url.startswith("http") and c.source_url not in sources:
            sources[c.source_url] = SourceRef(name=key.split(".", 1)[0], url=c.source_url, vintage=c.source_date)
    return ModelCard(
        constants_total=len(REGISTRY),
        constants_validated=sum(1 for c in REGISTRY.values() if c.validated),
        constants_calibration=sum(1 for c in REGISTRY.values() if c.source_url == CAL),
        perils=[p for p in PERILS if p in prefixes],
        sources=sorted(sources.values(), key=lambda s: s.url),
    )


def load(name: str, adapter: TypeAdapter):
    path = RESULTS / name
    return adapter.validate_json(path.read_text()) if path.exists() else None


def build(generated_at: datetime) -> ValidationReport:
    flood = load("flood_summary.json", TypeAdapter(FloodValidation))
    wildfire = load("wildfire_summary.json", TypeAdapter(WildfireValidation))
    benchmarks = load("benchmarks.json", TypeAdapter(list[BenchmarkRow])) or []
    if flood and wildfire and benchmarks:
        status = "COMPLETE"
    elif flood or wildfire or benchmarks:
        status = "PARTIAL"
    else:
        status = "PENDING"
    return ValidationReport(
        generated_at=generated_at,
        model_commit=model_commit(),
        status=status,
        flood=flood,
        wildfire=wildfire,
        benchmarks=benchmarks,
        model_card=model_card(),
    )


def dump(report: ValidationReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def main() -> None:
    CONTRACTS.mkdir(exist_ok=True)
    report = build(datetime.now(UTC).replace(microsecond=0))
    if REPORT_PATH.exists():
        # Keep the previous timestamp when nothing else changed, so reruns are byte-identical.
        prev = ValidationReport.model_validate_json(REPORT_PATH.read_text())
        kept = report.model_copy(update={"generated_at": prev.generated_at})
        if dump(kept) == dump(prev):
            report = kept
    REPORT_PATH.write_text(dump(report))
    SCHEMA_PATH.write_text(json.dumps(ValidationReport.model_json_schema(), indent=2, sort_keys=True) + "\n")
    print(f"{report.status} {REPORT_PATH}")


if __name__ == "__main__":
    main()
