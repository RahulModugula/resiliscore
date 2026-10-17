"""DOB records by BIN: open violations (BIS violations 3h2n-5cm9) and a cellar-conversion signal (DOB NOW w9ak-ipjd).

* `dob_open_violations`: BIS violations whose `violation_category` says ACTIVE.
* `dob_cellar_conversion_flag`: a DOB NOW filing for the BIN that works on the cellar/basement floor and proposes
  more dwelling units than exist. A flag means the permit record shows a conversion in progress or done. It is
  not proof of an illegal conversion, and no flag does not prove there is none.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ingestion.nyc.common import soda

VIOLATIONS = "3h2n-5cm9"
FILINGS = "w9ak-ipjd"


@dataclass(frozen=True)
class DobRecord:
    open_violations: int
    cellar_conversion: bool


def check_bin(bin_: str) -> str:
    if not (bin_.isdigit() and 6 <= len(bin_) <= 8):
        raise ValueError(f"BIN must be 6 to 8 digits: {bin_!r}")
    return bin_


def _units(v: object) -> int | None:
    try:
        return None if v in (None, "") else int(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def cellar_conversion(rows: list[dict]) -> bool:
    for r in rows:
        floor = (r.get("work_on_floor") or "").lower()
        existing, proposed = _units(r.get("existing_dwelling_units")), _units(r.get("proposed_dwelling_units"))
        on_cellar = "cellar" in floor or "basement" in floor
        if on_cellar and existing is not None and proposed is not None and proposed > existing:
            return True
    return False


async def fetch_dob(client: httpx.AsyncClient, bin_: str) -> DobRecord:
    bin_ = check_bin(bin_)
    violations = await soda(
        client, VIOLATIONS,
        **{"$select": "count(*) as n", "$where": f"bin='{bin_}' AND violation_category like '%ACTIVE%'"},
    )  # fmt: skip
    filings = await soda(
        client, FILINGS,
        **{
            "$select": "work_on_floor,existing_dwelling_units,proposed_dwelling_units",
            "$where": f"bin='{bin_}'",
            "$limit": 500,
        },
    )  # fmt: skip
    return DobRecord(int(violations[0]["n"]) if violations else 0, cellar_conversion(filings))
