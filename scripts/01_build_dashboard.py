"""
Build the Resource Utilization dashboard (CBO output gap, EDO BN gap, EDO
PF gap, r* model UC gap) from the latest CBO fetch and the EDO/rstar
projects' current-analysis outputs. Self-contained static page (see
dashboard_template.html).

Usage:
    python3 01_build_dashboard.py [--cbo-file PATH] [--edo-file PATH] [--rstar-file PATH]
"""
import argparse
import csv
import glob
import io
import json
from datetime import date
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SCRIPT_DIR.parent
DATA_DIR = DASHBOARD_DIR / "data"
OUT_DIR = DASHBOARD_DIR / "output"
PAGES_OUT = DASHBOARD_DIR / "docs" / "index.html"
EDO_DEFAULT = DASHBOARD_DIR.parent / "edo" / "outputs" / "output_gap.csv"
RSTAR_DEFAULT = DASHBOARD_DIR.parent / "rstar" / "outputs" / "rstar.csv"
RISK_DEFAULT = DASHBOARD_DIR.parent / "unemployment_risk" / "outputs" / "unemployment_risk.csv"

RISK_COLUMNS = [
    "prob_full5_h4", "prob_fin2_h4", "magnitude_full5_h4",
    "prob_full5_h12", "prob_fin2_h12", "magnitude_full5_h12",
]

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def latest_cbo_file() -> Path:
    candidates = sorted(glob.glob(str(DATA_DIR / "*_cbo_gap.csv")))
    if not candidates:
        raise SystemExit("No CBO gap data found -- run 00_fetch_cbo_gap.py first")
    return Path(candidates[-1])


def latest_cbo_meta(cbo_path: Path) -> dict:
    meta_path = cbo_path.with_name(cbo_path.stem + "_meta.json")
    if not meta_path.exists():
        raise SystemExit(
            f"{meta_path} not found -- run 00_fetch_cbo_gap.py (current version writes "
            f"it alongside the data; re-fetch if this file predates that check)."
        )
    return json.loads(meta_path.read_text())


def read_cbo(path: Path) -> dict:
    with open(path) as f:
        return {row["date"]: float(row["cbo_gap"]) for row in csv.DictReader(f)}


def read_edo(path: Path):
    """EDO output uses YYYYQN date labels; convert to YYYY-MM-DD (quarter start)."""
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            y, q = row["date"][:4], row["date"][5]
            month = {"1": "01", "2": "04", "3": "07", "4": "10"}[q]
            out[f"{y}-{month}-01"] = (float(row["GAP"]), float(row["PFGAP"]))
    return out


def read_rstar(path: Path) -> dict:
    """rstar output uses YYYYQN date labels; convert to YYYY-MM-DD (quarter
    start). Uses the smoothed (two-sided) output gap, matching EDO's choice,
    plus its +-2 std dev uncertainty band (filtering/smoothing uncertainty
    conditional on the point-estimated parameters -- see rstar/README.md
    "Uncertainty").
    """
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            y, q = row["date"][:4], row["date"][5]
            month = {"1": "01", "2": "04", "3": "07", "4": "10"}[q]
            out[f"{y}-{month}-01"] = (
                float(row["output_gap_2side"]),
                float(row["output_gap_2side_lower"]),
                float(row["output_gap_2side_upper"]),
            )
    return out


def read_risk(path: Path) -> dict:
    """Unemployment-risk output uses YYYYQN date labels; convert to
    YYYY-MM-DD (quarter start). Values are floats or blank (missing --
    e.g. the full5 model needs BIS credit/GDP data, which lags a few
    quarters behind the other series; see unemployment_risk/README.md)."""
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            y, q = row["date"][:4], row["date"][5]
            month = {"1": "01", "2": "04", "3": "07", "4": "10"}[q]
            out[f"{y}-{month}-01"] = {
                col: (float(row[col]) if row[col] != "" else None)
                for col in RISK_COLUMNS
            }
    return out


