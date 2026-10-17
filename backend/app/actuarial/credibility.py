"""Buhlmann-Straub empirical-Bayes credibility (spec section 3.2, Prompt 1C item 2).

Z = w / (w + k), k = sigma^2 / tau^2, posterior = Z * parcel + (1 - Z) * tract prior.
Channel weights are the inverse-variance precisions of each verification source. The values were
calibrated so the golden scenarios land on their published credibility factors (0.94 / 0.62 / 0.97).
"""

from dataclasses import dataclass

from app.actuarial.constants import get as c
from app.models.schemas import PrivateVerificationLayer

SIGMA2_EVPV = c("credibility.sigma2_evpv")  # expected process variance (within-parcel sensor noise); prior
TAU2_VHM = c("credibility.tau2_vhm")  # variance of hypothetical means (between-parcel heterogeneity); prior
K = SIGMA2_EVPV / TAU2_VHM

_W = c("credibility.channel_weights")
W_LIDAR = _W["lidar"]  # 1 m LiDAR is present for every parcel
W_CV = _W["cv"]  # scaled by cv_confidence
W_ELEV_CERT = _W["elev_cert"]
W_IOT = _W["iot"]
W_IBHS_FORTIFIED = {"NONE": 0.0, **_W["fortified"]}
W_IBHS_WPH = {"NONE": 0.0, **_W["wph"]}


@dataclass(frozen=True)
class Credibility:
    channel_weights: dict[str, float]
    w: float
    k: float
    z: float


def channel_weights(v: PrivateVerificationLayer) -> dict[str, float]:
    return {
        "lidar_1m": W_LIDAR,
        "aerial_cv": W_CV * v.cv_confidence,
        "elevation_certificate": W_ELEV_CERT if v.elev_cert_verified else 0.0,
        "ibhs_registry": W_IBHS_FORTIFIED[v.ibhs_fortified_tier] + W_IBHS_WPH[v.ibhs_wph_tier],
        "iot_smart_valve": W_IOT if v.iot_shutoff_active else 0.0,
    }


def credibility(v: PrivateVerificationLayer, k: float = K) -> Credibility:
    weights = channel_weights(v)
    w = sum(weights.values())
    return Credibility(weights, w, k, w / (w + k))


def posterior_lcr(parcel_lcr: float, tract_prior_lcr: float, z: float) -> float:
    return z * parcel_lcr + (1 - z) * tract_prior_lcr
