"""
Unemployment-risk variants computed here rather than in
output_gap/unemployment_risk, from that project's own observables.csv:

  nocredit   The Full Model without credit-to-GDP growth (unemployment rate,
             inflation, corporate-bond spread, term spread). Logit
             probability and 80th-percentile quantile regression at both
             horizons -- the same estimation sample, threshold and COVID
             exclusion as the upstream full5 model, so the two differ only
             by the credit variable. Because it doesn't need the BIS
             credit/GDP series, it can be scored a few quarters later than
             the Full Model.

  quantiles  For the Full Model and the no-credit model, quantile
             regressions at the 10th/20th/50th/80th/90th percentiles,
             scored at each model's latest available quarter, plus the
             unconditional (sample) percentiles of the outcome. Each set of
             five percentiles is fitted with a Jones-Faddy skewed-t
             distribution (least squares on the quantiles), giving a
             density for the dashboard's distribution exhibits.

The upstream estimation rules (sample window, COVID exclusion, 80th-
percentile threshold) are mirrored from output_gap/unemployment_risk/
scripts/02_estimate.py; check_full5_matches() confirms the mirrored full5
80th-percentile fit reproduces the upstream magnitude series.
"""
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import optimize, stats

HORIZONS = {"h4": 4, "h12": 12}
COVID_EXCLUDE = {"2020Q1", "2020Q2", "2020Q3", "2020Q4"}
THRESHOLD_PCT = 80

FULL5_VARS = ["unrate", "infl4q", "credit_gr16q", "bond_spread", "term_spread"]
NOCREDIT_VARS = ["unrate", "infl4q", "bond_spread", "term_spread"]
MODELS = {"full5": FULL5_VARS, "nocredit": NOCREDIT_VARS}

PDF_QUANTILES = [0.10, 0.20, 0.50, 0.80, 0.90]
PDF_GRID_POINTS = 161


def load_observables(path) -> pd.DataFrame:
    return pd.read_csv(path).set_index("date")


