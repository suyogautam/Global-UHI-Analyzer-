"""Unit tests for the Earth Engine-free logic used by App.py (uhi_core.py).

Run from the repository root:  pytest -q
"""
import math

import numpy as np
import pymannkendall as mk
import pytest
from scipy import stats

import uhi_core as core


# ---------------------------------------------------------------- MODIS LST
def test_modis_scale_and_offset():
    # 15000 DN * 0.02 = 300 K = 26.85 degC
    assert core.modis_dn_to_celsius(15000) == pytest.approx(26.85)
    assert core.modis_dn_to_celsius([13657.5]) == pytest.approx([0.0])
    assert core.MODIS_LST_SCALE == 0.02 and core.KELVIN_OFFSET == 273.15


@pytest.mark.parametrize("qc, good", [
    (0b00, True),       # LST produced, good quality
    (0b01, True),       # LST produced, other quality
    (0b10, False),      # not produced (cloud)
    (0b11, False),      # not produced (other)
    (0b1100_0100, True),   # higher bits ignored, mandatory bits = 00
    (0b1100_0110, False),  # higher bits ignored, mandatory bits = 10
])
def test_modis_qc_mask(qc, good):
    assert bool(core.modis_qc_is_good(qc)) is good


# ------------------------------------------------------- month and SUHI logic
def test_hottest_month_selection():
    temps = [(30.1, 6), (35.4, 7), (34.9, 8)]
    assert core.pick_hottest_month(temps) == 7


def test_hottest_month_ignores_missing_months():
    assert core.pick_hottest_month([(None, 6), (float("nan"), 7), (31.0, 8)]) == 8
    assert core.pick_hottest_month([(None, 6), (None, 7)]) is None
    assert core.pick_hottest_month([]) is None


def test_suhi_difference():
    assert core.suhi(36.5, 31.25) == pytest.approx(5.25)
    assert core.suhi(30.0, 31.0) == pytest.approx(-1.0)   # negative SUHI kept


def test_suhi_missing_is_none_not_zero():
    assert core.suhi(None, 31.0) is None
    assert core.suhi(35.0, None) is None
    assert core.suhi(float("nan"), 31.0) is None


# ------------------------------------------------------- land-cover shares
def test_landcover_shares():
    up, vp, op = core.landcover_shares(1000.0, 250.0, 150.0)
    assert (up, vp, op) == pytest.approx((25.0, 15.0, 60.0))


def test_landcover_shares_missing_total_gives_nan_not_zero():
    for total in (None, 0.0, float("nan")):
        assert all(math.isnan(v) for v in core.landcover_shares(total, 10.0, 10.0))


def test_landcover_shares_no_class_pixels_is_real_zero():
    assert core.landcover_shares(1000.0, None, 0.0) == pytest.approx((0.0, 0.0, 100.0))


def test_low_reference_flag():
    assert core.low_reference(1.5, 500) is True                      # small share
    assert core.low_reference(20.0, core.MIN_REF_PIXELS - 1) is True  # few pixels
    assert core.low_reference(20.0, 500) is False
    assert core.low_reference(float("nan"), None) is False            # unknown is not flagged


# ------------------------------------------------------------ seasonal mean
def test_seasonal_mean_of_monthly_records():
    recs = [{"UHI": 3.0, "Urban": 34.0, "Mean_NDVI": 0.5},
            {"UHI": 4.0, "Urban": 36.0, "Mean_NDVI": None},
            {"UHI": 5.0, "Urban": 38.0, "Mean_NDVI": 0.3}]
    out = core.average_monthly_records(recs, ["UHI", "Urban", "Mean_NDVI", "Absent"])
    assert out["UHI"] == pytest.approx(4.0)
    assert out["Urban"] == pytest.approx(36.0)
    assert out["Mean_NDVI"] == pytest.approx(0.4)    # mean of valid months only
    assert out["Absent"] is None


# ------------------------------------------------------------------ trends
def test_moving_average_respects_missing_years():
    years = [2000, 2001, 2003, 2004]
    vals = [1.0, 2.0, 4.0, 5.0]
    ma = core.moving_average_by_year(years, vals)
    # 2001 window = 2000, 2001, (2002 missing) -> mean(1, 2), not mean(1, 2, 4)
    assert ma[1] == pytest.approx(1.5)
    assert ma[2] == pytest.approx(4.5)


def test_trend_exact_linear_series():
    years = np.arange(2000, 2025)
    slope, p = core.trend_stats(years, 0.05 * (years - 2000) + 2.0)
    assert slope == pytest.approx(0.05)
    assert p < 1e-6


def test_trend_uses_real_year_axis_with_gaps():
    years = np.array([2000, 2001, 2002, 2010, 2011, 2012])
    slope, _ = core.trend_stats(years, 0.1 * years)
    assert slope == pytest.approx(0.1)   # per year, not per observation


def test_trend_matches_reference_implementations():
    rng = np.random.default_rng(42)
    years = np.arange(2000, 2025)
    y = 0.03 * (years - 2000) + rng.normal(0, 0.6, years.size)
    slope, p = core.trend_stats(years, y, "original")
    assert slope == pytest.approx(stats.theilslopes(y, years)[0])
    assert p == pytest.approx(mk.original_test(y).p)
    _, p_hr = core.trend_stats(years, y, "hamed_rao")
    assert p_hr == pytest.approx(mk.hamed_rao_modification_test(y).p)


def test_trend_ignores_nan_and_needs_three_years():
    years = np.arange(2000, 2006)
    y = np.array([1.0, np.nan, 3.0, 4.0, np.nan, 6.0])
    slope, p = core.trend_stats(years, y)
    assert slope == pytest.approx(1.0) and p is not None
    assert core.trend_stats([2000, 2001], [1.0, 2.0]) == (None, None)


def test_smoothing_inflates_significance():
    """Why the app tests the raw series: a 3-yr moving average makes a
    trend-free noisy series look significant far more often (reviewer comment)."""
    rng = np.random.default_rng(7)
    years = np.arange(2000, 2025)
    false_raw = false_ma = 0
    for _ in range(300):
        y = rng.normal(0, 1, years.size)             # no trend at all
        _, p_raw = core.trend_stats(years, y)
        _, p_ma = core.trend_stats(years, core.moving_average_by_year(years, y))
        false_raw += p_raw < 0.05
        false_ma += p_ma < 0.05
    assert false_raw / 300 < 0.10                     # close to the nominal 5 %
    assert false_ma > 2 * false_raw                   # smoothing inflates it
