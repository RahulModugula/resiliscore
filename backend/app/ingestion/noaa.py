"""NOAA Atlas 14 point precipitation frequency: 24-hour, 100-year depth (inches).

Source: https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py (partial-duration series, English units),
live-checked 2026-10-17. Atlas 15 has no API (CONUS preliminary no earlier than Sept 2026), so this is
Atlas 14 and the contract's `atlas15_cmip6_mult` is a documented assumption, never a live value.
"""

from __future__ import annotations

import ast

import httpx

PFDS_URL = "https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py"
VINTAGE = "Atlas14"
ROW_24H = 9  # durations: 5,10,15,30,60 min, 2,3,6,12,24 hr, ...
COL_100YR = 6  # average recurrence intervals: 1,2,5,10,25,50,100,200,500,1000 yr


def parse_pfds(text: str) -> float:
    for line in text.splitlines():
        if line.startswith("quantiles"):
            table = ast.literal_eval(line.split("=", 1)[1].strip().rstrip(";"))
            return float(table[ROW_24H][COL_100YR])
    raise ValueError("PFDS response has no quantiles table")


async def fetch_p24h_100yr_in(client: httpx.AsyncClient, lat: float, lng: float) -> float:
    resp = await client.get(
        PFDS_URL,
        params={"lat": lat, "lon": lng, "type": "pf", "data": "depth", "units": "english", "series": "pds"},
    )
    resp.raise_for_status()
    return parse_pfds(resp.text)
