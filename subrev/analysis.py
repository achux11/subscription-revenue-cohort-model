"""Cohort retention, churn curve, conversion, platform mix, cohort-based
revenue forecast, backtest and FX sensitivity."""
import numpy as np
import pandas as pd

from .data import ANNUAL_MULTIPLE, PRICE_UP_IDX, PRICE_UP_USD, months, monthly_revenue


# ---------- cohorts and churn ----------------------------------------------
def cohort_retention(subs, n, max_tenure=12):
    """Share of each monthly-plan paid cohort still active k months later."""
    mon = subs[subs.converted & ~subs.annual & (subs.paid_start <= n - 1)]
    out = {}
    for p, g in mon.groupby("paid_start"):
        row = {}
        for k in range(max_tenure + 1):
            if p + k <= n - 1:
                row[k] = float((g.end_idx > p + k).mean())
        out[str(months(n)[p])] = row
    return pd.DataFrame(out).T.sort_index()


def churn_curve(subs, n, max_tenure=None):
    """Monthly-plan churn hazard by paid tenure, using only observed months."""
    mon = subs[subs.converted & ~subs.annual & (subs.paid_start <= n - 1)]
    p, e = mon.paid_start.to_numpy(), mon.end_idx.to_numpy()
    rows = []
    for t in range(1, (max_tenure or n) + 1):
        eligible = (p + t <= n - 1)                 # month p+t is observed
        at_risk = eligible & (e > p + t - 1)
        churned = at_risk & (e == p + t)
        if at_risk.sum() == 0:
            break
        rows.append({"tenure": t, "at_risk": int(at_risk.sum()),
                     "churned": int(churned.sum()),
                     "churn_rate": churned.sum() / at_risk.sum()})
    return pd.DataFrame(rows)


def fit_hazard(curve):
    """Weighted log-log fit: churn(t) = a * t ** b."""
    c = curve[curve.churn_rate > 0]
    w = np.sqrt(c.at_risk.to_numpy())
    X = np.column_stack([np.ones(len(c)), np.log(c.tenure)])
    beta = np.linalg.lstsq(X * w[:, None], np.log(c.churn_rate) * w, rcond=None)[0]
    return float(np.exp(beta[0])), float(beta[1])


def annual_renewal_rate(subs, n, default=0.70):
    a = subs[subs.annual & (subs.paid_start + 12 <= n - 1)]
    return (float((a.end_idx > a.paid_start + 12).mean()), len(a)) if len(a) else (default, 0)


def conversion_by_platform(subs, n):
    done = subs[subs.signup_idx <= n - 2]            # trial finished inside window
    g = done.groupby("platform").agg(trials=("sub_id", "size"), paid=("converted", "sum"))
    g["conversion"] = g.paid / g.trials
    return g


def platform_mix(subs, fx, n):
    """Share of net revenue by platform in the first and last month."""
    paid = subs[subs.converted]
    res = {}
    for m in (n - 24, n - 1):                        # first and last month of the 2-year window
        act = paid[(paid.paid_start <= m) & (paid.end_idx > m)]
        rate = act.currency.map(fx.iloc[m]).to_numpy()
        recog = np.where(act.annual, act.monthly_price * ANNUAL_MULTIPLE / 12, act.monthly_price)
        net = recog * (1 - act.fee_rate.to_numpy()) * rate
        res[str(months(n)[m])] = pd.Series(net, index=act.platform.values).groupby(level=0).sum()
    df = pd.DataFrame(res)
    return df / df.sum()


# ---------- forecast ---------------------------------------------------------
def _signup_forecast(subs, fit_end, horizon):
    s = subs[subs.signup_idx <= fit_end].groupby("signup_idx").size()
    idx = s.index.to_numpy()
    last12 = idx[idx > fit_end - 12]
    nondec = last12[(last12 % 12) != 11]
    b, a = np.polyfit(nondec, np.log(s.loc[nondec]), 1)
    decs = idx[(idx % 12) == 11]
    dec_factor = float(np.mean([s.loc[d] / np.exp(a + b * d) for d in decs])) if len(decs) else 1.0
    fut = np.arange(fit_end + 1, fit_end + 1 + horizon)
    trend = np.exp(a + b * fut) * np.where((fut % 12) == 11, dec_factor, 1.0)
    return pd.Series(trend, index=fut), float(np.exp(b) - 1)


