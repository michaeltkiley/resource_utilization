"""
CI alerting step, not a data step: exits 1 if the latest CBO fetch found a
GDPC1/GDPPOT chain-dollar reference-year mismatch (see
00_fetch_cbo_gap.py). Deliberately meant to run *after* 01_build_dashboard.py
in a workflow -- publishing isn't gated on this, but a nonzero exit here
makes the workflow run itself report as failed, and GitHub emails the repo
owner on a failed scheduled-workflow run by default. That's the actual
monitoring mechanism for an unattended deploy: the dashboard keeps
publishing the (correctly labeled, uncorrected) series either way, but a
human gets a nudge to look rather than relying on someone remembering to
check the page.

Usage: python3 02_assert_cbo_alignment.py
"""
import glob
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    candidates = sorted(glob.glob(str(DATA_DIR / "*_cbo_gap_meta.json")))
    if not candidates:
        sys.exit("No CBO metadata found -- run 00_fetch_cbo_gap.py first")
    meta = json.loads(Path(candidates[-1]).read_text())

    if meta["reference_year_mismatch"]:
        sys.exit(
            f"CBO reference-year mismatch: GDPC1 is chained "
            f"{meta['gdpc1_reference_year']} dollars, GDPPOT is chained "
            f"{meta['gdppot_reference_year']} dollars. The dashboard has already "
            f"published with a visible warning banner -- this failure is just the "
            f"notification. See dashboard/README.md 'CBO reference-year check'."
        )
    print(f"OK: no CBO reference-year mismatch ({meta['gdpc1_reference_year']}).")


if __name__ == "__main__":
    main()
