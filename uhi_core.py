"""
uhi_core.py - pure (Earth Engine-free) logic used by App.py.

Everything here is plain Python/NumPy so it can be unit tested without
Google Earth Engine or Streamlit (see tests/test_core.py). App.py imports
these constants and functions, so the tests check the code the app runs.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

try:
    import pymannkendall as mk
    HAS_MK = True
except Exception:  # pragma: no cover - fallback only
    HAS_MK = False

# --------------------------------------------------------------------------
# MODIS MOD11A1 / MYD11A1 LST scaling and QC
# --------------------------------------------------------------------------
MODIS_LST_SCALE = 0.02      # DN -> Kelvin
KELVIN_OFFSET = 273.15      # Kelvin -> degrees C
MODIS_QC_MANDATORY_BITS = 3  # bits 0-1 of QC_Day / QC_Night
MODIS_QC_MAX_ACCEPTED = 2    # keep 0 (good) and 1 (other quality); drop 2, 3

# Low vegetated-reference warning thresholds
MIN_REF_PERCENT = 2.0        # vegetated reference share of the AOI (%)
MIN_REF_PIXELS = 10          # valid LST pixels in the vegetated reference

TREND_TESTS = {
    "Mann–Kendall (original)": "original",
    "Hamed–Rao modified Mann–Kendall (autocorrelation-corrected)": "hamed_rao",
}


def modis_dn_to_celsius(dn):
    """Convert MODIS LST digital numbers to degrees C (DN * 0.02 - 273.15)."""
    return np.asarray(dn, dtype=float) * MODIS_LST_SCALE - KELVIN_OFFSET


def modis_qc_is_good(qc):
    """True where the QC mandatory flag (bits 0-1) is 0 or 1."""
    return (np.asarray(qc, dtype=int) & MODIS_QC_MANDATORY_BITS) < MODIS_QC_MAX_ACCEPTED


# --------------------------------------------------------------------------
# Month selection, SUHI, land-cover shares
# --------------------------------------------------------------------------
def pick_hottest_month(temps):
    """temps: iterable of (aoi_median_lst, month). Returns the month with the
    highest LST, ignoring None/NaN values; None if nothing is valid."""
    valid = [(t, m) for t, m in temps if t is not None and np.isfinite(t)]
    if not valid:
        return None
    return max(valid, key=lambda x: x[0])[1]


def suhi(urban_lst, veg_lst):
    """SUHI = urban LST - vegetated-reference LST; None if either is missing."""
    if urban_lst is None or veg_lst is None:
        return None
    if not (np.isfinite(urban_lst) and np.isfinite(veg_lst)):
        return None
    return float(urban_lst) - float(veg_lst)


def landcover_shares(total_area, urban_area, veg_area):
    """Area shares (%) of urban, vegetated reference and other.
    Returns NaNs (not zeros) when the total area is missing or zero."""
    nan3 = (math.nan, math.nan, math.nan)
    try:
        tot = float(total_area) if total_area is not None else math.nan
        u = float(urban_area) if urban_area is not None else 0.0
        v = float(veg_area) if veg_area is not None else 0.0
    except (TypeError, ValueError):
        return nan3
    if not np.isfinite(tot) or tot <= 0:
        return nan3
    up = u / tot * 100.0
    vp = v / tot * 100.0
    op = max(0.0, 100.0 - up - vp)
    return up, vp, op


def low_reference(veg_percent, veg_pixels,
                  min_percent=MIN_REF_PERCENT, min_pixels=MIN_REF_PIXELS):
    """True when the vegetated reference is too small to be reliable."""
    small_share = veg_percent is not None and np.isfinite(veg_percent) and veg_percent < min_percent
    few_pixels = veg_pixels is not None and np.isfinite(veg_pixels) and veg_pixels < min_pixels
    return bool(small_share or few_pixels)


def average_monthly_records(records, numeric_keys):
    """Seasonal mean: average the per-month records of one year.
    Each numeric field is the mean over the months where it is valid."""
    out = {}
    for k in numeric_keys:
        vals = [r.get(k) for r in records]
        vals = [float(v) for v in vals if v is not None and np.isfinite(float(v))]
        out[k] = float(np.mean(vals)) if vals else None
    return out


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------
def moving_average_by_year(years, values, window=3):
    """Centered moving average on the calendar-year axis: missing years stay
    gaps instead of joining non-adjacent years. Used for display only."""
    s = pd.Series(np.asarray(values, dtype=float), index=np.asarray(years, dtype=int))
    full = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1))
    ma = full.rolling(window=window, center=True, min_periods=1).mean()
    return ma.reindex(s.index).to_numpy()


def trend_stats(years, values, test="original"):
    """Theil-Sen slope (units per year, on the real year axis) and the
    Mann-Kendall p-value of the UNSMOOTHED annual series.

    test: 'original'  -> original Mann-Kendall
          'hamed_rao' -> Hamed-Rao variance-corrected Mann-Kendall
    Returns (slope, p); (None, None) with fewer than 3 valid years."""
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if y.size < 3:
        return None, None
    order = np.argsort(x)
    x, y = x[order], y[order]
    slope = float(stats.theilslopes(y, x)[0])
    p = None
    if HAS_MK:
        try:
            if test == "hamed_rao":
                p = float(mk.hamed_rao_modification_test(y).p)
            else:
                p = float(mk.original_test(y).p)
        except Exception:
            p = None
    if p is None or not np.isfinite(p):
        p = float(stats.kendalltau(x, y)[1])
    return slope, p