def _signup_params(subs, fit_end):
    """Trend value for month fit_end+1 (no seasonality), growth, December factor."""
    s = subs[subs.signup_idx <= fit_end].groupby("signup_idx").size()
    idx = s.index.to_numpy()
    last12 = idx[idx > fit_end - 12]
    nondec = last12[(last12 % 12) != 11]
    b, a = np.polyfit(nondec, np.log(s.loc[nondec]), 1)
    decs = idx[(idx % 12) == 11]
    dec_factor = float(np.mean([s.loc[d] / np.exp(a + b * d) for d in decs])) if len(decs) else 1.0
    return float(np.exp(a + b * (fit_end + 1))), float(np.exp(b) - 1), dec_factor


def forecast(subs, fx, fit_end, horizon):
    """Cohort-based forecast of active subscribers and net revenue (USD at the
    FX rates of month fit_end, i.e. constant currency).

    Uses only information available at the end of month fit_end."""
    n_obs = fit_end + 1
    obs = subs[subs.signup_idx <= fit_end].copy()
    obs["end_known"] = np.where(obs.end_idx <= fit_end, obs.end_idx, 10_000)

    cens = obs.assign(end_idx=obs.end_known)
    a, b = fit_hazard(churn_curve(cens, n_obs))
    haz = lambda t: np.clip(a * np.asarray(t, float) ** b, 0, 1)
    surv_cum = np.concatenate([[1.0], np.cumprod(1 - haz(np.arange(1, 400)))])  # S(k)

    renew, _ = annual_renewal_rate(cens, n_obs)
    trial_done = obs[(obs.signup_idx <= fit_end - 1) & (obs.signup_idx >= fit_end - 6)]
    conv = trial_done.converted.mean()
    ann_share = trial_done.annual.sum() / max(trial_done.converted.sum(), 1)
    signups, growth = _signup_forecast(obs, fit_end, horizon)
    # trial starts already observed in fit_end convert next month
    signups.loc[fit_end] = (obs.signup_idx == fit_end).sum()

    base = monthly_revenue(cens, fx, n=n_obs, constant_fx_idx=fit_end)
    last = base.iloc[-1]
    paid = cens[cens.converted & (cens.paid_start <= fit_end) & (cens.end_idx > fit_end)]
    rate = paid.currency.map(fx.iloc[fit_end]).to_numpy()
    price = paid.monthly_price.to_numpy() + np.where(
        (paid.region.to_numpy() == "US") & ~paid.annual.to_numpy() & (fit_end >= PRICE_UP_IDX),
        PRICE_UP_USD, 0.0)
    recog = np.where(paid.annual, price * ANNUAL_MULTIPLE / 12, price)
    net = recog * (1 - paid.fee_rate.to_numpy()) * rate
    arpu_m = net[~paid.annual.to_numpy()].mean()
    arpu_a = net[paid.annual.to_numpy()].mean()

    rows = []
    for M in range(fit_end + 1, fit_end + 1 + horizon):
        # existing monthly subs, active at fit_end in paid month tau = fit_end - p + 1
        pm = paid[~paid.annual]
        tau = (fit_end - pm.paid_start + 1).to_numpy()
        d = M - fit_end
        mon = float((surv_cum[tau - 1 + d] / surv_cum[tau - 1]).sum())
        pa = paid[paid.annual]
        crossed = ((M - pa.paid_start) // 12 - (fit_end - pa.paid_start) // 12).to_numpy()
        ann = float((renew ** crossed).sum())
        base_mon, base_ann = mon, ann
        # new cohorts: trial in month s -> paid from s+1
        for s_idx, k in signups.items():
            p = s_idx + 1
            if p <= M:
                newpaid = k * conv
                mon += newpaid * (1 - ann_share) * surv_cum[M - p]
                ann += newpaid * ann_share * renew ** ((M - p) // 12)
        rows.append({"month_idx": M, "month": str(months(1)[0] + M),
                     "existing_monthly": base_mon, "existing_annual": base_ann,
                     "fc_active_monthly": mon, "fc_active_annual": ann,
                     "fc_active_subs": mon + ann,
                     "fc_net_revenue_usd": mon * arpu_m + ann * arpu_a})
    sig_a, sig_g, dec_f = _signup_params(obs, fit_end)
    params = {"signups_trend_next": sig_a, "dec_factor": dec_f,
              "trials_in_fit_end": int((obs.signup_idx == fit_end).sum()),
              "fit_end": str(months(fit_end + 1)[fit_end]), "hazard_a": a, "hazard_b": b,
              "annual_renewal": renew, "trial_conversion": conv, "annual_share": ann_share,
              "signup_growth_mom": growth, "arpu_monthly_usd": arpu_m,
              "arpu_annual_usd": arpu_a, "active_at_fit_end": int(last.active_subs)}
    return pd.DataFrame(rows), params


def mape(actual, pred):
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.mean(np.abs(pred - actual) / actual))


def backtest(subs, fx, fit_end, horizon):
    fc, params = forecast(subs, fx, fit_end, horizon)
    act = monthly_revenue(subs, fx, n=fit_end + 1 + horizon, constant_fx_idx=fit_end)
    act = act[act.month_idx > fit_end].reset_index(drop=True)
    out = fc.merge(act[["month_idx", "active_subs", "net_revenue_usd"]], on="month_idx")
    # naive baseline: last month's revenue grown at the trailing 3-month average growth
    hist = monthly_revenue(subs, fx, n=fit_end + 1, constant_fx_idx=fit_end).net_revenue_usd
    g = float(hist.pct_change().iloc[-3:].mean())
    out["naive_net_revenue_usd"] = hist.iloc[-1] * (1 + g) ** np.arange(1, len(out) + 1)
    return out, {"revenue_mape": mape(out.net_revenue_usd, out.fc_net_revenue_usd),
                 "naive_revenue_mape": mape(out.net_revenue_usd, out.naive_net_revenue_usd),
                 "subs_mape": mape(out.active_subs, out.fc_active_subs), **params}


# ---------- FX ---------------------------------------------------------------
def fx_bridge(subs, fx, n):
    """FY2025 vs FY2024 revenue growth: reported vs constant currency."""
    rep = monthly_revenue(subs, fx, n=n)
    cc = monthly_revenue(subs, fx, n=n, constant_fx_idx=n - 24)   # Jan 2024 rates
    fy = lambda df, y: df[df.month.str.startswith(y)].net_revenue_usd.sum()
    r24, r25 = fy(rep, "2024"), fy(rep, "2025")
    c24, c25 = fy(cc, "2024"), fy(cc, "2025")
    return {"fy2024_reported": r24, "fy2025_reported": r25,
            "reported_growth": r25 / r24 - 1, "constant_ccy_growth": c25 / c24 - 1,
            "fx_drag_pts": (r25 / r24 - 1) - (c25 / c24 - 1)}


def currency_mix(subs, fx, m):
    paid = subs[subs.converted & (subs.paid_start <= m) & (subs.end_idx > m)]
    rate = paid.currency.map(fx.iloc[m]).to_numpy()
    price = paid.monthly_price.to_numpy() + np.where(
        (paid.region.to_numpy() == "US") & ~paid.annual.to_numpy() & (m >= PRICE_UP_IDX), PRICE_UP_USD, 0.0)
    recog = np.where(paid.annual, price * ANNUAL_MULTIPLE / 12, price)
    net = pd.Series(recog * (1 - paid.fee_rate.to_numpy()) * rate, index=paid.currency.values)
    s = net.groupby(level=0).sum()
    return s / s.sum()


def fx_scenarios(fc_total, ccy_mix, shocks=(-0.10, 0.0, 0.10)):
    """Reported revenue if every non-USD currency moves by `shock` vs USD."""
    non_usd = 1 - ccy_mix.get("USD", 0.0)
    return pd.DataFrame([{"scenario": f"Non-USD currencies {s:+.0%} vs USD",
                          "fy_revenue_usd": fc_total * (1 + s * non_usd),
                          "impact_usd": fc_total * s * non_usd} for s in shocks])