def estimation_rows(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Same rows as upstream's current-analysis fit: all full5 predictors and
    the realized h-ahead outcome known, 2020 dropped from both t and t+h.
    Used for the no-credit model too, so it's estimated on an identical
    sample and differs from full5 only by the credit variable."""
    rows = df[FULL5_VARS + [f"du_{label}"]].dropna()
    t = pd.PeriodIndex(rows.index, freq="Q")
    keep = ~(t.astype(str).isin(COVID_EXCLUDE) | (t + HORIZONS[label]).astype(str).isin(COVID_EXCLUDE))
    return rows.loc[keep]


def fit_quantile(rows, label, predictors, q) -> pd.Series:
    formula = f"du_{label} ~ " + " + ".join(predictors)
    return smf.quantreg(formula, rows).fit(q=q).params


def score_linear(df, predictors, params) -> pd.Series:
    X = df[predictors].dropna()
    return params["Intercept"] + X.dot(params[predictors])


def fit_logit_scores(df, rows, label, predictors, thresh) -> pd.Series:
    y = (rows[f"du_{label}"] >= thresh).astype(int)
    res = sm.Logit(y, sm.add_constant(rows[predictors])).fit(disp=0)
    X = sm.add_constant(df[predictors].dropna(), has_constant="add")
    return res.predict(X)


def fit_skew_t(qs: list[float], values: list[float]) -> dict:
    """Least-squares fit of a Jones-Faddy skewed t to (probability, value)
    pairs. Values are sorted first: separately estimated quantile
    regressions can cross, and sorting (the Chernozhukov-Fernandez-Val-
    Galichon rearrangement) restores a valid set of quantiles."""
    v = np.sort(np.asarray(values, dtype=float))
    p = np.asarray(qs, dtype=float)
    spread = max(v[-1] - v[0], 1e-3)

    def unpack(theta):
        loc, log_scale, log_a, log_b = theta
        return loc, np.exp(log_scale), np.exp(np.clip(log_a, np.log(0.5), np.log(200))), \
            np.exp(np.clip(log_b, np.log(0.5), np.log(200)))

    def loss(theta):
        loc, scale, a, b = unpack(theta)
        fitted = stats.jf_skew_t.ppf(p, a, b, loc=loc, scale=scale)
        if not np.all(np.isfinite(fitted)):
            return 1e6
        return float(np.sum((fitted - v) ** 2)) / spread ** 2

    best = None
    for a0, b0 in [(5, 5), (3, 8), (8, 3), (2, 2)]:
        x0 = [v[2], np.log(spread / 2.5), np.log(a0), np.log(b0)]
        res = optimize.minimize(loss, x0, method="Nelder-Mead",
                                options={"xatol": 1e-6, "fatol": 1e-10, "maxiter": 4000})
        if best is None or res.fun < best.fun:
            best = res
    loc, scale, a, b = unpack(best.x)
    return {"loc": loc, "scale": scale, "a": a, "b": b, "rmse": float(np.sqrt(best.fun / len(p)) * spread)}


def skew_t_pdf(fit: dict, x: np.ndarray) -> np.ndarray:
    return stats.jf_skew_t.pdf(x, fit["a"], fit["b"], loc=fit["loc"], scale=fit["scale"])


def skew_t_ppf(fit: dict, p) -> np.ndarray:
    return stats.jf_skew_t.ppf(p, fit["a"], fit["b"], loc=fit["loc"], scale=fit["scale"])


def build(observables_path) -> dict:
    """Returns {"series": {date_label: {col: value}}, "pdfs": {...},
    "full5_q80": {label: Series}} -- series keyed by upstream's YYYYQN labels."""
    df = load_observables(observables_path)
    series = {}
    full5_q80 = {}
    pdfs = {}

    for label in HORIZONS:
        rows = estimation_rows(df, label)
        outcome = rows[f"du_{label}"]
        thresh = float(np.percentile(outcome, THRESHOLD_PCT))

        probs = fit_logit_scores(df, rows, label, NOCREDIT_VARS, thresh)
        q80_nocredit = score_linear(df, NOCREDIT_VARS, fit_quantile(rows, label, NOCREDIT_VARS, 0.80))
        full5_q80[label] = score_linear(df, FULL5_VARS, fit_quantile(rows, label, FULL5_VARS, 0.80))
        for d, v in probs.items():
            series.setdefault(d, {})[f"prob_nocredit_{label}"] = float(v)
        for d, v in q80_nocredit.items():
            series.setdefault(d, {})[f"magnitude_nocredit_{label}"] = float(v)

        uncond_vals = [float(np.percentile(outcome, q * 100)) for q in PDF_QUANTILES]
        uncond_fit = fit_skew_t(PDF_QUANTILES, uncond_vals)
        h_out = {
            "sample": [rows.index.min(), rows.index.max()],
            "n_obs": int(len(rows)),
            "unconditional": {"quantiles": uncond_vals, "fit": uncond_fit},
            "models": {},
        }
        for model, predictors in MODELS.items():
            X = df[predictors].dropna()
            latest = X.index[-1]
            vals = []
            for q in PDF_QUANTILES:
                params = fit_quantile(rows, label, predictors, q)
                vals.append(float(params["Intercept"] + X.loc[latest, predictors].dot(params[predictors])))
            fit = fit_skew_t(PDF_QUANTILES, vals)
            h_out["models"][model] = {"quarter": latest, "quantiles": vals, "fit": fit}

        # Plot range spans every set of estimated percentiles plus a margin,
        # rather than the fitted densities' own tails: the skewed t can put
        # a very long tail beyond the 90th percentile, which would squeeze
        # the region the estimates actually pin down.
        estimated = uncond_vals + [v for m in h_out["models"].values() for v in m["quantiles"]]
        lo, hi = min(estimated), max(estimated)
        pad = 0.6 * (hi - lo)
        grid = np.linspace(lo - pad, hi + pad, PDF_GRID_POINTS)
        h_out["x"] = grid.tolist()
        h_out["unconditional"]["pdf"] = skew_t_pdf(uncond_fit, grid).tolist()
        for model in MODELS:
            h_out["models"][model]["pdf"] = skew_t_pdf(h_out["models"][model]["fit"], grid).tolist()
        pdfs[label] = h_out

    return {"series": series, "pdfs": pdfs, "full5_q80": full5_q80}


def check_full5_matches(full5_q80: dict, upstream: dict, tol: float = 1e-3) -> list[str]:
    """Compare the mirrored full5 80th-percentile fit against upstream's
    magnitude series. upstream: {YYYYQN: {f"magnitude_full5_{label}": v}}.
    Returns a list of mismatch messages (empty if they agree)."""
    problems = []
    for label, s in full5_q80.items():
        col = f"magnitude_full5_{label}"
        diffs = [abs(v - upstream[d][col]) for d, v in s.items()
                 if d in upstream and upstream[d].get(col) is not None]
        if not diffs:
            problems.append(f"{col}: no overlapping quarters with upstream")
        elif max(diffs) > tol:
            problems.append(f"{col}: max abs difference {max(diffs):.4f} vs upstream")
    return problems
