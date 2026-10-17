#!/usr/bin/env python3
"""Bundle exact tax-lot addresses and measured NYC street centerlines. No geocoding."""
import datetime
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "public" / "manhattan" / "context"


def query(dataset, select, where):
    rows = []
    for offset in range(0, 200000, 10000):
        params = urllib.parse.urlencode({"$select": select, "$where": where, "$order": ":id", "$limit": 10000, "$offset": offset})
        url = f"https://data.cityofnewyork.us/resource/{dataset}.json?{params}"
        with urllib.request.urlopen(url, timeout=120) as response:
            batch = json.load(response)
        rows.extend(batch)
        if len(batch) < 10000:
            return rows
    raise RuntimeError("Unexpected source size; refusing truncated bundle")


def write(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text(json.dumps(value, separators=(",", ":")) + "\n")


def main():
    pluto = query("64uk-42ks", "bbl,address", "borough='MN' AND address IS NOT NULL")
    addresses = {str(int(float(row["bbl"]))): row["address"].strip() for row in pluto if row.get("address", "").strip()}
    write("addresses.json", addresses)
    streets = []
    for row in query("inkn-q76z", "physicalid,the_geom,full_street_name,streetwidth,segment_type", "boroughcode='1' AND status='2' AND from_level_code=13 AND to_level_code=13 AND rw_type NOT IN (3,4,12,14)"):
        for index, line in enumerate(row.get("the_geom", {}).get("coordinates", [])):
            if len(line) < 2:
                continue
            # CSCL streetwidth is feet, not the planimetric width of this rendered ribbon.
            width = float(row["streetwidth"]) * .3048 if row.get("streetwidth") else None
            streets.append({"id": f'{row["physicalid"]}:{index}', "name": row.get("full_street_name") or "Unnamed street", "coordinates": [[round(p[0], 7), round(p[1], 7)] for p in line], "widthM": round(width, 2) if width and width > 0 else None})
    write("streets.json", streets)
    write("sources.json", {"retrievedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "addresses": {"name": "NYC DCP PLUTO 26v2", "url": "https://data.cityofnewyork.us/d/64uk-42ks", "count": len(addresses)}, "streets": {"name": "NYC OTI Street Centerline", "url": "https://data.cityofnewyork.us/d/inkn-q76z", "count": len(streets)}, "limitations": ["Addresses join by exact BBL. A PLUTO address identifies a tax lot; several buildings on that lot can share the address. Missing addresses remain unknown.", "Only constructed at-grade segments are rendered; paper streets, bridges, tunnels, ferry routes and nonphysical links are excluded. Street ribbons use supplied streetwidth where present; otherwise a thin centerline. They are not surveyed curb boundaries.", "The focused view covers the selected building and its one-block vicinity, approximately 180 metres in each direction; it does not claim a cadastral block boundary."]})
    print(f"Bundled {len(addresses)} tax-lot addresses and {len(streets)} street segments")


if __name__ == "__main__":
    main()
