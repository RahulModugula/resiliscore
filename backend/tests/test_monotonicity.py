"""Spec 3.4: every mitigation strictly improves the score, and no ECDIS variable exists."""

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.actuarial import compliance, constants
from app.actuarial import compound_model as cm
from app.actuarial.optimizer import _ctx
from app.models.schemas import ParcelScoreResponse

GOLDEN = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "golden_scenarios.json").read_text())


def test_reference_jacobian_is_strictly_positive_for_every_mitigation():
    jac = compliance.reference_jacobian()
    assert set(jac) == set(cm.MITIGATION_NAMES)
    assert all(g > 0 for g in jac.values()), jac
    assert compliance.monotonicity_verified({k: 0.0 for k in jac})


@pytest.mark.parametrize("key", GOLDEN)
def test_golden_parcels_are_never_harmed_by_a_mitigation(key):
    r = ParcelScoreResponse.model_validate(GOLDEN[key])
    jac = compliance.numerical_jacobian(
        r.public_hazard_layer, r.private_verification_layer, **_ctx(r),
        tract_prior_lcr=r.actuarial_breakdown.tract_prior_lcr, z=r.actuarial_breakdown.credibility_weight_z,
    )
    assert min(jac.values()) >= -1e-9, jac
    assert compliance.monotonicity_verified(jac)


def _set(monkeypatch, key: str, value) -> None:
    monkeypatch.setitem(constants.REGISTRY, key, replace(constants.REGISTRY[key], value=value))


def _flip_nyc(monkeypatch, name: str) -> None:
    """NYC retrofits act through registry coefficients (nyc.py): flip the ones behind `name`."""
    if name == "backwater_valve":
        _set(monkeypatch, "nyc.freq_reduction", {"backwater_valve": -0.85})
    elif name in ("sump_pump_battery", "elevated_mechanicals", "flood_vents"):
        reductions = dict(constants.get("nyc.sev_reduction"))
        reductions[name] = -reductions[name]
        _set(monkeypatch, "nyc.sev_reduction", reductions)
    elif name == "dry_floodproofing":
        _set(monkeypatch, "nyc.dry_floodproof_depth_ft", -constants.get("nyc.dry_floodproof_depth_ft"))
    else:  # cellar_reversal: a larger dose raises the finish multiplier instead of cutting it
        _set(monkeypatch, "nyc.cellar_reversal_multiplier", 2.0)


def _flip(monkeypatch, name: str) -> None:
    """Negate every coefficient through which mitigation `name` acts."""
    if name == "canopy_trim":
        monkeypatch.setattr(cm, "DELTA3_CANOPY", -cm.DELTA3_CANOPY)
        return
    if name in cm.NYC_DOSE_NAMES:
        _flip_nyc(monkeypatch, name)
        return
    flipped = {
        peril: {
            k: replace(e, **{f.name: -getattr(e, f.name) for f in fields(e)}) if k == name else e
            for k, e in table.items()
        }
        for peril, table in cm.EFFECTS.items()
    }
    monkeypatch.setattr(cm, "EFFECTS", flipped)


@pytest.mark.parametrize("name", cm.MITIGATION_NAMES)
def test_flipping_a_mitigation_sign_fails_the_check(monkeypatch, name):
    assert compliance.reference_jacobian()[name] > 0
    _flip(monkeypatch, name)
    jac = compliance.reference_jacobian()
    assert jac[name] < 0
    assert not compliance.monotonicity_verified(jac)


def test_no_ecdis_fields_in_the_contract():
    assert compliance.ecdis_fields_present() == []


def test_ecdis_scan_catches_a_socio_economic_field():
    class Bad(BaseModel):
        applicant_credit_score: int

    class Wrapper(BaseModel):
        inner: list[Bad]

    assert compliance.ecdis_fields_present(Wrapper) == ["applicant_credit_score"]
