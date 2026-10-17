"""Validation report: builder statuses, schema sync, endpoint and strictness."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.validation import FloodValidation, ValidationReport

BACKEND = Path(__file__).resolve().parents[1]
CONTRACTS = BACKEND.parent / "contracts"

_spec = importlib.util.spec_from_file_location("build_validation_report", BACKEND / "scripts" / "build_validation_report.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

FLOOD = {
    "method": "Binned claims versus Hazus curve",
    "data_source": "OpenFEMA NFIP claims",
    "data_vintage": "v2",
    "fetched_on": "2026-10-17",
    "verdict": "Hazus over-predicts at shallow depth.",
    "severity_by_depth": [
        {
            "depth_bucket": "0-1 ft", "depth_mid_ft": 0.5, "n": 100, "observed_mean_dr": 0.1,
            "observed_ci_low": 0.08, "observed_ci_high": 0.12, "hazus_pred_dr": 0.2,
        }
    ],
    "adopted": False,
}


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "RESULTS", tmp_path)
    return tmp_path


def test_empty_results_is_pending(results):
    report = builder.build(datetime.now(UTC))
    assert report.status == "PENDING"
    assert report.flood is None and report.wildfire is None and report.benchmarks == []
    assert report.model_card.constants_total > 0


def test_flood_section_is_partial(results):
    (results / "flood_summary.json").write_text(json.dumps(FLOOD))
    report = builder.build(datetime.now(UTC))
    assert report.status == "PARTIAL"
    assert report.flood.severity_by_depth[0].fitted_pred_dr is None


def test_invalid_section_file_is_rejected(results):
    (results / "flood_summary.json").write_text(json.dumps({**FLOOD, "bogus": 1}))
    with pytest.raises(ValidationError):
        builder.build(datetime.now(UTC))


def test_schema_file_matches_model():
    on_disk = json.loads((CONTRACTS / "validation_report_schema.json").read_text())
    assert on_disk == ValidationReport.model_json_schema()


def test_endpoint_returns_valid_report():
    r = TestClient(app).get("/v1/model/validation")
    assert r.status_code == 200
    ValidationReport.model_validate(r.json())


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        FloodValidation.model_validate({**FLOOD, "extra_field": 1})