def fetch_recessions() -> list[list[str]]:
    """NBER recession dates from FRED's USREC (monthly 0/1 indicator, 1 for
    each month NBER has dated as within a recession). Returns contiguous
    [start, end] date pairs (YYYY-MM-01) for chart shading -- pulled live
    rather than hardcoded so a newly NBER-dated recession shows up
    automatically on the next rebuild."""
    resp = requests.get(FRED_CSV_URL.format(series_id="USREC"), timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    next(reader)
    rows = [(r[0], r[1]) for r in reader if len(r) == 2 and r[1] not in (".", "")]

    bands = []
    start = None
    prev_d = None
    for d, v in rows:
        if v == "1" and start is None:
            start = d
        elif v != "1" and start is not None:
            bands.append([start, prev_d])
            start = None
        prev_d = d
    if start is not None:
        bands.append([start, prev_d])
    return bands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cbo-file", default=None, help="defaults to the latest data/*_cbo_gap.csv")
    ap.add_argument("--edo-file", default=str(EDO_DEFAULT))
    ap.add_argument("--rstar-file", default=str(RSTAR_DEFAULT))
    ap.add_argument("--risk-file", default=str(RISK_DEFAULT))
    args = ap.parse_args()

    cbo_path = Path(args.cbo_file) if args.cbo_file else latest_cbo_file()
    edo_path = Path(args.edo_file)
    if not edo_path.exists():
        raise SystemExit(f"{edo_path} not found -- run the EDO pipeline first (see output_gap/edo/README.md)")
    rstar_path = Path(args.rstar_file)
    if not rstar_path.exists():
        raise SystemExit(f"{rstar_path} not found -- run the rstar pipeline first (see output_gap/rstar/README.md)")
    risk_path = Path(args.risk_file)
    if not risk_path.exists():
        raise SystemExit(f"{risk_path} not found -- run the unemployment_risk pipeline first "
                          f"(see output_gap/unemployment_risk/README.md)")

    cbo = read_cbo(cbo_path)
    cbo_meta = latest_cbo_meta(cbo_path)
    edo = read_edo(edo_path)
    rstar = read_rstar(rstar_path)
    risk = read_risk(risk_path)

    dates = sorted(set(cbo) & set(edo) & set(rstar))
    if not dates:
        raise SystemExit("No overlapping dates across CBO, EDO, and rstar series")

    risk_dates = sorted(risk)
    risk_as_of = max(
        d for d in risk_dates if any(risk[d][c] is not None for c in RISK_COLUMNS)
    )

    recessions = fetch_recessions()

    payload = {
        "run_date": f"{date.today():%Y%m%d}",
        "as_of": dates[-1],
        "dates": dates,
        "cbo": [round(cbo[d], 4) for d in dates],
        "bn": [round(edo[d][0], 4) for d in dates],
        "pf": [round(edo[d][1], 4) for d in dates],
        "uc": [round(rstar[d][0], 4) for d in dates],
        "uc_lower": [round(rstar[d][1], 4) for d in dates],
        "uc_upper": [round(rstar[d][2], 4) for d in dates],
        "cbo_reference_year_mismatch": cbo_meta["reference_year_mismatch"],
        "cbo_gdpc1_reference_year": cbo_meta["gdpc1_reference_year"],
        "cbo_gdppot_reference_year": cbo_meta["gdppot_reference_year"],
        "recessions": recessions,
        "risk_dates": risk_dates,
        "risk_as_of": risk_as_of,
        **{
            f"risk_{col}": [
                (round(risk[d][col], 4) if risk[d][col] is not None else None)
                for d in risk_dates
            ]
            for col in RISK_COLUMNS
        },
    }

    template = (SCRIPT_DIR / "dashboard_template.html").read_text()
    if "__DATA_JSON__" not in template:
        raise ValueError("dashboard_template.html is missing the __DATA_JSON__ placeholder")
    html = template.replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{payload['run_date']}_dashboard.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} ({len(html)} bytes, {len(dates)} quarters, as of {payload['as_of']})")

    PAGES_OUT.parent.mkdir(parents=True, exist_ok=True)
    PAGES_OUT.write_text(html)
    print(f"Wrote {PAGES_OUT} (stable copy)")


if __name__ == "__main__":
    main()
