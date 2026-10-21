"""Simulated consumer-subscription business: signups, free trials, monthly and
annual plans, churn, multiple currencies and platforms.

Every assumption is a named constant below so a reviewer can see (and change)
exactly what drives the numbers. Nothing here is real company data.
"""
import numpy as np
import pandas as pd

START = "2022-01"          # first signup month (launch)
N_MONTHS = 48              # Jan 2022 .. Dec 2025 of history
BASE_SIGNUPS = 4000        # trial starts in month 0
SIGNUP_GROWTH = 0.015      # month-over-month growth in trial starts (~20%/yr)
SIGNUP_NOISE = 0.06        # month-to-month randomness in trial starts (lognormal sd)
DEC_SEASONALITY = 1.20     # December gift / holiday bump

REGIONS = {                # share of signups, currency, monthly price (local)
    "US": (0.45, "USD", 9.99),
    "EU": (0.25, "EUR", 9.99),
    "UK": (0.10, "GBP", 8.99),
    "BR": (0.20, "BRL", 29.90),
}
ANNUAL_MULTIPLE = 10       # annual plan = 10 x monthly price, billed up front
ANNUAL_SHARE = 0.25        # share of converting trials that pick annual

# platform: (share of signups in month 0, share in last month, trial conversion, fee)
PLATFORMS = {
    "Web":     (0.50, 0.38, 0.42, 0.03),   # card processing ~3%
    "iOS":     (0.30, 0.37, 0.35, 0.15),   # app store fee 15%
    "Android": (0.20, 0.25, 0.30, 0.15),
}

# Monthly-plan churn hazard at paid tenure t (months): HAZ_A * t ** HAZ_B
HAZ_A, HAZ_B = 0.16, -0.45
REGION_CHURN_MULT = {"US": 1.0, "EU": 0.95, "UK": 1.0, "BR": 1.35}
ANNUAL_RENEWAL = {"US": 0.72, "EU": 0.74, "UK": 0.72, "BR": 0.60}

# FX: USD per 1 unit of local currency, monthly random walk (start, drift, vol)
FX = {"USD": (1.0, 0.0, 0.0), "EUR": (1.08, 0.000, 0.012),
      "GBP": (1.27, 0.000, 0.012), "BRL": (0.205, -0.006, 0.025)}

# Real-world shocks the forecast does not know about in advance
JAN_CHURN_MULT = 1.25      # post-holiday cancellations in January
PRICE_UP_IDX = 44          # Sep 2025: US monthly plan +$1.00
PRICE_UP_USD = 1.00
PRICE_UP_CHURN_MULT = 1.6  # extra US monthly churn in the 2 months after the increase

FAR = 10_000               # "still active" sentinel for end month


def months(n=N_MONTHS, start=START):
    return pd.period_range(start, periods=n, freq="M")


def fx_table(n=N_MONTHS, seed=7):
    rng = np.random.default_rng(seed)
    rows = {}
    for ccy, (s0, drift, vol) in FX.items():
        steps = rng.normal(drift, vol, n) if vol else np.zeros(n)
        steps[0] = 0.0
        rows[ccy] = s0 * np.exp(np.cumsum(steps))
    df = pd.DataFrame(rows)
    df.insert(0, "month_idx", np.arange(n))
    return df


