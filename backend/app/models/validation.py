"""Validation report contract: how the model's outputs compare with observed loss data.

Served at GET /v1/model/validation and written to contracts/validation_report.json by
scripts/build_validation_report.py. `dr` means damage ratio, a fraction of replacement value in 0-1.
A section is None while its results are pending.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeverityBucket(_Strict):
    depth_bucket: str = Field(description="Label of the flood depth bucket, e.g. '1-2 ft'.")
    depth_mid_ft: float = Field(description="Bucket midpoint, feet above first finished floor.")
    n: int = Field(description="Number of observed claims in the bucket.")
    observed_mean_dr: float = Field(description="Observed mean damage ratio (dr, 0-1).")
    observed_ci_low: float = Field(description="Lower bound of the confidence interval on observed_mean_dr.")
    observed_ci_high: float = Field(description="Upper bound of the confidence interval on observed_mean_dr.")
    hazus_pred_dr: float = Field(description="Damage ratio predicted by the Hazus curve at depth_mid_ft.")
    fitted_pred_dr: float | None = Field(default=None, description="Damage ratio from the fitted curve, if any.")


class FloodEvent(_Strict):
    event: str = Field(description="Name of the flood event.")
    year: int = Field(description="Year of the event.")
    states: list[str] = Field(default_factory=list, description="US state codes the event covers.")
    n_claims: int = Field(description="Number of claims used for the event.")
    observed_mean_dr: float = Field(description="Observed mean damage ratio (dr, 0-1).")
    hazus_mae: float = Field(description="Mean absolute error of the Hazus prediction, in dr.")
    fitted_mae: float | None = Field(default=None, description="Mean absolute error of the fitted curve, in dr.")
    bias: float = Field(description="Mean signed error (predicted minus observed), in dr.")
    tract_spearman: float | None = Field(default=None, description="Spearman rank correlation across tracts.")
    n_tracts: int | None = Field(default=None, description="Number of tracts in the rank comparison.")
    note: str | None = Field(default=None, description="Free-text caveat for the event.")


class RankingDecile(_Strict):
    decile: int = Field(description="Decile of predicted risk, 1 to 10.")
    expected: float = Field(description="Mean predicted loss in the decile.")
    actual: float = Field(description="Mean observed loss in the decile.")


class Ranking(_Strict):
    n_tracts: int = Field(description="Number of tracts ranked.")
    spearman: float = Field(description="Spearman rank correlation of predicted versus observed loss.")
    gini: float = Field(description="Gini coefficient of the ranking.")
    deciles: list[RankingDecile] = Field(default_factory=list, description="Expected versus actual by decile.")


class FloodValidation(_Strict):
    method: str = Field(description="How the validation was done.")
    data_source: str = Field(description="Where the observed data came from.")
    data_vintage: str = Field(description="Vintage or release of the observed data.")
    fetched_on: date = Field(description="Date the data was fetched.")
    verdict: str = Field(description="Plain-language conclusion.")
    severity_by_depth: list[SeverityBucket] = Field(default_factory=list, description="Severity by depth bucket.")
    events: list[FloodEvent] = Field(default_factory=list, description="Per-event results.")
    ranking: Ranking | None = Field(default=None, description="Tract ranking result; None if not run.")
    adopted: bool = Field(description="True if a fitted result was adopted into the model.")
    adoption_note: str | None = Field(default=None, description="Why the fit was or was not adopted.")


class WildfireFire(_Strict):
    fire: str = Field(description="Name of the fire.")
    year: int = Field(description="Year of the fire.")
    n_structures: int = Field(description="Structures assessed.")
    destroyed_share: float = Field(description="Share of assessed structures destroyed (0-1).")
    auc_current: float = Field(description="ROC AUC of the current model.")
    auc_fitted: float | None = Field(default=None, description="ROC AUC of the fitted model, if any.")
    calibration_slope: float | None = Field(default=None, description="Calibration slope; 1.0 is ideal.")
    note: str | None = Field(default=None, description="Free-text caveat for the fire.")


class WildfireFeature(_Strict):
    feature: str = Field(description="Structure or site feature tested.")
    n: int = Field(description="Structures with the feature recorded.")
    odds_ratio: float = Field(description="Observed odds ratio of destruction.")
    ci_low: float = Field(description="Lower bound of the odds-ratio confidence interval.")
    ci_high: float = Field(description="Upper bound of the odds-ratio confidence interval.")
    model_implied_ratio: float | None = Field(default=None, description="Ratio the model implies for the feature.")
    supported: bool = Field(description="True if the data supports the model's direction and size.")


class WildfireValidation(_Strict):
    method: str = Field(description="How the validation was done.")
    data_source: str = Field(description="Where the observed data came from.")
    data_vintage: str = Field(description="Vintage or release of the observed data.")
    fetched_on: date = Field(description="Date the data was fetched.")
    verdict: str = Field(description="Plain-language conclusion.")
    fires: list[WildfireFire] = Field(default_factory=list, description="Per-fire results.")
    features: list[WildfireFeature] = Field(default_factory=list, description="Per-feature results.")
    pooled_auc: float | None = Field(default=None, description="ROC AUC pooled across fires.")
    adopted: bool = Field(description="True if a fitted result was adopted into the model.")
    adoption_note: str | None = Field(default=None, description="Why the fit was or was not adopted.")


class BenchmarkRow(_Strict):
    name: str = Field(description="Benchmark name.")
    n: int = Field(description="Number of requests measured.")
    concurrency: int | None = Field(default=None, description="Concurrent clients, if applicable.")
    p50_ms: float = Field(description="Median latency, ms.")
    p95_ms: float = Field(description="95th percentile latency, ms.")
    p99_ms: float = Field(description="99th percentile latency, ms.")
    rps: float | None = Field(default=None, description="Requests per second, if measured.")


class SourceRef(_Strict):
    name: str = Field(description="Source name.")
    url: str = Field(description="Source URL.")
    vintage: str = Field(description="Date or release the source was read.")


class ModelCard(_Strict):
    constants_total: int = Field(description="Entries in the constants registry.")
    constants_validated: int = Field(description="Entries taken from a primary or official source.")
    constants_calibration: int = Field(description="Entries solved by internal calibration to reference parcels.")
    perils: list[str] = Field(default_factory=list, description="Perils the model covers.")
    sources: list[SourceRef] = Field(default_factory=list, description="Distinct external sources used.")


class ValidationReport(_Strict):
    schema_version: Literal["1.0"] = Field(default="1.0", description="Contract version.")
    generated_at: datetime = Field(description="When the report was built.")
    model_commit: str = Field(description="Short git commit of the model the report describes.")
    status: Literal["COMPLETE", "PARTIAL", "PENDING"] = Field(
        description="COMPLETE when flood, wildfire and benchmarks are present, PENDING when none, else PARTIAL."
    )
    flood: FloodValidation | None = Field(default=None, description="Flood results; None while pending.")
    wildfire: WildfireValidation | None = Field(default=None, description="Wildfire results; None while pending.")
    benchmarks: list[BenchmarkRow] = Field(default_factory=list, description="Latency and throughput rows.")
    model_card: ModelCard = Field(description="Summary of the constants registry.")
