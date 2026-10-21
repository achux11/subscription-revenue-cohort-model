"""Build the full model and write subscription_revenue_model.xlsx."""
import pandas as pd
from subrev.data import simulate, fx_table, monthly_revenue, N_MONTHS
from subrev import analysis as A

subs = simulate()
fx = fx_table(N_MONTHS + 24)
n = N_MONTHS
hist = monthly_revenue(subs, fx, n=n)
ret = A.cohort_retention(subs, n)
curve = A.churn_curve(subs, n, max_tenure=18)
a, b = A.fit_hazard(curve)
conv = A.conversion_by_platform(subs, n)
mix = A.platform_mix(subs, fx, n)
bt, bt_stats = A.backtest(subs, fx, fit_end=n - 7, horizon=6)
bt24, bt24_stats = A.backtest(subs, fx, fit_end=n - 25, horizon=24)
fc, params = A.forecast(subs, fx, fit_end=n - 1, horizon=24)
fy26 = fc[fc.month.str.startswith("2026")].fc_net_revenue_usd.sum()
fy27 = fc[fc.month.str.startswith("2027")].fc_net_revenue_usd.sum()
bridge = A.fx_bridge(subs, fx, n)
cmix = A.currency_mix(subs, fx, n - 1)
scen = A.fx_scenarios(fy26, cmix)
fy25 = hist[hist.month.str.startswith("2025")].net_revenue_usd.sum()

summary = {
    "Trial starts (Jan 2022 - Dec 2025)": len(subs),
    "Paid subscribers ever": int(subs.converted.sum()),
    "Active subscribers, Dec 2025": int(hist.active_subs.iloc[-1]),
    "Trial-to-paid conversion": subs[subs.signup_idx <= n - 2].converted.mean(),
    "Month-1 churn (monthly plan)": curve.churn_rate.iloc[0],
    "Month-12 churn (monthly plan)": curve.loc[curve.tenure == 12, "churn_rate"].iloc[0],
    "12-month retention, monthly plan (avg cohort)": ret[12].mean(),
    "Annual-plan renewal rate": A.annual_renewal_rate(subs, n)[0],
    "Net ARPU, Dec 2025 (USD/month)": hist.arpu_net_usd.iloc[-1],
    "FY2025 net revenue (USD)": fy25,
    "FY2025 billings (USD)": hist[hist.month.str.startswith("2025")].billings_usd.sum(),
    "Revenue growth FY25 vs FY24, reported": bridge["reported_growth"],
    "Revenue growth FY25 vs FY24, constant currency": bridge["constant_ccy_growth"],
    "FX drag (pts)": bridge["fx_drag_pts"],
    "Backtest revenue MAPE (6 mo, fit Jun 2025)": bt_stats["revenue_mape"],
    "Backtest revenue MAPE, naive run-rate baseline": bt_stats["naive_revenue_mape"],
    "Backtest subscriber MAPE (6 mo)": bt_stats["subs_mape"],
    "Long-range backtest revenue MAPE (24 mo, fit Dec 2023)": bt24_stats["revenue_mape"],
    "Long-range backtest MAPE, naive run-rate baseline": bt24_stats["naive_revenue_mape"],
    "Forecast FY2026 net revenue (USD, constant ccy)": fy26,
    "Forecast FY2027 net revenue (USD, constant ccy)": fy27,
    "Non-USD share of revenue, Dec 2025": 1 - cmix.get("USD", 0),
    "Mobile (iOS+Android) share of net revenue, first month": mix.iloc[:, 0].drop("Web").sum(),
    "Mobile (iOS+Android) share of net revenue, Dec 2025": mix.iloc[:, 1].drop("Web").sum(),
}
for k, v in summary.items():
    print(f"{k:55s} {v:,.4f}" if isinstance(v, float) else f"{k:55s} {v:,}")
print("hazard fit a=%.3f b=%.3f" % (a, b))
print(conv); print(mix); print(scen); 

# robustness: the same backtests on 10 independent simulations
import numpy as np
rob = []
for sd in range(1, 11):
    s2 = simulate(seed=sd)
    _, s6 = A.backtest(s2, fx, fit_end=n - 7, horizon=6)
    _, s24 = A.backtest(s2, fx, fit_end=n - 25, horizon=24)
    rob.append({"seed": sd, "cohort_mape_6mo": s6["revenue_mape"], "naive_mape_6mo": s6["naive_revenue_mape"],
                "cohort_mape_24mo": s24["revenue_mape"], "naive_mape_24mo": s24["naive_revenue_mape"]})
rob = pd.DataFrame(rob)
print(rob.round(3)); print("median:", rob.median().round(4).to_dict())
print("cohort beats naive at 24 mo in", int((rob.cohort_mape_24mo < rob.naive_mape_24mo).sum()), "of 10")
print("cohort beats naive at 6 mo in", int((rob.cohort_mape_6mo < rob.naive_mape_6mo).sum()), "of 10")

with pd.ExcelWriter("subscription_revenue_model.xlsx") as w:
    pd.Series(summary, name="value").to_frame().to_excel(w, sheet_name="Summary")
    hist.to_excel(w, sheet_name="Monthly Revenue", index=False)
    ret.to_excel(w, sheet_name="Cohort Retention")
    curve.to_excel(w, sheet_name="Churn Curve", index=False)
    conv.to_excel(w, sheet_name="Trial Conversion")
    mix.to_excel(w, sheet_name="Platform Mix")
    bt.to_excel(w, sheet_name="Backtest 6mo", index=False)
    bt24.to_excel(w, sheet_name="Backtest 24mo", index=False)
    fc.to_excel(w, sheet_name="Forecast 2026-27", index=False)
    pd.Series(params).to_frame("value").to_excel(w, sheet_name="Forecast Assumptions")
    scen.to_excel(w, sheet_name="FX Scenarios", index=False)
    cmix.to_frame("share").to_excel(w, sheet_name="Currency Mix")
    rob.to_excel(w, sheet_name="Backtest Robustness", index=False)