def simulate(n=N_MONTHS, seed=42):
    """One row per trial start with plan, conversion and end month."""
    rng = np.random.default_rng(seed)
    plat_names = list(PLATFORMS)
    reg_names = list(REGIONS)
    frames = []
    for m in range(n):
        k = BASE_SIGNUPS * (1 + SIGNUP_GROWTH) ** m
        if (m % 12) == 11:
            k *= DEC_SEASONALITY
        k = int(rng.poisson(k * rng.lognormal(0, SIGNUP_NOISE)))
        w = m / max(n - 1, 1)
        p_share = np.array([(1 - w) * a + w * b for a, b, _, _ in PLATFORMS.values()])
        p_share /= p_share.sum()
        plat = rng.choice(plat_names, size=k, p=p_share)
        reg = rng.choice(reg_names, size=k, p=[v[0] for v in REGIONS.values()])
        conv_p = np.array([PLATFORMS[p][2] for p in plat])
        converted = rng.random(k) < conv_p
        annual = converted & (rng.random(k) < ANNUAL_SHARE)
        frames.append(pd.DataFrame({"signup_idx": m, "platform": plat, "region": reg,
                                    "converted": converted, "annual": annual}))
    s = pd.concat(frames, ignore_index=True)
    s.insert(0, "sub_id", np.arange(len(s)))
    s["paid_start"] = np.where(s.converted, s.signup_idx + 1, -1)   # 1-month free trial
    s["end_idx"] = -1

    # monthly plan: churn at the end of each paid month with a tenure hazard
    mon = s.index[s.converted & ~s.annual]
    mult = s.loc[mon, "region"].map(REGION_CHURN_MULT).to_numpy()
    is_us = (s.loc[mon, "region"] == "US").to_numpy()
    p0 = s.loc[mon, "paid_start"].to_numpy()
    end = np.full(len(mon), FAR)
    alive = np.ones(len(mon), bool)
    for t in range(1, 3 * n):
        cal = p0 + t - 1                                   # month the churn decision lands in
        shock = np.where(cal % 12 == 0, JAN_CHURN_MULT, 1.0)
        shock = shock * np.where(is_us & ((cal == PRICE_UP_IDX) | (cal == PRICE_UP_IDX + 1)),
                                 PRICE_UP_CHURN_MULT, 1.0)
        h = np.clip(HAZ_A * t ** HAZ_B * mult * shock, 0, 1)
        churn = alive & (rng.random(len(mon)) < h)
        end[churn] = p0[churn] + t
        alive &= ~churn
    s.loc[mon, "end_idx"] = end

    # annual plan: renew (or not) every 12 months
    ann = s.index[s.annual]
    renew_p = s.loc[ann, "region"].map(ANNUAL_RENEWAL).to_numpy()
    end = np.full(len(ann), FAR)
    alive = np.ones(len(ann), bool)
    for term in range(1, 6):
        lapse = alive & (rng.random(len(ann)) >= renew_p)
        end[lapse] = s.loc[ann, "paid_start"].to_numpy()[lapse] + 12 * term
        alive &= ~lapse
    s.loc[ann, "end_idx"] = end

    s["currency"] = s.region.map({k: v[1] for k, v in REGIONS.items()})
    s["monthly_price"] = s.region.map({k: v[2] for k, v in REGIONS.items()})
    s["fee_rate"] = s.platform.map({k: v[3] for k, v in PLATFORMS.items()})
    return s


def monthly_revenue(subs, fx, n=N_MONTHS, constant_fx_idx=None):
    """Monthly billings, recognized revenue and net revenue in USD.

    Annual plans are billed up front but recognized 1/12 per month.
    If constant_fx_idx is set, every month is converted at that month's rates
    (constant-currency view)."""
    paid = subs[subs.converted]
    rows = []
    for m in range(n):
        act = paid[(paid.paid_start <= m) & (paid.end_idx > m)]
        fxm = fx.iloc[m if constant_fx_idx is None else constant_fx_idx]
        rate = act.currency.map(fxm).to_numpy()
        is_ann = act.annual.to_numpy()
        price = act.monthly_price.to_numpy() + np.where(
            (act.region.to_numpy() == "US") & ~is_ann & (m >= PRICE_UP_IDX), PRICE_UP_USD, 0.0)
        recog_local = np.where(is_ann, price * ANNUAL_MULTIPLE / 12, price)
        bill_local = np.where(is_ann,
                              np.where((m - act.paid_start.to_numpy()) % 12 == 0,
                                       price * ANNUAL_MULTIPLE, 0.0),
                              price)
        fee = act.fee_rate.to_numpy()
        rows.append({"month_idx": m,
                     "active_subs": len(act),
                     "active_monthly": int((~is_ann).sum()),
                     "active_annual": int(is_ann.sum()),
                     "billings_usd": float((bill_local * rate).sum()),
                     "gross_revenue_usd": float((recog_local * rate).sum()),
                     "net_revenue_usd": float((recog_local * (1 - fee) * rate).sum())})
    out = pd.DataFrame(rows)
    out.insert(1, "month", months(n).astype(str))
    out["arpu_net_usd"] = out.net_revenue_usd / out.active_subs.where(out.active_subs > 0)
    return out
