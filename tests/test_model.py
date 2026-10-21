import numpy as np
import pytest
from subrev.data import simulate, fx_table, monthly_revenue, N_MONTHS
from subrev import analysis as A


@pytest.fixture(scope="module")
def world():
    return simulate(n=N_MONTHS, seed=1), fx_table(N_MONTHS + 24)


def test_trial_conversion_matches_platform_assumptions(world):
    subs, _ = world
    conv = A.conversion_by_platform(subs, N_MONTHS).conversion
    assert conv["Web"] > conv["iOS"] > conv["Android"]
    assert abs(conv["Web"] - 0.42) < 0.02


def test_churn_curve_declines_with_tenure(world):
    subs, _ = world
    c = A.churn_curve(subs, N_MONTHS, max_tenure=12)
    assert c.churn_rate.iloc[0] > c.churn_rate.iloc[-1]
    a, b = A.fit_hazard(c)
    assert b < 0 and 0.1 < a < 0.25


def test_retention_is_monotonic_within_cohort(world):
    subs, _ = world
    r = A.cohort_retention(subs, N_MONTHS).dropna()
    assert (np.diff(r.to_numpy(), axis=1) <= 1e-12).all()


def test_annual_billed_up_front_recognized_monthly(world):
    subs, fx = world
    rev = monthly_revenue(subs, fx)
    fy = rev[rev.month.str.startswith("2025")]
    assert fy.billings_usd.sum() > fy.gross_revenue_usd.sum() > fy.net_revenue_usd.sum()


def test_forecast_uses_only_past_data(world):
    subs, fx = world
    leaked = subs.copy()
    leaked.loc[leaked.signup_idx > 30, "converted"] = False   # change the future
    fc1, _ = A.forecast(subs, fx, fit_end=30, horizon=6)
    fc2, _ = A.forecast(leaked, fx, fit_end=30, horizon=6)
    assert np.allclose(fc1.fc_net_revenue_usd, fc2.fc_net_revenue_usd)


def test_long_range_backtest_beats_naive(world):
    subs, fx = world
    _, st = A.backtest(subs, fx, fit_end=N_MONTHS - 25, horizon=24)
    assert st["revenue_mape"] < 0.10
    assert st["revenue_mape"] < st["naive_revenue_mape"]


def test_fx_scenarios_scale_with_non_usd_share():
    import pandas as pd
    s = A.fx_scenarios(100.0, pd.Series({"USD": 0.6, "EUR": 0.4}))
    assert s.impact_usd.round(6).tolist() == [-4.0, 0.0, 4.0]
