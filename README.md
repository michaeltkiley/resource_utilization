# resource_utilization — Resource Utilization and Risk Dashboard

Served at `michaeltkiley.github.io/resource_utilization/`, same shape as
`termprem` and `monetary_policy_surprises`. Reads its three model inputs
from `michaeltkiley/output_gap` rather than computing them itself -- see
that repo's README for the `edo`/`rstar`/`unemployment_risk` pipelines
and the `CROSS_REPO_TOKEN` deployment setup.

Two tabs:

- **Resource Utilization** — four output-gap estimates, side by side: the
  CBO's production-function gap, the Federal Reserve Board's EDO model's
  Beveridge-Nelson (BN) and production-function (PF) gaps, and the rstar
  project's Unobserved Components (UC) gap (with a &plusmn;2 std dev
  filtering-uncertainty band).
- **Recession and Unemployment Risk** — probability and implied magnitude
  of a large increase in the unemployment rate, at 1- and 3-year horizons,
  from `../unemployment_risk`'s full (5-variable) and financial-only
  (2-variable) models.

## Pipeline

```
scripts/00_fetch_cbo_gap.py            FRED: GDPC1 vs. GDPPOT -> CBO output gap
scripts/01_build_dashboard.py          reads the latest CBO fetch + output_gap's edo/outputs/output_gap.csv +
                                        rstar/outputs/rstar.csv + unemployment_risk/outputs/unemployment_risk.csv
                                        (each project's current-analysis default),
                                        builds docs/index.html from the template
scripts/02_assert_cbo_alignment.py     CI alerting step -- see "CBO reference-year check"
```

`00_fetch_cbo_gap.py` pulls FRED's full history every run — stateless,
same idempotent pattern as `termprem`/`monetary_policy_surprises`.
`01_build_dashboard.py` depends on the edo/rstar/unemployment_risk
pipelines in `output_gap` already having been run; it does not run any of
them itself -- see that repo's READMEs. In CI, `output_gap` is checked out
as a sibling directory (`output_gap/`) alongside this repo's own checkout
-- see `.github/workflows/update.yml`.

`data/` and `output/` are gitignored (regenerated on every run);
`docs/index.html` is the only generated file committed, matching the
sibling dashboards' convention (it's what GitHub Pages serves).

CI runs on `repository_dispatch` from any of `output_gap`'s three model
workflows, plus `workflow_dispatch` for a manual run. There's no cron here
-- this repo only rebuilds when an upstream model actually updates.

To run locally (assumes `output_gap` is checked out as a sibling
directory, i.e. `../output_gap`):

```
cd scripts
python3 00_fetch_cbo_gap.py
python3 01_build_dashboard.py \
  --edo-file ../../output_gap/edo/outputs/output_gap.csv \
  --rstar-file ../../output_gap/rstar/outputs/rstar.csv \
  --risk-file ../../output_gap/unemployment_risk/outputs/unemployment_risk.csv
```

## CBO reference-year check

CBO's potential GDP (`GDPPOT`) and BEA's real GDP (`GDPC1`) are each
independently chain-weighted to a "reference year" (e.g. "Billions of
Chained 2017 Dollars"). If BEA rebases `GDPC1` to a new reference year
before CBO re-benchmarks `GDPPOT`, the ratio between them picks up a
spurious, non-mean-reverting level shift that has nothing to do with the
business cycle.

`00_fetch_cbo_gap.py` checks this directly every run -- reading each
series' own published reference year off its FRED page and comparing
them -- and writes the result to a `data/*_cbo_gap_meta.json` sidecar. If
they ever mismatch, the dashboard shows a warning banner naming both
years. The CBO stat tile also always shows a trailing 5-year average, as
a transparent diagnostic (these gap concepts are defined around a zero
steady state, so a persistent non-zero average is itself a signal worth
noticing).

**Deliberately no automatic numeric correction is applied.** Detecting
*that* two series are chained to different reference years is a
mechanical, verifiable check; estimating *how much* of a given gap
reading to attribute to that vs. genuine economics is not something this
project attempts, because there's no way to build that correction
robustly -- it would depend on assumptions (how much of the base-year
revision the level shift explains, timing, etc.) that could easily be
wrong in a way that's not obviously wrong to look at. Showing the
misaligned series with a clear warning is preferred to a plausible-looking
but unverified correction.

**A page banner alone isn't much of a monitoring mechanism once this runs
unattended on a schedule** -- nobody's necessarily looking at the page the
day it flips. `02_assert_cbo_alignment.py` is the actual alert: run it
*after* `01_build_dashboard.py` in the CI workflow (once this has one).
It doesn't touch the published output -- the dashboard still publishes
normally, uncorrected series, banner and all -- it just exits 1 if the
latest fetch found a mismatch. A failing step later in a job still makes
the whole workflow run report as failed, and GitHub emails the repo owner
on a failed scheduled-workflow run by default. So the loop closes without
ever guessing at a correction: mechanical check -> visible warning on the
page -> CI failure -> email -> a human (you) decides what to do.
