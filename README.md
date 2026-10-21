# Subscription Revenue & Cohort Forecast Model

**A consumer-subscription revenue model: trial conversion, cohort retention, churn curves, ARPU, platform and currency mix, a cohort-based long-range forecast, and FX scenarios.**

Built on a **simulated** subscription business (Jan 2022 – Dec 2025) so every assumption is visible and changeable in `subrev/data.py`. It is not real company data.

## What it models

| Area | What it does |
|---|---|
| **Trials & conversion** | 1-month free trial, conversion by platform (Web / iOS / Android) |
| **Plans** | Monthly plan, and an annual plan billed up front and recognized 1/12 per month (billings ≠ revenue) |
| **Churn curve** | Monthly churn by paid tenure, fitted as `churn(t) = a · t^b` on observed months only |
| **Cohorts** | Retention matrix by paid-start month |
| **ARPU & mix** | Net ARPU after app-store (15%) and card (3%) fees; platform mix and currency mix of revenue |
| **FX** | 4 currencies (USD, EUR, GBP, BRL); reported vs. constant-currency growth; ±10% USD scenarios |
| **Forecast** | Cohort-based: existing subscribers × fitted survival + new trials × conversion × survival + annual renewals, in constant currency |
| **Backtest** | Fit on data up to a cut-off, forecast the next 6 or 24 months, compare to actuals and to a naive run-rate forecast |

Real-world shocks the forecast is **not** told about: January churn spikes, a US price increase in Sep 2025 (+$1.00, with extra churn), and random month-to-month noise in signups.

## Results (`python run.py`)

| Metric | Value |
|---|---|
| Trial starts / paid subscribers | 285,585 / 105,096 |
| Active subscribers, Dec 2025 | 40,925 |
| Trial-to-paid conversion | 36.9% (Web 41.9%, iOS 35.1%, Android 29.8%) |
| Monthly-plan churn | **17.4%** in month 1 → **5.8%** by month 12 |
| 12-month retention, monthly plan (avg cohort) | 34.1% |
| Annual-plan renewal | 70.1% |
| Net ARPU, Dec 2025 | $7.67 / month |
| FY2025 net revenue / billings | $3.37M / $3.89M |
| FY2025 growth: reported vs. constant currency | **+30.7% vs. +32.8%** (FX drag 2.1 pts) |
| Mobile share of net revenue, Jan 2024 → Dec 2025 | 44.4% → 49.0% |
| FY2026 / FY2027 forecast (constant currency) | **$4.28M / $5.20M** |
| FY2026 if non-USD currencies move ±10% vs. USD | **±$201K** (47% of revenue is non-USD) |

### Forecast accuracy (revenue MAPE, 10 independent simulations)

| Horizon | Cohort model (median) | Naive run-rate (median) | Cohort model wins |
|---|---|---|---|
| 6 months | 1.7% | 1.3% | 3 of 10 |
| **24 months** | **2.8%** | **17.6%** | **10 of 10** |

> 💡 **Over 6 months, a simple run-rate is as good or better. Over 24 months, the cohort model is far more accurate**, because a run-rate can't see that young cohorts churn fast and older cohorts stabilize.

## Outputs

`subscription_revenue_model.xlsx`: Summary, Monthly Revenue, Cohort Retention, Churn Curve, Trial Conversion, Platform Mix, Backtest 6mo, Backtest 24mo, Forecast 2026-27, Forecast Assumptions, FX Scenarios, Currency Mix, Backtest Robustness.

## Run

```bash
pip install -r requirements.txt
python run.py      # ~10 s, prints results and writes the workbook
pytest -q          # 7 tests
```

Tests cover conversion by platform, a declining churn curve, monotonic cohort retention, billings vs. recognized revenue, **no future data leaking into the forecast**, the long-range backtest beating the naive baseline, and FX scenario math.

## Layout

```
subrev/data.py       # simulated business: assumptions, subscribers, FX, monthly revenue
subrev/analysis.py   # cohorts, churn curve, conversion, mix, forecast, backtest, FX
run.py               # builds everything and writes the Excel workbook
tests/test_model.py  # 7 tests
```

## Limitations

- Simulated data: the churn curve shape is a modeling assumption, so the backtest shows the method works when its assumption roughly holds (plus shocks), not that it would hit 2.8% on real data.
- One pooled churn curve; a production model would fit by plan, region and platform.
- FX scenarios move all non-USD currencies together.
