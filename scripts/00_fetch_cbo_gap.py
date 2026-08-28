"""
Fetch CBO's output gap: real GDP (GDPC1) vs. CBO's real potential GDP
(GDPPOT), both from FRED. gap = 100*(GDPC1/GDPPOT - 1), CBO's own
percent-of-potential convention. Full history pulled every run (stateless,
matches the ingest pattern in the sibling dashboards).

Also checks a specific, mechanical failure mode: GDPC1 and GDPPOT are
each independently chain-weighted to a "reference year" (e.g. "Billions
of Chained 2017 Dollars"), stated on each series' own FRED page. If BEA
rebases GDPC1 to a new reference year before CBO re-benchmarks GDPPOT (or
vice versa), the ratio between them picks up a spurious, non-mean-
-reverting level shift that has nothing to do with the business cycle.
This is checked directly against each series' *own* published reference
year every run -- not inferred statistically -- and written to a sidecar
JSON the dashboard build reads. If it ever mismatches, the dashboard
shows a warning; deliberately no automatic numeric correction is applied
(see ../README.md "CBO reference-year check" for why).

Usage: python3 00_fetch_cbo_gap.py
"""
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
FRED_SERIES_PAGE_URL = "https://fred.stlouisfed.org/series/{series_id}"


def fetch_series(series_id: str) -> dict:
    resp = requests.get(FRED_CSV_URL.format(series_id=series_id), timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    next(reader)
    out = {}
    for row in reader:
        if len(row) != 2 or row[1] in (".", ""):
            continue
        out[row[0]] = float(row[1])
    return out


def fetch_chain_dollar_reference_year(series_id: str) -> int:
    """Reads the reference year straight off the series' own FRED page
    (e.g. "Billions of Chained 2017 Dollars" -> 2017). Raises if the
    expected units string isn't found, rather than guessing.
    """
    resp = requests.get(FRED_SERIES_PAGE_URL.format(series_id=series_id), timeout=30)
    resp.raise_for_status()
    m = re.search(r"Billions of Chained (\d{4}) Dollars", resp.text)
    if not m:
        raise ValueError(
            f"Couldn't find a 'Billions of Chained YYYY Dollars' units string on "
            f"the {series_id} FRED page -- units may have changed; check manually."
        )
    return int(m.group(1))


def main():
    gdpc1 = fetch_series("GDPC1")
    gdppot = fetch_series("GDPPOT")

    rows = []
    for d in sorted(gdpc1):
        if d not in gdppot:
            continue
        gap = 100 * (gdpc1[d] / gdppot[d] - 1)
        rows.append((d, round(gap, 6)))

    if not rows:
        sys.exit("No overlapping GDPC1/GDPPOT observations -- check FRED response")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{date.today():%Y%m%d}"

    out_path = DATA_DIR / f"{stamp}_cbo_gap.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "cbo_gap"])
        w.writerows(rows)
    print(f"Wrote {out_path} ({len(rows)} quarters, {rows[0][0]}..{rows[-1][0]})")

    gdpc1_year = fetch_chain_dollar_reference_year("GDPC1")
    gdppot_year = fetch_chain_dollar_reference_year("GDPPOT")
    mismatch = gdpc1_year != gdppot_year
    meta = {
        "gdpc1_reference_year": gdpc1_year,
        "gdppot_reference_year": gdppot_year,
        "reference_year_mismatch": mismatch,
    }
    meta_path = DATA_DIR / f"{stamp}_cbo_gap_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    if mismatch:
        print(
            f"WARNING: GDPC1 is chained {gdpc1_year} dollars but GDPPOT is chained "
            f"{gdppot_year} dollars -- CBO hasn't re-benchmarked to BEA's latest base "
            f"year yet. The gap below likely carries a spurious level shift, not a "
            f"real change in resource utilization. The dashboard will show a warning; "
            f"no automatic correction is applied (see dashboard/README.md).",
            file=sys.stderr,
        )
    else:
        print(f"OK: GDPC1 and GDPPOT both chained {gdpc1_year} dollars -- no base-year mismatch.")


if __name__ == "__main__":
    main()
