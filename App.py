# UHI Analyzer – Landsat + MODIS (Streamlit app)
# Satellite-based urban heat island analysis using Google Earth Engine.
# Supports county, city, drawn polygon, and shapefile AOIs.
# Landsat 5/7/8/9 (30 m) and MODIS Terra+Aqua (1 km) pipelines.
# NLCD or MODIS MCD12Q1 land cover for urban/vegetated separation.
# Outputs: results table, trend charts, interactive maps, GeoTIFF, shapefile, ERA5 validation.

from __future__ import annotations
import streamlit as st
import geemap
# geemap.foliumap is NOT imported here — it crashes on Streamlit Cloud (BoxKeyError).
# The Map class is imported lazily inside folium_map_with_layers() below.
import geopandas as gpd
import pandas as pd
import zipfile, os, io, tempfile, requests
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from scipy import stats
from validation_era5 import render_validation_tab

try:
    import pymannkendall as mk
    _HAS_MK = True
except Exception:
    _HAS_MK = False
import ee
from datetime import datetime

from streamlit_folium import st_folium
import folium
from folium.plugins import Draw, Fullscreen, MousePosition, Geocoder


from shapely.geometry import shape as shp_shape, Point as shp_Point

# ----------------------------
# Page & UI
# ----------------------------
st.set_page_config(page_title="Urban Heat Island Analyzer", page_icon="🌡️", layout="wide")
st.title("Urban Heat Island (UHI) Analyzer – Landsat + MODIS")
st.caption(
    "Landsat (30 m) or MODIS (1 km) · hottest-month selection per year · "
    "NDVI, NDMI, NDBI, LST, UHI · trend analysis with Sen’s slope & Mann–Kendall · "
    "NLCD/MODIS LULC · interactive maps · GeoTIFF & shapefile export. "
    "**NLCD-based analysis (Landsat & MODIS) is US-only. For global coverage, switch to MODIS + MCD12Q1 land cover.**"
)

with st.expander("🔍 How it works"):
    st.markdown("""
### Overview
Analyze UHI for **any U.S. county**, a **city**, or a **custom drawn/uploaded AOI** using **Landsat** (30 m, 2000–2026) or **MODIS** (1 km, 2000–2026). For each year the app identifies the **hottest month** (from your selected month set) based on peak daytime LST, computes spectral indices and land surface temperature, separates urban from vegetated pixels using NLCD or MODIS MCD12Q1 land cover, and calculates UHI intensity. Results include year-by-year tables, trend analysis, interactive maps, and multiple export options.

> ⚠️ **Coverage note:** NLCD-based analysis (Landsat and MODIS) is **US-only**. For areas outside the US, switch to **MODIS + MCD12Q1** land cover. MODIS MCD12Q1 has a 500 m pixel size — small cities where urban-class pixels are absent or sparse within the AOI may return no urban data or unreliable UHI estimates.

---

### Landsat pipeline (30 m · Collection 2 Level-2)
1. **Sensors:** Landsat 5 TM (2000–2012), Landsat 7 ETM+ (gap-fill only), Landsat 8 OLI-TIRS and Landsat 9 (2013–2026) — pulled from `LANDSAT/LT05`, `LC07`, `LC08`, `LC09` C02 T1_L2 collections.
2. **Scale factors:** Surface reflectance `SR_* × 0.0000275 − 0.2`; surface temperature (Kelvin) `ST_* × 0.00341802 + 149.0` → °C.
3. **Cloud/shadow masking:** `QA_PIXEL` bitmask (cloud, cloud shadow, dilated cloud).
4. **Monthly median composites** per selected month.
5. **Hottest month selection:** Highest AOI-median LST across the selected month set.
6. **Outlier filtering:** LST clipped to 5th–95th percentiles within AOI before statistics.
7. **Spectral indices:** NDVI = (NIR − Red)/(NIR + Red); NDMI = (NIR − SWIR1)/(NIR + SWIR1); NDBI = (SWIR1 − NIR)/(SWIR1 + NIR). Bands mapped per sensor.
8. **Land cover (NLCD):** Nearest available year (2001–2021). Urban = classes 22–24 (Developed Low/Med/High); Vegetated = 41–43, 52, 71, 21. Water (11) and Cropland (82) excluded from vegetated reference.
9. **UHI = urban median LST − vegetated median LST.** Area percentages computed from pixel counts.

### MODIS pipeline (1 km · Terra + Aqua merged)
1. **Daytime LST:** `MOD11A1` + `MYD11A1` merged, `LST_Day_1km` band, QC-filtered, scaled to °C, monthly median.
2. **Hottest month selection:** Highest AOI-median daytime LST.
3. **Nighttime LST:** Same hottest month, `LST_Night_1km`, same QC and scale logic.
4. **Spectral indices (day):** `MOD09GA` surface reflectance (× 0.0001), monthly median → NDVI, NDMI, NDBI.
5. **Land cover:** NLCD (US-only) or MODIS MCD12Q1 IGBP (`MODIS/061/MCD12Q1`, annual 2001–present, global). Urban = class 13; Vegetated = classes 1–10 (forests, shrublands, savannas, grasslands).
6. **UHI** computed for both day and night using the same urban/vegetated separation.

### Trend analysis
Each metric (UHI, Mean LST, NDVI, NDMI, NDBI) is plotted as original annual values with a 3-year centered moving average. **Sen’s slope** and **Mann–Kendall p-value** are fitted separately to both the original and smoothed series. UHI slope and p-value are included in the results table and exported CSV.

### Outputs
- **Results table** (CSV) — yearly metrics, land-cover percentages, slope/p-values.
- **Trend charts** (PNG ZIP) — UHI, LST, NDVI, NDMI, NDBI, urban vs vegetated comparison.
- **Interactive map** — toggle LST, NDVI, NDMI, NDBI, LULC, UHI layers; continuous colorbars; AOI outline.
- **GeoTIFF export** — all raster layers for any selected year queued to Google Drive.
- **Shapefile export** (ZIP) — AOI polygon + per-year point features with all metrics as attributes.
- **ERA5 validation tab** — Pearson correlation of satellite LST anomalies against ERA5-Land 2 m air temperature reanalysis.
""")

with st.expander("📋 How to use this app"):
    st.markdown("""
### Step-by-step guide

**1. Authenticate**
Upload your Google Earth Engine credentials file (or use local auth if running locally). Enter your GEE Project ID and click Authenticate.

**2. Select your sensor platform**
- *Landsat* — 30 m resolution, US-only NLCD land cover, good for detailed city-scale analysis.
- *MODIS* — 1 km resolution, supports global coverage when paired with MCD12Q1. Also provides nighttime LST.

**3. Define your Area of Interest (AOI)**
Choose one of four modes from the sidebar:
- **County** — select a US state then county; the county boundary is used directly.
- **City** — select a state and city, then choose Census boundary or CCA-derived urban cluster (1000 m gap).
- **Draw** — use the drawing tool on the interactive map; finish the polygon and click *Use this polygon*.
- **Shapefile** — upload a ZIP containing a .shp file (and associated .dbf/.shx/.prj).

**4. Set your time range and months**
- Choose start and end year (2000–2026).
- Select individual months or use the season preset (e.g. JJA = Jun–Aug for summer analysis).

**5. Select land cover source** *(MODIS only)*
- *NLCD* — 30 m, US-only, biennial updates.
- *MODIS MCD12Q1* — 500 m, global, annual. Required for non-US AOIs. May not detect urban pixels in small cities.

**6. Urban & Vegetative classes** *(optional)*
Expand the *Urban & Vegetative Reference* panel to customize which land cover classes define the urban and vegetated zones. Default recommended classes are pre-selected.

**7. Run Analysis**
Click **Run Analysis**. Processing time depends on the number of years and AOI size (typically 1–5 minutes).

---

### Reading the outputs

**Results Table tab**
- One row per year showing Urban LST, Vegetated LST, Mean LST, UHI intensity, NDVI, NDMI, NDBI, and land-cover percentages.
- Download as CSV.

**Charts tab**
- Each metric plotted as yearly values + 3-year moving average.
- Sen’s slope (trend rate in °C/yr or index units/yr) and Mann–Kendall p-value shown for significance.
- Urban vs Vegetated temperature comparison chart included.
- Download all charts as a ZIP of PNGs.

**Interactive Map tab**
- Select any year from the dropdown to load that year’s layers.
- Toggle individual layers (LST, NDVI, NDMI, NDBI, LULC, UHI, AOI boundary) in the layer control (top-right).
- Horizontal colorbars at the top show the value range for each continuous layer.
- Export rasters to Google Drive from this tab.

**Land Cover Change tab**
- Pie charts showing urban/vegetated/other proportions per year.

**Shapefile Export tab**
- Download AOI and point features with all metrics as attributes for use in GIS software.

**Validation tab**
- Compares satellite-derived LST anomalies against ERA5-Land 2 m air temperature (Pearson r, p-value, scatter plot, time series).
""")

with st.expander("🧑‍💻 About the developer"):
    st.markdown("""
**Suyog Gautam**

This app was built as an open-source tool for satellite-based urban heat island research using Google Earth Engine.

🔗 [GitHub — github.com/suyogautam](https://github.com/suyogautam)  
💼 [LinkedIn — Suyog Gautam](https://www.linkedin.com/in/suyog-gautam-76488a253/)

**Open source & citation**  
This project is open source. If you use or adapt this app for your own work or build a similar tool, please cite using the `cite me` file in the GitHub repository.
""")

# ----------------------------
# EE Authentication Gate
# ----------------------------
from auth_handler import render_auth_gate
if not render_auth_gate():
    st.stop()

# ----------------------------
# Census helpers
# ----------------------------

# All 50 states + DC with FIPS codes — no API needed for this list
_FALLBACK_STATES = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05",
    "California": "06", "Colorado": "08", "Connecticut": "09", "Delaware": "10",
    "Florida": "12", "Georgia": "13", "Hawaii": "15", "Idaho": "16",
    "Illinois": "17", "Indiana": "18", "Iowa": "19", "Kansas": "20",
    "Kentucky": "21", "Louisiana": "22", "Maine": "23", "Maryland": "24",
    "Massachusetts": "25", "Michigan": "26", "Minnesota": "27", "Mississippi": "28",
    "Missouri": "29", "Montana": "30", "Nebraska": "31", "Nevada": "32",
    "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35", "New York": "36",
    "North Carolina": "37", "North Dakota": "38", "Ohio": "39", "Oklahoma": "40",
    "Oregon": "41", "Pennsylvania": "42", "Rhode Island": "44", "South Carolina": "45",
    "South Dakota": "46", "Tennessee": "47", "Texas": "48", "Utah": "49",
    "Vermont": "50", "Virginia": "51", "Washington": "53", "West Virginia": "54",
    "Wisconsin": "55", "Wyoming": "56", "District of Columbia": "11",
}

def _census_api_is_down():
    """Returns True if the last Census API call failed (no key or key invalid)."""
    return st.session_state.get("_census_api_down", False)

def _get_census_key():
    """Return the Census API key stored in session state, or empty string."""
    return st.session_state.get("census_api_key", "").strip()

def _census_key_missing():
    """True if no Census API key has been entered."""
    return _get_census_key() == ""

def _fetch_states_from_census():
    """
    Returns (state_dict, api_ok: bool).
    Never writes to st.session_state — caller handles state.
    Never raises — any failure returns the fallback list.
    """
    import json as _json
    key = _get_census_key()
    if not key:
        return _FALLBACK_STATES, False

    url = f"https://api.census.gov/data/2019/acs/acs1?get=NAME&for=state:*&key={key}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        text = r.text.strip()
        if not text.startswith("["):
            return _FALLBACK_STATES, False
        data = _json.loads(text)
        if not isinstance(data, list) or len(data) < 2:
            return _FALLBACK_STATES, False
        return {row[0]: row[1] for row in data[1:]}, True
    except Exception:
        return _FALLBACK_STATES, False

def _fetch_counties_from_census(state_id: str):
    """
    Returns county name → FIPS dict for a given state FIPS.
    Requires Census API key. Returns empty dict on failure.
    """
    key = _get_census_key()
    if not key:
        return {}

    url = f"https://api.census.gov/data/2019/acs/acs1?get=NAME&for=county:*&in=state:{state_id}&key={key}"
    try:
        import json as _json
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        text = r.text.strip()
        if not text.startswith("["):
            raise ValueError("Response is not JSON")
        rows = _json.loads(text)
        if not isinstance(rows, list) or len(rows) < 2:
            raise ValueError("Unexpected format")
        counties = {}
        for row in rows[1:]:
            full = row[0]
            cid = str(row[-1])
            counties[full.split(",")[0]] = cid
        return counties
    except Exception:
        return {}

def load_places_for_state(state_fips: str):
    """
    Load city names using Census Tiger/Line 2023 Places.
    Stable, permanent URL from Census Bureau.
    """
    import requests, geopandas as gpd, zipfile, tempfile, os, io

    # Use Tiger/Line 2023 (most recent stable version)
    url = f"https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_{state_fips.zfill(2)}_place.zip"
    
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        st.warning(f"Could not download Census data: {e}")
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                shp = [f for f in os.listdir(tmp) if f.endswith(".shp")][0]
                gdf = gpd.read_file(os.path.join(tmp, shp))
        
        # Get unique place names, sorted
        names = sorted(gdf["NAME"].unique())
        return names
    except Exception as e:
        st.warning(f"Could not parse shapefile: {e}")
        return []
# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Analysis Parameters")

# Census API key input — required for County and City AOI modes
with st.sidebar.expander("🗝️ Census API Key", expanded=_census_key_missing()):
    st.markdown(
        "**County** and **City** AOI modes use the Census ACS API, "
        "which now requires a free key. "
        "**Custom AOI** (draw/upload) works without one."
    )
    _key_input = st.text_input(
        "Census API Key",
        value=st.session_state.get("census_api_key", ""),
        type="password",
        placeholder="Paste your Census API key here",
        key="_census_key_widget"
    )
    if _key_input != st.session_state.get("census_api_key", ""):
        st.session_state["census_api_key"] = _key_input
        st.session_state.pop("_census_api_down", None)
        st.session_state.pop("_census_key_invalid", None)
        st.rerun()
    if _census_key_missing():
        st.caption(
            "Get a free key (delivered by email instantly): "
            "[api.census.gov/data/key\_signup.html](https://api.census.gov/data/key_signup.html)"
        )
    elif st.session_state.get("_census_key_invalid"):
        st.error("❌ Key invalid or rejected. Check for typos or re-request at "
                 "[api.census.gov/data/key\_signup.html](https://api.census.gov/data/key_signup.html)")
    else:
        st.success("✅ Census API key set.")

# AOI source selector
aoi_source = st.sidebar.radio("AOI Source", ["County (US only)", "City (US only)", "Custom AOI (US / Global)"], index=0)

try:
    states, _census_ok = _fetch_states_from_census()
    st.session_state["_census_api_down"] = not _census_ok
    if _census_ok:
        st.session_state["_census_key_invalid"] = False
    elif _get_census_key():
        # Had a key but API call failed — likely invalid key
        st.session_state["_census_key_invalid"] = True
except Exception:
    states = _FALLBACK_STATES
    st.session_state["_census_api_down"] = True
aoi_mode = "County boundary"  # internal switch used by run_btn logic

# Show appropriate notice about Census key status
if _census_key_missing():
    st.info(
        "ℹ️ **Census API key required for County and City modes.** "
        "Enter your free key in the **🗝️ Census API Key** panel in the sidebar. "
        "Get one at [api.census.gov/data/key\_signup.html](https://api.census.gov/data/key_signup.html). "
        "\n\n**Custom AOI** (draw or upload shapefile) works without a key and supports global areas."
    )
elif _census_api_is_down():
    st.warning(
        "⚠️ **Census API unreachable or key rejected.** "
        "County and City modes are disabled. Check your key or use **Custom AOI** to continue."
    )

# defaults
selected_state = "Custom"
state_id = "00"
selected_county = "AOI"
county_id = "000"
selected_city = None
city_boundary_type = None
custom_aoi_mode = None

if aoi_source == "County (US only)":
    aoi_mode = "County boundary"
    if _census_key_missing() or _census_api_is_down():
        st.sidebar.error(
            "❌ Census API key required. Enter your key in the "
            "**🗝️ Census API Key** panel above, or switch to Custom AOI."
        )
        counties = {}
    else:
        selected_state = st.sidebar.selectbox("Select State", list(states.keys()))
        state_id = states[selected_state]
        counties = _fetch_counties_from_census(state_id)
        if not counties:
            st.sidebar.warning("⚠️ Could not load counties. Census API may be temporarily down.")
        else:
            selected_county = st.sidebar.selectbox("Select County", list(counties.keys()))
            county_id = counties[selected_county]

elif aoi_source == "City (US only)":
    aoi_mode = "Draw AOI"  # city AOI will be provided via custom_aoi_geojson under the hood
    if _census_key_missing() or _census_api_is_down():
        st.sidebar.error(
            "❌ Census API key required. Enter your key in the "
            "**🗝️ Census API Key** panel above, or switch to Custom AOI."
        )
        cities = []
    else:
        selected_state = st.sidebar.selectbox("Select State", list(states.keys()))
        state_id = states[selected_state]
        cities = load_places_for_state(state_id)
    if cities:
        selected_city = st.sidebar.selectbox("Select City", cities)
    else:
        selected_city = st.sidebar.text_input("City Name")
    city_boundary_type = st.sidebar.radio(
        "City Boundary Type",
        ["Census boundary", "CCA urban cluster (1000 m)"],
        index=0
    )
    # For labelling/export where county name is used, reuse this string
    selected_county = selected_city if selected_city else "CityAOI"
    county_id = "000"

elif aoi_source == "Custom AOI (US / Global)":
    aoi_mode = "Draw AOI"
    selected_state, selected_county, state_id, county_id = "Custom", "AOI", "00", "000"
    custom_aoi_mode = st.sidebar.radio(
        "Custom AOI Type",
        ["Draw on map", "Upload shapefile"],
        index=0
    )

# ════════════════════════════════════════════════════════
# ①  DATA SOURCE
# ════════════════════════════════════════════════════════
st.sidebar.subheader("📡 Data Source")
source = st.sidebar.radio(
    "Sensor platform",
    ["Landsat (30 m)", "MODIS (1 km)"],
    index=0,
    help="Landsat gives 30 m spatial resolution (US-focused). MODIS gives 1 km with global coverage."
)

# ════════════════════════════════════════════════════════
# ②  TIME PERIOD
# ════════════════════════════════════════════════════════
st.sidebar.subheader("⏱ Time Period")
LANDSAT_START = 1984
MODIS_START   = 2000
current_year  = datetime.now().year
min_year = MODIS_START if source.startswith("MODIS") else LANDSAT_START

start_year = st.sidebar.slider("Start Year", min_year, current_year, min_year + 10)
end_year   = st.sidebar.slider("End Year",   min_year, current_year, current_year)
st.sidebar.caption(f"Data available: {min_year}–{current_year}")

# ════════════════════════════════════════════════════════
# ③  SENSOR SETTINGS  (Landsat only)
# ════════════════════════════════════════════════════════
if source.startswith("Landsat"):
    with st.sidebar.expander("🛰 Landsat Sensor Settings", expanded=False):
        landsat_sensor_recommended = st.checkbox(
            "Use recommended sensors",
            value=True,
            key="ls_sensor_rec",
            help=(
                "Recommended: L5 TM (1984–2012) → L8/9 OLI (2013+). "
                "The app picks the best available sensor per year automatically."
            )
        )
        if not landsat_sensor_recommended:
            _ALL_SENSORS = [
                "Landsat 5 TM (1984–2012)",
                "Landsat 7 ETM+ (1999–2022)",
                "Landsat 8 OLI (2013–present)",
                "Landsat 9 OLI (2021–present)",
            ]
            selected_sensors = st.multiselect(
                "Active sensors",
                options=_ALL_SENSORS,
                default=["Landsat 5 TM (1984–2012)", "Landsat 8 OLI (2013–present)", "Landsat 9 OLI (2021–present)"],
                key="ls_sensors",
                help="Years outside a sensor's valid range are silently skipped."
            )
            if not selected_sensors:
                st.warning("⚠️ Select at least one sensor.")
                selected_sensors = _ALL_SENSORS
            st.caption("⚠️ Landsat 7 ETM+ has scan-line corrector (SLC) failure after May 2003, causing striped data gaps.")
        else:
            selected_sensors = [
                "Landsat 5 TM (1984–2012)",
                "Landsat 8 OLI (2013–present)",
                "Landsat 9 OLI (2021–present)",
            ]
else:
    landsat_sensor_recommended = True
    selected_sensors = []

# ════════════════════════════════════════════════════════
# ④  MONTHS
# ════════════════════════════════════════════════════════
st.sidebar.subheader("📅 Months")

# ════════════════════════════════════════════════════════
# ⑤  LAND COVER SOURCE  (MODIS only — Landsat always uses NLCD)
# ════════════════════════════════════════════════════════

# ── Class lookup tables ──────────────────────────────────────────────────
_NLCD_CLASS_OPTIONS = {
    "Open Water (11)": 11,
    "Perennial Ice/Snow (12)": 12,
    "Developed Open Space (21)": 21,
    "Developed Low Intensity (22)": 22,
    "Developed Medium Intensity (23)": 23,
    "Developed High Intensity (24)": 24,
    "Barren Land (31)": 31,
    "Deciduous Forest (41)": 41,
    "Evergreen Forest (42)": 42,
    "Mixed Forest (43)": 43,
    "Shrub/Scrub (52)": 52,
    "Grassland/Herbaceous (71)": 71,
    "Pasture/Hay (81)": 81,
    "Cultivated Crops (82)": 82,
    "Woody Wetlands (90)": 90,
    "Emergent Wetlands (95)": 95,
}

# IGBP classes used by MCD12Q1 (Type 1)
_MCD12Q1_CLASS_OPTIONS = {
    "Evergreen Needleleaf Forests (1)": 1,
    "Evergreen Broadleaf Forests (2)": 2,
    "Deciduous Needleleaf Forests (3)": 3,
    "Deciduous Broadleaf Forests (4)": 4,
    "Mixed Forests (5)": 5,
    "Closed Shrublands (6)": 6,
    "Open Shrublands (7)": 7,
    "Woody Savannas (8)": 8,
    "Savannas (9)": 9,
    "Grasslands (10)": 10,
    "Permanent Wetlands (11)": 11,
    "Croplands (12)": 12,
    "Urban and Built-up Lands (13)": 13,
    "Cropland/Natural Vegetation Mosaics (14)": 14,
    "Snow and Ice (15)": 15,
    "Barren (16)": 16,
    "Water Bodies (17)": 17,
}

# Recommended defaults
_NLCD_DEFAULT_URBAN = ["Developed Low Intensity (22)", "Developed Medium Intensity (23)", "Developed High Intensity (24)"]
_NLCD_DEFAULT_VEG   = ["Deciduous Forest (41)", "Evergreen Forest (42)", "Mixed Forest (43)",
                        "Shrub/Scrub (52)", "Grassland/Herbaceous (71)", "Developed Open Space (21)"]
_MCD_DEFAULT_URBAN  = ["Urban and Built-up Lands (13)"]
_MCD_DEFAULT_VEG    = ["Evergreen Needleleaf Forests (1)", "Evergreen Broadleaf Forests (2)",
                        "Deciduous Needleleaf Forests (3)", "Deciduous Broadleaf Forests (4)",
                        "Mixed Forests (5)", "Closed Shrublands (6)", "Open Shrublands (7)",
                        "Woody Savannas (8)", "Savannas (9)", "Grasslands (10)"]

# Determine active LC source
if source.startswith("MODIS"):
    with st.sidebar.expander("🗺 Land Cover Source", expanded=True):
        lc_source = st.radio(
            "Land cover dataset",
            ["NLCD (30 m, US only)", "MODIS MCD12Q1 (500 m, global, annual)"],
            index=0,
            key="lc_source_radio",
            help=(
                "NLCD: ~biennial, US only, 30 m — nearest-year snapping applied.\n"
                "MCD12Q1: annual 2001–present, global, 500 m IGBP classification — "
                "better spatial match for MODIS LST and works outside the US."
            )
        )
        use_mcd12q1 = lc_source.startswith("MODIS")
        if use_mcd12q1:
            st.caption("🌍 Global coverage · Annual · IGBP classes · 500 m")
        else:
            st.caption("🇺🇸 US only · Biennial · NLCD classes · 30 m")
else:
    use_mcd12q1 = False   # Landsat always uses NLCD
    lc_source   = "NLCD (30 m, US only)"

# ════════════════════════════════════════════════════════
# ⑥  URBAN & VEGETATIVE REFERENCE
# ════════════════════════════════════════════════════════
_active_class_opts = _MCD12Q1_CLASS_OPTIONS if use_mcd12q1 else _NLCD_CLASS_OPTIONS
_active_default_urban = _MCD_DEFAULT_URBAN  if use_mcd12q1 else _NLCD_DEFAULT_URBAN
_active_default_veg   = _MCD_DEFAULT_VEG   if use_mcd12q1 else _NLCD_DEFAULT_VEG
_lc_label = "IGBP (MCD12Q1)" if use_mcd12q1 else "NLCD"

_rec_help = (
    f"Recommended urban ({_lc_label}): {'Urban/Built-up (13)' if use_mcd12q1 else 'Developed Low/Med/High (22–24)'}.\n"
    f"Recommended vegetative ({_lc_label}): {'forests, shrublands, savannas, grasslands' if use_mcd12q1 else 'Forest (41–43), Shrub (52), Grass (71), Developed Open (21) — excludes Water & Cropland'}."
)

with st.sidebar.expander("🏙 Urban & Vegetative Reference", expanded=False):
    lulc_ref_mode = st.checkbox(
        "Use recommended settings",
        value=True,
        key="lulc_ref_mode",
        help=_rec_help
    )

    if lulc_ref_mode:
        st.caption(
            f"**Urban:** {', '.join(_active_default_urban)}\n\n"
            f"**Vegetative:** {', '.join(_active_default_veg[:3])}… *(recommended)*"
        )
        custom_urban_codes = []  # → recommended
        custom_veg_codes   = []  # → recommended
    else:
        st.markdown(f"**Urban classes** *({_lc_label}) — hot side of UHI*")
        custom_urban_labels = st.multiselect(
            "Urban classes",
            options=list(_active_class_opts.keys()),
            default=[l for l in _active_default_urban if l in _active_class_opts],
            key="custom_urban",
            help="Classes treated as the urban (warm) surface. UHI = Urban LST − Vegetative LST."
        )
        custom_urban_codes = [_active_class_opts[l] for l in custom_urban_labels]
        if not custom_urban_codes:
            st.warning("⚠️ Select at least one urban class.")
            custom_urban_codes = list(_active_class_opts[l] for l in _active_default_urban)

        st.markdown(f"**Vegetative classes** *({_lc_label}) — cool background*")
        custom_veg_labels = st.multiselect(
            "Vegetative classes",
            options=list(_active_class_opts.keys()),
            default=[l for l in _active_default_veg if l in _active_class_opts],
            key="custom_veg",
            help="Classes treated as the vegetative (cool) reference baseline."
        )
        custom_veg_codes = [_active_class_opts[l] for l in custom_veg_labels]
        if not custom_veg_codes:
            st.warning("⚠️ Select at least one vegetative class.")
            custom_veg_codes = list(_active_class_opts[l] for l in _active_default_veg)

        overlap = set(custom_urban_codes) & set(custom_veg_codes)
        if overlap:
            st.warning(f"⚠️ Classes appear in both urban and vegetative lists — UHI will be biased.")

# Seasonal presets
season_mode = st.sidebar.radio("Selection mode", ["Custom months", "Season (preset)"], index=1)
season_choice = None
if season_mode == "Season (preset)":
    season_choice = st.sidebar.selectbox("Season", ["DJF (Dec–Feb)", "MAM (Mar–May)", "JJA (Jun–Aug)", "SON (Sep–Nov)"], index=2)
    if season_choice.startswith("DJF"):
        selected_months = ['12-Dec','01-Jan','02-Feb']
    elif season_choice.startswith("MAM"):
        selected_months = ['03-Mar','04-Apr','05-May']
    elif season_choice.startswith("JJA"):
        selected_months = ['06-Jun','07-Jul','08-Aug']
    else:
        selected_months = ['09-Sep','10-Oct','11-Nov']
else:
    month_options   = ['01-Jan','02-Feb','03-Mar','04-Apr','05-May','06-Jun','07-Jul','08-Aug','09-Sep','10-Oct','11-Nov','12-Dec']
    selected_months = st.sidebar.multiselect("Months to consider", month_options, default=['06-Jun','07-Jul','08-Aug'])

@st.cache_data(show_spinner=False)
def load_city_aoi_from_census(state_fips: str, city_name: str):
    """
    Load a specific city boundary from Census Tiger/Line 2023 Places.
    Returns: (aoi_ee, gdf_ll, epsg)
    """
    import requests, geopandas as gpd, zipfile, tempfile, os, io
    from shapely.geometry import shape as shp_shape
    import geemap

    url = f"https://www2.census.gov/geo/tiger/TIGER2023/PLACE/tl_2023_{state_fips.zfill(2)}_place.zip"
    
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Could not download Census data: {e}")

    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                shp = [f for f in os.listdir(tmp) if f.endswith(".shp")][0]
                gdf = gpd.read_file(os.path.join(tmp, shp))
    except Exception as e:
        raise RuntimeError(f"Could not parse shapefile: {e}")

    # Filter by city name
    gdf_sel = gdf[gdf["NAME"] == city_name]
    
    if gdf_sel.empty:
        raise RuntimeError(f"City '{city_name}' not found in Census 2023 Places for this state.")

    # Convert to WGS84
    gdf_ll = gdf_sel.to_crs(epsg=4326)

    # Calculate UTM zone for projection
    poly = gdf_ll.geometry.iloc[0]
    lon, lat = poly.centroid.x, poly.centroid.y
    zone = int(((lon + 180) / 6) % 60) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    
    # Project to UTM
    gdf_proj = gdf_ll.to_crs(epsg=epsg)

    # Convert to Earth Engine FeatureCollection
    aoi_ee = geemap.geopandas_to_ee(gdf_proj)

    return aoi_ee, gdf_ll, epsg

# ----------------------------
# AOI builders / previews
# ----------------------------
@st.cache_data(show_spinner=False)
def load_county_aoi(state_id: str, county_id: str):
    sid = str(state_id).zfill(2)
    cid = str(county_id).zfill(3)
    url = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_5m.zip"
    with zipfile.ZipFile(io.BytesIO(requests.get(url).content)) as z:
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            shp = [f for f in os.listdir(tmp) if f.endswith('.shp')][0]
            gdf = gpd.read_file(os.path.join(tmp, shp))
            gdf = gdf[(gdf["STATEFP"] == sid) & (gdf["COUNTYFP"] == cid)]
            if gdf.empty:
                raise RuntimeError("County not found in shapefile")
            gdf_ll = gdf.to_crs(epsg=4326)
            lon = gdf_ll.geometry.centroid.x.mean()
            utm_zone = int(((lon + 180) / 6) % 60) + 1
            epsg = 32600 + utm_zone if gdf_ll.geometry.centroid.y.mean() >= 0 else 32700 + utm_zone
            gdf_proj = gdf_ll.to_crs(epsg=epsg)
            aoi_ee = geemap.geopandas_to_ee(gdf_proj)
    return aoi_ee, gdf_ll, epsg

def get_aoi_center_latlon(aoi_fc: ee.FeatureCollection):
    try:
        lon, lat = aoi_fc.geometry().centroid().coordinates().getInfo()
        return [lat, lon]
    except Exception:
        return [39.0, -98.0]

def build_draw_aoi_ui():
    st.subheader("Draw an AOI (polygon) on the map")

    # US basemap
    m = folium.Map(location=[39.0, -98.0], zoom_start=4,
                   tiles='cartodbpositron', control_scale=True)
    folium.TileLayer('openstreetmap', name='OpenStreetMap').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='&copy; Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community',
        name='Esri World Imagery', overlay=False, control=True
    ).add_to(m)
    folium.TileLayer('cartodbdark_matter', name='CartoDB Dark Matter').add_to(m)

    Fullscreen().add_to(m)
    MousePosition(position='bottomright', separator=' | ', empty_string='NaN', prefix='Lat/Lng:').add_to(m)
    Geocoder(collapsed=False, position='topleft', add_marker=True).add_to(m)

    Draw(
        export=False, position='topleft',
        draw_options={
            'polyline': False, 'rectangle': False, 'circle': False,
            'marker': False, 'circlemarker': False,
            'polygon': {'allowIntersection': False, 'showArea': True}
        },
        edit_options={'edit': True, 'remove': True}
    ).add_to(m)

    folium.LayerControl().add_to(m)

    ret = st_folium(
        m, height=460, width=None,
        returned_objects=['last_active_drawing', 'last_draw', 'last_object', 'all_drawings']
    )

    # Auto-capture the most recent polygon; store as GeoJSON (not EE object)
    geom = None
    for k in ('last_active_drawing', 'last_draw', 'last_object'):
        if ret and ret.get(k) and isinstance(ret[k], dict):
            g = ret[k].get('geometry')
            if g: geom = g; break
    if geom is None and ret and ret.get('all_drawings'):
        for item in reversed(ret['all_drawings']):
            if isinstance(item, dict):
                g = item.get('geometry', {})
                if g and g.get('type') in ('Polygon', 'MultiPolygon'):
                    geom = g
                    break

    if geom:
        st.session_state['custom_aoi_geojson'] = geom
        st.info("AOI polygon captured ✓  (Click **Run Analysis**.)")

    return st.session_state.get('custom_aoi_geojson', None)

def show_county_preview_map(state_id: str, county_id: str):
    """Always-visible basemap when County mode is selected."""
    try:
        _, gdf_ll, _ = load_county_aoi(state_id, county_id)
    except Exception:
        st.warning("Could not load county geometry for preview.")
        return
    center = [gdf_ll.geometry.centroid.y.mean(), gdf_ll.geometry.centroid.x.mean()]
    m = folium.Map(location=center, zoom_start=9, tiles='cartodbpositron', control_scale=True)
    folium.GeoJson(
        gdf_ll.__geo_interface__,
        name="County boundary",
        style_function=lambda _: {'color': '#00AEEF', 'weight': 3, 'fillOpacity': 0.05}
    ).add_to(m)
    Fullscreen().add_to(m)
    Geocoder(collapsed=True, position='topleft', add_marker=False).add_to(m)
    folium.LayerControl().add_to(m)
    st_folium(m, height=420, width=None)

def load_shapefile_from_zip(zip_bytes):
    """Read a zipped ESRI Shapefile and return (GeoDataFrame in EPSG:4326, union geometry GeoJSON)."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            shp_files = [f for f in z.namelist() if f.endswith('.shp')]
            if not shp_files:
                st.error("Uploaded ZIP does not contain a .shp file.")
                return None, None
            with tempfile.TemporaryDirectory() as tmpdir:
                z.extractall(tmpdir)
                shp_path = None
                for root, dirs, files in os.walk(tmpdir):
                    for f in files:
                        if f.endswith('.shp'):
                            shp_path = os.path.join(root, f)
                            break
                    if shp_path:
                        break
                if shp_path is None:
                    st.error("Could not find shapefile after extraction.")
                    return None, None
                gdf = gpd.read_file(shp_path)
                if gdf.empty:
                    st.error("Shapefile has no features.")
                    return None, None
                gdf_ll = gdf.to_crs(epsg=4326)
                geom_union = gdf_ll.unary_union
                gj = geom_union.__geo_interface__
                return gdf_ll, gj
    except Exception as e:
        st.error(f"Failed to read shapefile: {e}")
        return None, None

# ----------------------------
# NLCD helpers + colorful style
# ----------------------------
def get_best_nlcd_for_year(year: int):
    yrs = [2001, 2004, 2006, 2008, 2011, 2013, 2016, 2019, 2021]
    target = min(yrs, key=lambda y: abs(y - year))
    if target <= 2019:
        nlcd = ee.ImageCollection("USGS/NLCD_RELEASES/2019_REL/NLCD").filter(
            ee.Filter.eq('system:index', str(target))
        ).first().select('landcover')
    else:
        try:
            nlcd = ee.ImageCollection("USGS/NLCD_RELEASES/2021_REL/NLCD").filter(
                ee.Filter.eq('system:index', '2021')
            ).first().select('landcover')
        except Exception:
            nlcd = ee.ImageCollection("USGS/NLCD_RELEASES/2019_REL/NLCD").filter(
                ee.Filter.eq('system:index', '2019')
            ).first().select('landcover')
            target = 2019
    return nlcd, target

def nlcd_masks(nlcd_img: ee.Image, custom_veg_codes: list | None = None, custom_urban_codes: list | None = None):
    """
    Returns (urban_mask, veg_mask).

    Recommended (no custom codes):
        Urban  = 22–24 (Developed Low/Medium/High)
        Veg    = 41–43, 52, 71, 21 — excludes Water & Cropland
    Custom codes override the relevant mask independently.
    """
    # Urban mask
    if custom_urban_codes:
        urban = nlcd_img.eq(custom_urban_codes[0])
        for code in custom_urban_codes[1:]:
            urban = urban.Or(nlcd_img.eq(code))
    else:
        urban = nlcd_img.gte(22).And(nlcd_img.lte(24))

    # Vegetative mask
    if custom_veg_codes:
        veg = nlcd_img.eq(custom_veg_codes[0])
        for code in custom_veg_codes[1:]:
            veg = veg.Or(nlcd_img.eq(code))
    else:
        forest = nlcd_img.gte(41).And(nlcd_img.lte(43))
        shrub  = nlcd_img.eq(52)
        grass  = nlcd_img.eq(71)
        open_s = nlcd_img.eq(21)
        veg = forest.Or(shrub).Or(grass).Or(open_s)

    return urban, veg

def nlcd_styled_and_legend(nlcd_img: ee.Image):
    """Create a colorful categorical NLCD layer + legend."""
    classes = [11,21,22,23,24,31,41,42,43,52,71,81,82,90,95]
    palette = [
        '#466b9f', '#dec5c5', '#d99282', '#eb0000', '#ab0000',
        '#b3ac9f', '#68ab5f', '#1c5f2c', '#b5ca8f', '#ccba7c',
        '#e2e2c1', '#c9d29b', '#9c9c00', '#a4d3f5', '#a5fbd1'
    ]
    legend_dict = {
        'Open Water (11)':'#466b9f','Dev. Open Space (21)':'#dec5c5','Developed Low (22)':'#d99282',
        'Developed Medium (23)':'#eb0000','Developed High (24)':'#ab0000','Barren (31)':'#b3ac9f',
        'Deciduous Forest (41)':'#68ab5f','Evergreen Forest (42)':'#1c5f2c','Mixed Forest (43)':'#b5ca8f',
        'Shrub/Scrub (52)':'#ccba7c','Grass/Herb (71)':'#e2e2c1','Pasture/Hay (81)':'#c9d29b',
        'Cultivated (82)':'#9c9c00','Woody Wetlands (90)':'#a4d3f5','Emergent Wetlands (95)':'#a5fbd1'
    }
    remapped = nlcd_img.remap(classes, list(range(1, len(classes)+1)))
    styled = remapped.visualize(min=1, max=len(classes), palette=palette)
    return styled, legend_dict

def landcover_percentages(aoi_geom, nlcd_img, custom_veg_codes=None, custom_urban_codes=None):
    area_img = ee.Image.pixelArea().rename('area')
    urban_mask, veg_mask = nlcd_masks(nlcd_img, custom_veg_codes, custom_urban_codes)
    total_area = area_img.clip(aoi_geom).reduceRegion(
        ee.Reducer.sum(), aoi_geom, 30, maxPixels=1e9, bestEffort=True
    ).get('area')
    urban_area = area_img.updateMask(urban_mask).reduceRegion(
        ee.Reducer.sum(), aoi_geom, 30, maxPixels=1e9, bestEffort=True
    ).get('area')
    veg_area = area_img.updateMask(veg_mask).reduceRegion(
        ee.Reducer.sum(), aoi_geom, 30, maxPixels=1e9, bestEffort=True
    ).get('area')
    try:
        tot = float(ee.Number(total_area).getInfo() or 0.0)
        u   = float(ee.Number(urban_area).getInfo() or 0.0)
        v   = float(ee.Number(veg_area).getInfo() or 0.0)
        if tot <= 0: return 0.0, 0.0, 0.0
        up = (u / tot) * 100.0
        vp = (v / tot) * 100.0
        op = max(0.0, 100.0 - up - vp)
        return up, vp, op
    except Exception:
        return 0.0, 0.0, 0.0

# ----------------------------
# MCD12Q1 (MODIS Land Cover) helpers — 500 m, annual, global, IGBP Type 1
# ----------------------------
def get_mcd12q1_for_year(year: int):
    """
    Fetch MODIS MCD12Q1 annual land cover (IGBP Type 1) for the given year.
    Available 2001–present. Years before 2001 fall back to 2001.
    Returns (ee.Image with 'LC_Type1' band, actual_year).
    """
    actual_year = max(2001, min(year, 2023))  # clamp to available range
    img = (
        ee.ImageCollection("MODIS/061/MCD12Q1")
        .filter(ee.Filter.calendarRange(actual_year, actual_year, 'year'))
        .first()
        .select('LC_Type1')
    )
    return img, actual_year

def mcd12q1_masks(lc_img: ee.Image, custom_veg_codes: list | None = None, custom_urban_codes: list | None = None):
    """
    Build urban and vegetative masks from MCD12Q1 IGBP Type 1 classes.

    Recommended defaults (IGBP):
        Urban  = 13 (Urban and Built-up Lands)
        Veg    = 1–10 (all forest/shrub/savanna/grassland types)
                 excludes Croplands (12), Wetlands (11), Water (17), Snow (15), Barren (16)
    Custom codes override the relevant mask independently.
    """
    if custom_urban_codes:
        urban = lc_img.eq(custom_urban_codes[0])
        for code in custom_urban_codes[1:]:
            urban = urban.Or(lc_img.eq(code))
    else:
        urban = lc_img.eq(13)  # Urban and Built-up

    if custom_veg_codes:
        veg = lc_img.eq(custom_veg_codes[0])
        for code in custom_veg_codes[1:]:
            veg = veg.Or(lc_img.eq(code))
    else:
        # IGBP classes 1–10: all forests, shrublands, savannas, grasslands
        veg = lc_img.gte(1).And(lc_img.lte(10))

    return urban, veg

def landcover_percentages_mcd(aoi_geom, lc_img: ee.Image, custom_veg_codes=None, custom_urban_codes=None):
    """Compute urban/veg/other percentages using MCD12Q1 (500 m pixels)."""
    area_img = ee.Image.pixelArea().rename('area')
    urban_mask, veg_mask = mcd12q1_masks(lc_img, custom_veg_codes, custom_urban_codes)
    scale = 500  # MCD12Q1 native resolution
    total_area = area_img.clip(aoi_geom).reduceRegion(
        ee.Reducer.sum(), aoi_geom, scale, maxPixels=1e9, bestEffort=True
    ).get('area')
    urban_area = area_img.updateMask(urban_mask).reduceRegion(
        ee.Reducer.sum(), aoi_geom, scale, maxPixels=1e9, bestEffort=True
    ).get('area')
    veg_area = area_img.updateMask(veg_mask).reduceRegion(
        ee.Reducer.sum(), aoi_geom, scale, maxPixels=1e9, bestEffort=True
    ).get('area')
    try:
        tot = float(ee.Number(total_area).getInfo() or 0.0)
        u   = float(ee.Number(urban_area).getInfo() or 0.0)
        v   = float(ee.Number(veg_area).getInfo() or 0.0)
        if tot <= 0: return 0.0, 0.0, 0.0
        up = (u / tot) * 100.0
        vp = (v / tot) * 100.0
        op = max(0.0, 100.0 - up - vp)
        return up, vp, op
    except Exception:
        return 0.0, 0.0, 0.0

def mcd12q1_styled_and_legend(lc_img: ee.Image):
    """Colorful IGBP styled layer + legend dict for map display."""
    classes = list(range(1, 18))
    palette = [
        '#05450a','#086a10','#54a708','#78d203','#009900',
        '#c6b044','#dcd159','#dade48','#fbff13','#b6ff05',
        '#27ff87','#c24f44','#a5a5a5','#ff6d4c','#69fff8',
        '#f9ffa4','#1c0dff'
    ]
    legend_dict = {
        'Evergreen Needleleaf Forest':'#05450a','Evergreen Broadleaf Forest':'#086a10',
        'Deciduous Needleleaf Forest':'#54a708','Deciduous Broadleaf Forest':'#78d203',
        'Mixed Forest':'#009900','Closed Shrublands':'#c6b044','Open Shrublands':'#dcd159',
        'Woody Savannas':'#dade48','Savannas':'#fbff13','Grasslands':'#b6ff05',
        'Permanent Wetlands':'#27ff87','Croplands':'#c24f44','Urban/Built-up':'#a5a5a5',
        'Cropland/Veg Mosaic':'#ff6d4c','Snow and Ice':'#69fff8',
        'Barren':'#f9ffa4','Water Bodies':'#1c0dff'
    }
    remapped = lc_img.remap(classes, list(range(1, len(classes)+1)))
    styled = remapped.visualize(min=1, max=len(classes), palette=palette)
    return styled, legend_dict

# ----------------------------
# NEW: NLCD urban, CCA, and buffer helpers
# ----------------------------
def load_nlcd_urban():
    """NLCD 2019 urban mask (22–24)."""
    nlcd2019 = ee.ImageCollection("USGS/NLCD_RELEASES/2019_REL/NLCD").filter(
        ee.Filter.eq('system:index', '2019')
    ).first().select('landcover')
    urban = nlcd2019.gte(22).And(nlcd2019.lte(24))
    return urban

def compute_urban_area_km2(aoi_geom: ee.Geometry):
    """Compute total urban area (km²) inside a geometry, using NLCD 2019."""
    try:
        urban = load_nlcd_urban()
        area_img = ee.Image.pixelArea().rename('area').updateMask(urban)
        stats = area_img.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=aoi_geom,
            scale=30,
            maxPixels=1e9,
            bestEffort=True
        )
        area_m2 = ee.Number(stats.get('area')).getInfo()
        if area_m2 is None:
            return 0.0
        return float(area_m2) / 1e6  # m² → km²
    except Exception:
        return 0.0

def classify_city_and_buffer(urban_area_km2: float):
    """
    Returns (recommended_buffer_km, category_name)
    """
    if urban_area_km2 < 150:
        return 5.0, "small city"
    elif urban_area_km2 < 500:
        return 10.0, "mid-size city"
    else:
        return 15.0, "large city"

def run_cca(city_geom: ee.Geometry, d_m: int = 1000) -> ee.FeatureCollection:
    """
    Contiguous Urban Area clustering via morphological dilation + connected components.
    
    Steps:
      1. Load NLCD urban pixels (22–24) clipped to city + 5 km buffer
      2. Dilate by d_m (default 1000 m) to bridge small gaps
      3. Find connected components (labels)
      4. Vectorize to polygon clusters
      5. Filter out tiny noise patches (< 0.5 km² area)
    """
    urban = load_nlcd_urban().clip(city_geom.buffer(5000))

    radius_px = max(1, int(d_m / 30))
    kernel = ee.Kernel.circle(radius=radius_px, units='pixels')

    dilated = urban.focal_max(kernel=kernel)

    labeled = dilated.selfMask().connectedComponents(
        connectedness=ee.Kernel.square(1),
        maxSize=1024
    )

    vectors = labeled.select('labels').reduceToVectors(
        geometry=city_geom.buffer(5000),
        scale=90,          # coarser scale speeds up vectorization; 90 m is fine for cluster outlines
        geometryType='polygon',
        labelProperty='cluster',
        bestEffort=True,
        maxPixels=1e13
    )

    # Filter out tiny spurious clusters (< 0.5 km² ≈ 500 000 m²)
    vectors_with_area = vectors.map(
        lambda f: f.set('area_m2', f.geometry().area(maxError=10))
    )
    vectors_filtered = vectors_with_area.filter(ee.Filter.gt('area_m2', 500000))

    return vectors_filtered


def pick_nearest_cluster(cca_fc: ee.FeatureCollection, city_geom: ee.Geometry) -> ee.Feature:
    """
    Pick the CCA polygon whose CENTROID is closest to the city centroid.
    Using centroid–centroid distance is more robust than edge distance for
    irregular polygons and avoids selecting a large adjacent cluster that merely
    touches the city boundary.
    """
    city_centroid = city_geom.centroid(maxError=1)

    def _with_centroid_dist(feat):
        feat_centroid = feat.geometry().centroid(maxError=1)
        dist = feat_centroid.distance(city_centroid, maxError=1)
        return feat.set('centroid_dist', dist)

    cca_with_dist = cca_fc.map(_with_centroid_dist)

    count = cca_with_dist.size().getInfo()
    if count == 0:
        raise RuntimeError(
            "No urban clusters found after CCA. The city may lack NLCD-classified urban pixels "
            "or the dilation distance is too small. Try increasing d_m or switching to Census boundary."
        )

    return ee.Feature(cca_with_dist.sort('centroid_dist').first())

# ----------------------------
# Cloud masking & scale factors (Landsat)
# ----------------------------
def _qa_mask(image):
    qa = image.select('QA_PIXEL')
    cloud  = qa.bitwiseAnd(1 << 5).eq(0)
    shadow = qa.bitwiseAnd(1 << 3).eq(0)
    dil    = qa.bitwiseAnd(1 << 1).eq(0)
    return image.updateMask(cloud.And(shadow).And(dil))

cloud_mask_landsat8 = _qa_mask
cloud_mask_landsat5 = _qa_mask

def apply_scale_factors(image, sensor: str):
    """
    Apply Collection-2 Level-2 scale factors.
    sensor: 'L5', 'L7', 'L8', 'L9'
    """
    if sensor in ('L5', 'L7'):
        optical = image.select(['SR_B1','SR_B2','SR_B3','SR_B4','SR_B5','SR_B7']).multiply(0.0000275).add(-0.2)
        thermal = image.select(['ST_B6']).multiply(0.00341802).add(149.0)
    else:  # L8, L9
        optical = image.select(['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','SR_B7']).multiply(0.0000275).add(-0.2)
        thermal = image.select(['ST_B10']).multiply(0.00341802).add(149.0)
    return image.addBands(optical, overwrite=True).addBands(thermal, overwrite=True)

# ----------------------------
# Percentile filter
# ----------------------------
def filter_lst_percentiles(lst_image, aoi):
    try:
        percentiles = lst_image.reduceRegion(
            reducer=ee.Reducer.percentile([5, 95]),
            geometry=aoi.geometry(),
            scale=30, maxPixels=1e9, bestEffort=True
        )
        p05 = ee.Number(percentiles.get('LST_p5'))
        p95 = ee.Number(percentiles.get('LST_p95'))
        mask = lst_image.gte(p05).And(lst_image.lte(p95))
        return lst_image.updateMask(mask), p05.getInfo(), p95.getInfo()
    except Exception as e:
        st.warning(f"Could not filter LST by percentiles: {e}")
        return lst_image, None, None

# ----------------------------
# Landsat pipeline
# ----------------------------
def process_landsat_data(year, aoi, months, custom_veg_codes=None, custom_urban_codes=None, selected_sensors=None):
    """
    Process Landsat data for a given year using all applicable sensors.
    Sensor coverage:
      Landsat 5 TM  : 1984–2012 (LANDSAT/LT05/C02/T1_L2)
      Landsat 7 ETM+: 1999–2022 (LANDSAT/LE07/C02/T1_L2) — SLC-off after 2003, use with caution
      Landsat 8 OLI : 2013–present (LANDSAT/LC08/C02/T1_L2)
      Landsat 9 OLI : 2021–present (LANDSAT/LC09/C02/T1_L2)
    """
    if selected_sensors is None:
        # Default recommended: L5 for 1984–2012, L8/9 for 2013+
        selected_sensors = ["Landsat 5 TM (1984–2012)", "Landsat 8 OLI (2013–present)", "Landsat 9 OLI (2021–present)"]

    # Resolve which EE collections and band configs to use for this year
    # Each entry: (ee_collection_id, sensor_code, year_min, year_max)
    SENSOR_REGISTRY = [
        ("Landsat 5 TM (1984–2012)",      "LANDSAT/LT05/C02/T1_L2", "L5", 1984, 2012),
        ("Landsat 7 ETM+ (1999–2022)",    "LANDSAT/LE07/C02/T1_L2", "L7", 1999, 2022),
        ("Landsat 8 OLI (2013–present)",  "LANDSAT/LC08/C02/T1_L2", "L8", 2013, 2099),
        ("Landsat 9 OLI (2021–present)",  "LANDSAT/LC09/C02/T1_L2", "L9", 2021, 2099),
    ]

    # Band configs per sensor group
    def _band_config(sensor_code):
        if sensor_code in ('L5', 'L7'):
            return {
                'thermal_band': 'ST_B6',
                'ndvi_bands':   ['SR_B4', 'SR_B3'],
                'ndmi_bands':   ['SR_B4', 'SR_B5'],
                'ndbi_bands':   ['SR_B5', 'SR_B4'],
            }
        else:  # L8, L9
            return {
                'thermal_band': 'ST_B10',
                'ndvi_bands':   ['SR_B5', 'SR_B4'],
                'ndmi_bands':   ['SR_B5', 'SR_B6'],
                'ndbi_bands':   ['SR_B6', 'SR_B5'],
            }

    month_numbers = [int(m.split('-')[0]) for m in months]
    monthly = {}
    satellite_labels_used = set()

    for m in month_numbers:
        start = ee.Date.fromYMD(year, m, 1)
        end   = start.advance(1, 'month')

        # Collect images from all selected+applicable sensors, merge them
        merged = None
        sensor_code_for_month = None

        for sensor_label, ee_id, sensor_code, yr_min, yr_max in SENSOR_REGISTRY:
            if sensor_label not in selected_sensors:
                continue
            if not (yr_min <= year <= yr_max):
                continue

            cfg = _band_config(sensor_code)
            col = (ee.ImageCollection(ee_id)
                   .filterDate(start, end)
                   .filterBounds(aoi.geometry())
                   .map(lambda img, sc=sensor_code: apply_scale_factors(img, sc))
                   .map(_qa_mask))

            if merged is None:
                merged = col
                sensor_code_for_month = sensor_code  # use config of first sensor found
            else:
                # Merging different sensor families only works when bands align.
                # L5/L7 and L8/9 have different band layouts; only merge same family.
                if _band_config(sensor_code) == _band_config(sensor_code_for_month):
                    merged = merged.merge(col)
            satellite_labels_used.add(sensor_label.split(" (")[0])

        if merged is None:
            continue

        try:
            if merged.size().getInfo() == 0:
                continue
        except Exception:
            continue

        cfg = _band_config(sensor_code_for_month)
        monthly[m] = {
            'image':        merged.median().clip(aoi.geometry()),
            'thermal_band': cfg['thermal_band'],
            'ndvi_bands':   cfg['ndvi_bands'],
            'ndmi_bands':   cfg['ndmi_bands'],
            'ndbi_bands':   cfg['ndbi_bands'],
        }

    if not monthly:
        st.warning(f"No valid images found for {year} with selected sensors/months.")
        return None

    # Pick hottest month by median LST
    temps = []
    for m, comp in monthly.items():
        try:
            lst_c = comp['image'].select(comp['thermal_band']).subtract(273.15)
            t = lst_c.reduceRegion(ee.Reducer.median(), aoi.geometry(), 30, maxPixels=1e9, bestEffort=True)\
                     .get(comp['thermal_band']).getInfo()
            if t is not None:
                temps.append((t, m))
        except Exception:
            pass

    if not temps:
        st.warning(f"Could not calculate LST for {year}.")
        return None

    _, best_m = max(temps, key=lambda x: x[0])
    comp = monthly[best_m]
    img  = comp['image']

    nlcd, nlcd_year = get_best_nlcd_for_year(year)

    ndvi = img.normalizedDifference(comp['ndvi_bands']).rename('NDVI')
    ndmi = img.normalizedDifference(comp['ndmi_bands']).rename('NDMI')
    ndbi = img.normalizedDifference(comp['ndbi_bands']).rename('NDBI')
    lst  = img.select(comp['thermal_band']).subtract(273.15).rename('LST')

    lst_filtered, _, _ = filter_lst_percentiles(lst, aoi)

    urban_mask, veg_mask = nlcd_masks(nlcd.clip(aoi.geometry()), custom_veg_codes, custom_urban_codes)
    up, vp, op = landcover_percentages(aoi.geometry(), nlcd, custom_veg_codes, custom_urban_codes)

    def mean_from(image, mask=None):
        try:
            if mask is not None:
                image = image.updateMask(mask)
            return image.reduceRegion(ee.Reducer.mean(), aoi.geometry(), 30, maxPixels=1e9, bestEffort=True).getInfo()
        except Exception:
            return {}

    urban_stats = mean_from(lst_filtered, urban_mask)
    veg_stats   = mean_from(lst_filtered, veg_mask)
    mean_stats  = mean_from(lst_filtered)
    ndvi_stats  = mean_from(ndvi)
    ndmi_stats  = mean_from(ndmi)
    ndbi_stats  = mean_from(ndbi)

    urban_mean = urban_stats.get('LST')
    veg_mean   = veg_stats.get('LST')
    uhi_val    = (urban_mean - veg_mean) if (urban_mean is not None and veg_mean is not None) else None

    rural_mean_num = ee.Number(veg_stats.get('LST') if veg_stats.get('LST') is not None else 0.0)
    uhi_img = lst_filtered.updateMask(urban_mask).subtract(ee.Image.constant(rural_mean_num)).rename('UHI')

    sat_label = ' + '.join(sorted(satellite_labels_used)) if satellite_labels_used else (
        'Landsat 5' if year <= 2012 else 'Landsat 8/9'
    )

    return {
        'Year': year,
        'Month': f"{int(best_m):02d}",
        'Image_Date': f"{year}-{int(best_m):02d}-15 (composite)",
        'Urban': urban_mean,
        'Vegetative': veg_mean,
        'Mean_LST': mean_stats.get('LST'),
        'Mean_NDVI': ndvi_stats.get('NDVI'),
        'Mean_NDMI': ndmi_stats.get('NDMI'),
        'Mean_NDBI': ndbi_stats.get('NDBI'),
        'UHI': uhi_val,
        'Urban_Percent': up, 'Vegetative_Percent': vp, 'Other_Percent': op,
        'Satellite': sat_label,
        'NLCD_Year': nlcd_year,
        'EE_Images': {'LST': lst_filtered, 'NDVI': ndvi, 'NDMI': ndmi, 'NDBI': ndbi,
                      'LC': nlcd, 'LC_TYPE': 'NLCD', 'UHI': uhi_img}
    }

# ----------------------------
# MODIS pipelines (Day & Night) – WITH QC filtering (and night uses DAY hottest month)
# ----------------------------
def _scale_mask_modis_lst(img, lst_band: str, qc_band: str):
    qc = img.select(qc_band)
    # Keep Mandatory QA bits (0–1) < 2  → 0=good, 1=other quality; exclude 2/3 (not produced)
    good = qc.bitwiseAnd(3).lt(2)
    return img.select(lst_band).updateMask(good).multiply(0.02).subtract(273.15).rename('LST')

def modis_lst_day_median(year: int, month: int, aoi: ee.FeatureCollection):
    start = ee.Date.fromYMD(year, month, 1); end = start.advance(1, 'month')
    terra = ee.ImageCollection('MODIS/061/MOD11A1').filterDate(start, end)\
        .map(lambda i: _scale_mask_modis_lst(i, 'LST_Day_1km', 'QC_Day'))
    aqua  = ee.ImageCollection('MODIS/061/MYD11A1').filterDate(start, end)\
        .map(lambda i: _scale_mask_modis_lst(i, 'LST_Day_1km', 'QC_Day'))
    return terra.merge(aqua).median().clip(aoi)

def modis_lst_night_median(year: int, month: int, aoi: ee.FeatureCollection):
    start = ee.Date.fromYMD(year, month, 1); end = start.advance(1, 'month')
    terra = ee.ImageCollection('MODIS/061/MOD11A1').filterDate(start, end)\
        .map(lambda i: _scale_mask_modis_lst(i, 'LST_Night_1km', 'QC_Night'))
    aqua  = ee.ImageCollection('MODIS/061/MYD11A1').filterDate(start, end)\
        .map(lambda i: _scale_mask_modis_lst(i, 'LST_Night_1km', 'QC_Night'))
    return terra.merge(aqua).median().clip(aoi)

def modis_indices_median(year: int, month: int, aoi: ee.FeatureCollection):
    start = ee.Date.fromYMD(year, month, 1); end = start.advance(1, 'month')
    sr = (ee.ImageCollection('MODIS/061/MOD09GA')
          .filterDate(start, end).filterBounds(aoi)
          .select(['sur_refl_b01','sur_refl_b02','sur_refl_b06'],
                  ['red',         'nir',          'swir1'])     # ← b06 = SWIR1 (1628–1652 nm) ✓
          .map(lambda img: img.multiply(0.0001)))
    def add_index(img):
        ndvi = img.normalizedDifference(['nir', 'red']).rename('NDVI')
        ndmi = img.normalizedDifference(['nir', 'swir1']).rename('NDMI')   # ← NIR vs SWIR1 ✓
        ndbi = img.normalizedDifference(['swir1', 'nir']).rename('NDBI')   # ← SWIR1 vs NIR ✓
        return ee.Image.cat([ndvi, ndmi, ndbi])
    return sr.map(add_index).median().clip(aoi)

def process_modis_day_and_best_month(year: int, aoi: ee.FeatureCollection, months: list[str], custom_veg_codes=None, custom_urban_codes=None, use_mcd12q1: bool = False):
    """Returns (rec_day, best_month_int, lst_img_for_best_month)."""
    month_numbers = [int(m.split('-')[0]) for m in months]
    temps, lst_by_m = [], {}
    for m in month_numbers:
        lst_img = modis_lst_day_median(year, m, aoi)
        try:
            t = lst_img.reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True)\
                       .get('LST').getInfo()
        except Exception:
            t = None
        if t is not None:
            temps.append((t, m))
            lst_by_m[m] = lst_img
    if not temps:
        return None, None, None

    _, best_m = max(temps, key=lambda x: x[0])
    index_img = modis_indices_median(year, best_m, aoi)
    stats_idx = index_img.reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True).getInfo()
    ndvi = stats_idx.get('NDVI'); ndmi = stats_idx.get('NDMI'); ndbi = stats_idx.get('NDBI')

    # ── Land cover: NLCD or MCD12Q1 ───────────────────────────────────────
    if use_mcd12q1:
        lc_img, lc_year = get_mcd12q1_for_year(year)
        urban_m, veg_m  = mcd12q1_masks(lc_img, custom_veg_codes, custom_urban_codes)
        lc_scale = 500
        lc_label = f"MCD12Q1-{lc_year}"
    else:
        lc_img, lc_year = get_best_nlcd_for_year(year)
        urban_m, veg_m  = nlcd_masks(lc_img, custom_veg_codes, custom_urban_codes)
        lc_scale = 30
        lc_label = f"NLCD-{lc_year}"

    lst_img = lst_by_m[best_m]
    urban_t    = lst_img.updateMask(urban_m).reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()
    rural_t    = lst_img.updateMask(veg_m).reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()
    aoi_mean_t = lst_img.reduceRegion(ee.Reducer.mean(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()

    if (rural_t is None) or (urban_t is None) or (aoi_mean_t is None):
        return None, None, None

    if use_mcd12q1:
        up, vp, op = landcover_percentages_mcd(aoi.geometry(), lc_img, custom_veg_codes, custom_urban_codes)
    else:
        up, vp, op = landcover_percentages(aoi.geometry(), lc_img, custom_veg_codes, custom_urban_codes)

    uhi_img = lst_img.updateMask(urban_m).subtract(ee.Image.constant(rural_t)).rename('UHI')

    rec_day = {
        'Year': year,
        'Month': f"{best_m:02d}",
        'Image_Date': f"{year}-{best_m:02d}-15",
        'Satellite': 'MODIS',
        'LC_Source': lc_label,
        'Urban': round(urban_t, 2),
        'Vegetative': round(rural_t, 2),
        'Mean_LST': round(aoi_mean_t, 2),
        'Mean_NDVI': round(ndvi, 4) if ndvi is not None else None,
        'Mean_NDMI': round(ndmi, 4) if ndmi is not None else None,
        'Mean_NDBI': round(ndbi, 4) if ndbi is not None else None,
        'UHI': round(urban_t - rural_t, 2),
        'Urban_Percent': up, 'Vegetative_Percent': vp, 'Other_Percent': op,
        'NLCD_Year': lc_year,
        'EE_Images': {'LST': lst_img, 'NDVI': index_img.select('NDVI'),
                      'NDMI': index_img.select('NDMI'), 'NDBI': index_img.select('NDBI'),
                      'LC': lc_img, 'LC_TYPE': 'MCD12Q1' if use_mcd12q1 else 'NLCD',
                      'UHI': uhi_img}
    }
    return rec_day, best_m, lst_img

def process_modis_night_for_month(year: int, aoi: ee.FeatureCollection, best_m: int, custom_veg_codes=None, custom_urban_codes=None, use_mcd12q1: bool = False):
    """Nighttime LST computed using the SAME hottest month determined by daytime."""
    if use_mcd12q1:
        lc_img, lc_year = get_mcd12q1_for_year(year)
        urban_m, veg_m  = mcd12q1_masks(lc_img, custom_veg_codes, custom_urban_codes)
    else:
        lc_img, lc_year = get_best_nlcd_for_year(year)
        urban_m, veg_m  = nlcd_masks(lc_img, custom_veg_codes, custom_urban_codes)

    lst_img_n  = modis_lst_night_median(year, best_m, aoi)
    urban_t    = lst_img_n.updateMask(urban_m).reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()
    rural_t    = lst_img_n.updateMask(veg_m).reduceRegion(ee.Reducer.median(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()
    aoi_mean_t = lst_img_n.reduceRegion(ee.Reducer.mean(), aoi, 1000, maxPixels=1e9, bestEffort=True).get('LST').getInfo()

    if (rural_t is None) or (urban_t is None) or (aoi_mean_t is None):
        return None

    if use_mcd12q1:
        up, vp, op = landcover_percentages_mcd(aoi.geometry(), lc_img, custom_veg_codes, custom_urban_codes)
    else:
        up, vp, op = landcover_percentages(aoi.geometry(), lc_img, custom_veg_codes, custom_urban_codes)

    uhi_img = lst_img_n.updateMask(urban_m).subtract(ee.Image.constant(rural_t)).rename('UHI')

    return {
        'Year': year,
        'Month': f"{best_m:02d}",
        'Image_Date': f"{year}-{best_m:02d}-15 (night)",
        'Satellite': 'MODIS',
        'LC_Source': f"{'MCD12Q1' if use_mcd12q1 else 'NLCD'}-{lc_year}",
        'Urban': round(urban_t, 2),
        'Vegetative': round(rural_t, 2),
        'Mean_LST': round(aoi_mean_t, 2),
        'UHI': round(urban_t - rural_t, 2),
        'Urban_Percent': up, 'Vegetative_Percent': vp, 'Other_Percent': op,
        'NLCD_Year': lc_year,
        'EE_Images': {'LST': lst_img_n, 'LC': lc_img, 'LC_TYPE': 'MCD12Q1' if use_mcd12q1 else 'NLCD', 'UHI': uhi_img}
    }

# ----------------------------
# Map & Legends & Drive export
# ----------------------------

def folium_map_with_layers(ee_images: dict, aoi_geom, map_center):
    from ee_folium_map import Map as _EEMap
    m = _EEMap(center=map_center, zoom=9)

    # Vis params — identical to local app
    ndvi_vis = {'min': -0.2, 'max': 0.9, 'palette': ['#f7fcf5','#c7e9c0','#74c476','#238b45','#00441b']}
    ndmi_vis = {'min': -0.6, 'max': 0.6, 'palette': ['#f7fbff','#c6dbef','#67a9cf','#2171b5','#08306b']}
    ndbi_vis = {'min': -0.5, 'max': 0.5, 'palette': ['#2166ac','#f7f7f7','#b2182b']}
    lst_vis  = {'min': 20.0, 'max': 45.0, 'palette': ['#2c7bb6','#abd9e9','#ffffbf','#fdae61','#d7191c']}
    uhi_vis  = {'min': -5.0, 'max':  5.0, 'palette': ['#2166ac','#67a9cf','#f7f7f7','#ef8a62','#b2182b']}

    # Collect colorbars to render together as a horizontal strip at the top,
    # matching the branca.LinearColormap layout used in the local app.
    colorbar_layers = []  # list of (title, palette, vmin, vmax)

    if 'LST' in ee_images:
        m.addLayer(ee_images['LST'].clip(aoi_geom), lst_vis, 'LST (°C)')
        colorbar_layers.append(("LST (°C)", lst_vis['palette'], lst_vis['min'], lst_vis['max']))

    if 'NDVI' in ee_images:
        m.addLayer(ee_images['NDVI'].clip(aoi_geom), ndvi_vis, 'NDVI')
        colorbar_layers.append(("NDVI", ndvi_vis['palette'], ndvi_vis['min'], ndvi_vis['max']))

    if 'NDMI' in ee_images:
        m.addLayer(ee_images['NDMI'].clip(aoi_geom), ndmi_vis, 'NDMI')
        colorbar_layers.append(("NDMI", ndmi_vis['palette'], ndmi_vis['min'], ndmi_vis['max']))

    if 'NDBI' in ee_images:
        m.addLayer(ee_images['NDBI'].clip(aoi_geom), ndbi_vis, 'NDBI')
        colorbar_layers.append(("NDBI", ndbi_vis['palette'], ndbi_vis['min'], ndbi_vis['max']))

    # Land cover — add as map layer only, NO legend swatches (matches local app behaviour:
    # local app also only shows layer name in the layer control, no separate swatch panel)
    lc_img_raw = ee_images.get('LC') or ee_images.get('NLCD')
    if lc_img_raw is not None:
        lc_type = ee_images.get('LC_TYPE', 'NLCD')
        lc_clipped = lc_img_raw.clip(aoi_geom)
        if lc_type == 'MCD12Q1':
            lc_styled, _ = mcd12q1_styled_and_legend(lc_clipped)
            lc_layer_name = 'MODIS MCD12Q1 Land Cover'
        else:
            lc_styled, _ = nlcd_styled_and_legend(lc_clipped)
            lc_layer_name = 'NLCD Land Cover'
        m.addLayer(lc_styled, {}, lc_layer_name)

    if 'UHI' in ee_images:
        m.addLayer(ee_images['UHI'].clip(aoi_geom), uhi_vis, 'UHI Intensity (°C)')
        colorbar_layers.append(("UHI (°C)", uhi_vis['palette'], uhi_vis['min'], uhi_vis['max']))

    # AOI boundary
    try:
        fc = ee.FeatureCollection(aoi_geom)
    except Exception:
        fc = aoi_geom
    outline = ee.Image().byte().paint(fc, 1, 2)
    m.addLayer(outline, {'palette': ['#00ffff']}, 'AOI boundary')

    # ── Colorbars: horizontal strip at the top of the map, side-by-side ──
    # This replicates what branca.LinearColormap + add_child() produces locally.
    # Each bar is a fixed-width block; they sit in a flex row pinned to top-left.
    if colorbar_layers:
        bar_items_html = ""
        for title, palette, vmin, vmax in colorbar_layers:
            gradient = ", ".join(palette)
            bar_items_html += f"""
            <div style="margin-right:12px; min-width:140px;">
              <div style="font-size:11px; font-weight:600; color:#333;
                          margin-bottom:2px; white-space:nowrap;">{title}</div>
              <div style="height:10px; width:100%;
                          background:linear-gradient(to right,{gradient});
                          border:1px solid #bbb; border-radius:2px;"></div>
              <div style="display:flex; justify-content:space-between;
                          font-size:10px; color:#444; margin-top:1px;">
                <span>{vmin}</span>
                <span>{(vmin+vmax)/2:.1f}</span>
                <span>{vmax}</span>
              </div>
            </div>"""

        colorbar_html = f"""
        <div style="
            position: fixed;
            top: 0px;
            left: 0px;
            z-index: 1000;
            background: rgba(255,255,255,0.90);
            border-bottom: 1px solid #ccc;
            padding: 5px 10px 4px 10px;
            display: flex;
            flex-direction: row;
            align-items: flex-start;
            font-family: Arial, sans-serif;
            pointer-events: none;
            width: auto;
            max-width: 100%;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15);
        ">
            {bar_items_html}
        </div>
        """
        m.get_root().html.add_child(folium.Element(colorbar_html))

    try:
        m.addLayerControl()
    except Exception:
        m.add_layer_control()
    return m

def export_layers_to_drive(year: int, layers: dict, aoi_fc: ee.FeatureCollection, folder: str, scale: int):
    region = aoi_fc.geometry()
    for key, image in layers.items():
        if image is None:
            continue
        try:
            desc = f"{key}_{year}"
            geemap.ee_export_image_to_drive(
                image=image, description=desc, folder=folder,
                region=region, scale=scale, fileFormat='GeoTIFF', crs='EPSG:4326'
            )
            st.success(f"Export task created: {desc} → Drive/{folder}")
        except Exception as e:
            st.warning(f"Could not export {key}: {e}")

# ----------------------------
# Trend helpers & plotting
# ----------------------------
def sens_slope_and_p(x_vals: np.ndarray, y_vals: np.ndarray):
    mask = ~np.isnan(y_vals)
    x = x_vals[mask]; y = y_vals[mask]
    if y.size < 2: return None, None
    if _HAS_MK:
        res = mk.original_test(y)
        slope, p = float(res.slope), float(res.p)
    else:
        slope, _, _, _ = stats.theilslopes(y, x)
        _, p = stats.kendalltau(x, y)
        slope, p = float(slope), float(p)
    return slope, p

def _save_fig_to_bytes(fig):
    b = io.BytesIO(); fig.savefig(b, format='png', dpi=300, bbox_inches='tight'); b.seek(0); return b.getvalue()

def plot_series_with_trends(years: np.ndarray, y: np.ndarray, title: str, ylabel: str, legend_prefix: str, store_key: str, night: bool=False):
    s = pd.Series(y)
    ma = s.rolling(window=3, center=True, min_periods=1).mean().to_numpy()

    slope_raw, p_raw = sens_slope_and_p(years, y)
    slope_ma,  p_ma  = sens_slope_and_p(years, ma)

    orig_color = '#1f77b4'
    ma_color   = '#ff7f0e'

    # Nighttime gets a subtle blue-tinted panel, but text is always dark/readable
    plot_bg  = '#f0f4ff' if night else '#ffffff'  # very light blue tint for night, pure white for day
    paper_bg = '#ffffff'                           # always white outer area
    text_col = '#1a1a1a'                           # always near-black text
    grid_col = '#d4d4d4'                           # medium gray grid

    fig = go.Figure()

    # Original series
    fig.add_trace(go.Scatter(
        x=years, y=y, mode='lines+markers', name=f'{legend_prefix} (Original)',
        line=dict(color=orig_color, width=1.5, dash='dot'),
        marker=dict(size=6), opacity=0.50
    ))

    # 3-year MA
    fig.add_trace(go.Scatter(
        x=years, y=ma, mode='lines+markers', name=f'{legend_prefix} (3-yr MA)',
        line=dict(color=ma_color, width=2.5),
        marker=dict(size=7, symbol='square')
    ))

    # Trend lines
    if slope_raw is not None:
        valid_y = y[~np.isnan(y)]
        if len(valid_y) > 0:
            x_line = np.array([years.min(), years.max()])
            y_raw  = slope_raw * (x_line - x_line[0]) + valid_y[0]
            fig.add_trace(go.Scatter(
                x=x_line, y=y_raw, mode='lines',
                name=f'Original trend: {slope_raw:.4f}/yr (p={p_raw:.3f})',
                line=dict(color=orig_color, width=2, dash='dash'), opacity=0.65
            ))

    if slope_ma is not None:
        valid_ma = ma[~np.isnan(ma)]
        if len(valid_ma) > 0:
            x_line = np.array([years.min(), years.max()])
            y_ma   = slope_ma * (x_line - x_line[0]) + valid_ma[0]
            fig.add_trace(go.Scatter(
                x=x_line, y=y_ma, mode='lines',
                name=f'MA trend: {slope_ma:.4f}/yr (p={p_ma:.3f})',
                line=dict(color=ma_color, width=2.5)
            ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=text_col), x=0.0, xanchor='left'),
        xaxis=dict(
            title=dict(text='Year', font=dict(color=text_col, size=11)),
            tickformat='d',
            tickfont=dict(color=text_col, size=10),
            gridcolor=grid_col,
            linecolor='#888',
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text=ylabel, font=dict(color=text_col, size=11)),
            tickfont=dict(color=text_col, size=10),
            gridcolor=grid_col,
            linecolor='#888',
            zeroline=False,
        ),
        plot_bgcolor=plot_bg,
        paper_bgcolor=paper_bg,
        legend=dict(
            font=dict(size=9, color=text_col),
            bgcolor='rgba(255,255,255,0.92)',
            bordercolor='#aaa',
            borderwidth=1
        ),
        hovermode='x unified',
        margin=dict(l=65, r=20, t=50, b=55),
        height=400
    )

    st.plotly_chart(fig, use_container_width=True)

    # Static PNG for ZIP download (matplotlib)
    try:
        fig_mpl, ax = plt.subplots(figsize=(9, 4))
        ax.set_facecolor('#f0f4ff' if night else 'white')
        ax.plot(years, y,  'o-', color=orig_color, markersize=5, alpha=0.45, linewidth=1.5, label=f'{legend_prefix} (Original)')
        ax.plot(years, ma, 's-', color=ma_color,   markersize=6, alpha=0.9,  linewidth=2.0, label=f'{legend_prefix} (3-yr MA)')
        if slope_raw is not None:
            valid_y2 = y[~np.isnan(y)]
            x_line = np.array([years.min(), years.max()])
            ax.plot(x_line, slope_raw*(x_line-x_line[0])+valid_y2[0], '--', color=orig_color, linewidth=2, alpha=0.55,
                    label=f'Original: {slope_raw:.4f}/yr (p={p_raw:.3f})')
        if slope_ma is not None:
            valid_ma2 = ma[~np.isnan(ma)]
            x_line = np.array([years.min(), years.max()])
            ax.plot(x_line, slope_ma*(x_line-x_line[0])+valid_ma2[0], '-', color=ma_color, linewidth=2.5, alpha=0.9,
                    label=f'MA: {slope_ma:.4f}/yr (p={p_ma:.3f})')
        ax.set_title(title, fontsize=12); ax.set_xlabel('Year', fontsize=9); ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, linestyle='--', alpha=0.5, color='#d0d0d0'); ax.legend(fontsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        plt.tight_layout()
        st.session_state.chart_figures[store_key] = _save_fig_to_bytes(fig_mpl)
        plt.close(fig_mpl)
    except Exception:
        pass

def plot_urban_vs_rural_comparison(df: pd.DataFrame, label: str, store_key='urban_rural_comparison', night: bool=False):
    years = df['Year'].astype(int).to_numpy()
    urban = df['Urban'].astype(float).to_numpy()
    rural = df['Vegetative'].astype(float).to_numpy()
    delta = np.abs(urban - rural)

    plot_bg  = '#f0f4ff' if night else '#ffffff'
    paper_bg = '#ffffff'
    text_col = '#1a1a1a'
    grid_col = '#d4d4d4'

    fig = go.Figure()

    # Shaded UHI gap between urban and vegetative
    fig.add_trace(go.Scatter(
        x=np.concatenate([years, years[::-1]]),
        y=np.concatenate([urban, rural[::-1]]),
        fill='toself', fillcolor='rgba(180,180,180,0.20)',
        line=dict(color='rgba(0,0,0,0)'),
        hoverinfo='skip', showlegend=False, name='UHI gap'
    ))

    # Urban line
    fig.add_trace(go.Scatter(
        x=years, y=urban, mode='lines+markers', name='Urban (Mean LST)',
        line=dict(color='#e74c3c', width=2.2),
        marker=dict(size=7),
        hovertemplate='%{x}: %{y:.2f} °C<extra>Urban</extra>'
    ))

    # Vegetative line
    fig.add_trace(go.Scatter(
        x=years, y=rural, mode='lines+markers', name='Vegetative (Mean LST)',
        line=dict(color='#27ae60', width=2.2),
        marker=dict(size=7),
        hovertemplate='%{x}: %{y:.2f} °C<extra>Vegetative</extra>'
    ))

    # Delta labels at midpoint
    fig.add_trace(go.Scatter(
        x=years, y=(urban + rural) / 2,
        mode='text',
        text=[f'Δ{d:.1f}°C' for d in delta],
        textposition='middle center',
        textfont=dict(size=9, color='#444'),
        hoverinfo='skip', showlegend=False, name='UHI Δ'
    ))

    fig.update_layout(
        title=dict(text=f"{label}: Urban vs Vegetative Surface Temperature",
                   font=dict(size=14, color=text_col), x=0.0, xanchor='left'),
        xaxis=dict(
            title=dict(text='Year', font=dict(color=text_col, size=11)),
            tickformat='d',
            tickfont=dict(color=text_col, size=10),
            gridcolor=grid_col,
            linecolor='#888',
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text='Land Surface Temperature (°C)', font=dict(color=text_col, size=11)),
            tickfont=dict(color=text_col, size=10),
            gridcolor=grid_col,
            linecolor='#888',
            zeroline=False,
        ),
        plot_bgcolor=plot_bg,
        paper_bgcolor=paper_bg,
        legend=dict(
            font=dict(size=10, color=text_col),
            bgcolor='rgba(255,255,255,0.92)',
            bordercolor='#aaa',
            borderwidth=1
        ),
        hovermode='x unified',
        margin=dict(l=70, r=20, t=55, b=60),
        height=430
    )

    st.plotly_chart(fig, use_container_width=True)

    # Static PNG for ZIP download
    try:
        fig_mpl, ax = plt.subplots(figsize=(11, 5))
        ax.set_facecolor('#f0f4ff' if night else 'white')
        ax.plot(years, urban, '-o', linewidth=1.8, label='Urban Areas (Mean)', color='#e74c3c')
        ax.plot(years, rural, '-o', linewidth=1.8, label='Vegetative Areas (Mean)', color='#27ae60')
        for x, u, r in zip(years, urban, rural):
            if np.isfinite(u) and np.isfinite(r):
                ymin, ymax = sorted([u, r])
                ax.fill_between([x-0.3, x+0.3], ymin, ymax, alpha=0.15, color='gray')
                ax.text(x, (u+r)/2, f"Δ{abs(u-r):.1f}°C", ha='center', va='center',
                        fontsize=8, bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7))
        ax.set_title(f"{label}: Urban vs Vegetative Surface Temperature", fontsize=13)
        ax.set_xlabel('Year', fontsize=10); ax.set_ylabel('LST (°C)', fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.5, color='#d0d0d0')
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.legend(fontsize=9); plt.tight_layout()
        st.session_state.chart_figures[store_key] = _save_fig_to_bytes(fig_mpl)
        plt.close(fig_mpl)
    except Exception:
        pass

# ----------------------------
# Session state
# ----------------------------
for key, default in [
    ('analysis_ready', False), ('results_df', None),
    ('results_df_night', None),
    ('ee_layers_by_year', {}), ('aoi_gdf', None), ('aoi_ee', None),
    ('chart_figures', {}), ('custom_aoi_geojson', None),
    ('landcover_pies', {})
]:
    if key not in st.session_state: st.session_state[key] = default

# ----------------------------
# AOI preview / builder section
# ----------------------------
if aoi_source == "County (US only)":
    st.subheader("AOI Preview (County)")
    if _census_key_missing() or _census_api_is_down():
        st.info(
            "ℹ️ Enter your Census API key in the sidebar (**🗝️ Census API Key**) "
            "to use County mode, or switch to **Custom AOI**. "
            "Get a free key at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html)"
        )
    elif not counties:
        st.warning("County list could not be loaded. Census API may be temporarily down.")
    else:
        show_county_preview_map(states[selected_state], counties[selected_county])

elif aoi_source == "City (US only)":
    st.subheader("AOI Preview (City)")

    if not selected_city:
        st.info("Select a state and city in the sidebar to build a city AOI.")
    else:
        try:
            # Load city boundary from Census Places shapefile
            city_fc_ee, city_gdf_ll, epsg_city = load_city_aoi_from_census(state_id, selected_city)
            city_geom = city_fc_ee.geometry()

            # City Boundary Type
            if city_boundary_type == "CCA urban cluster (1000 m)":
                cca_fc = run_cca(city_geom, d_m=1000)
                cca_feat = pick_nearest_cluster(cca_fc, city_geom)
                base_geom = cca_feat.geometry()
                st.caption("Using CCA-derived urban cluster (d = 1000 m).")
            else:
                base_geom = city_geom
                st.caption("Using Census city boundary (Census Places 2022).")

            # ------------------------------
            # Urban area & recommended buffer
            # ------------------------------
            urban_area_km2 = compute_urban_area_km2(base_geom)
            rec_buf_km, city_category = classify_city_and_buffer(urban_area_km2)
            
            c1, c2 = st.columns(2)
            c1.info(f"Urban area (NLCD): **{urban_area_km2:.1f} km²**")
            
            c2.info(
                f"Recommended buffer: **{rec_buf_km:.1f} km** "
                f"({city_category})"
            )
            st.caption(
                "City categories: Small (<150 km² → 5 km Buffer), "
                "Mid-size (150–500 km² → 10 km Buffer), "
                "Large (>500 km² → 15 km Buffer)."
            )
            # ------------------------------
            # Buffer selection
            # ------------------------------
            buffer_mode = st.radio(
                "Buffer for analysis AOI",
                ["Recommended", "Custom", "No buffer"],
                index=0,
                horizontal=True
            )

            if buffer_mode == "Recommended":
                buf_km = rec_buf_km
            elif buffer_mode == "Custom":
                buf_km = st.number_input(
                    "Custom buffer distance (km)",
                    min_value=0.0,
                    value=float(rec_buf_km),
                    step=1.0
                )
            else:
                buf_km = 0.0

            # Apply buffer
            if buf_km > 0.0:
                final_geom = base_geom.buffer(buf_km * 1000)
            else:
                final_geom = base_geom

            # Save AOI as GeoJSON for downstream analysis
            try:
                gj = final_geom.getInfo()
            except Exception:
                gj = base_geom.getInfo()

            st.session_state['custom_aoi_geojson'] = gj

            # ------------------------------
            # Preview Map
            # ------------------------------
            poly = shp_shape(gj)
            gdf_city = gpd.GeoDataFrame({'name': ['City AOI']}, geometry=[poly], crs="EPSG:4326")
            center = [gdf_city.geometry.centroid.y.mean(), gdf_city.geometry.centroid.x.mean()]

            m = folium.Map(location=center, zoom_start=10, tiles='cartodbpositron', control_scale=True)
            folium.GeoJson(
                gdf_city.__geo_interface__,
                name="City AOI",
                style_function=lambda _: {'color': '#e41a1c', 'weight': 2, 'fillOpacity': 0.10}
            ).add_to(m)

            Fullscreen().add_to(m)
            Geocoder(collapsed=True, position='topleft', add_marker=False).add_to(m)
            folium.LayerControl().add_to(m)
            st_folium(m, height=420, width=None)

        except Exception as e:
            st.warning(f"Could not build city AOI: {e}")

elif aoi_source == "Custom AOI (US / Global)":
    if custom_aoi_mode == "Draw on map":
        _ = build_draw_aoi_ui()
    else:
        st.subheader("AOI from Shapefile")
        uploaded_zip = st.file_uploader("Upload zipped shapefile (.zip)", type=["zip"])
        if uploaded_zip is not None:
            gdf_ll, gj = load_shapefile_from_zip(uploaded_zip.getvalue())
            if gdf_ll is not None and gj is not None:
                st.session_state['custom_aoi_geojson'] = gj
                st.success("Shapefile AOI loaded. This AOI will be used for analysis.")
                center = [gdf_ll.geometry.centroid.y.mean(), gdf_ll.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=9, tiles='cartodbpositron', control_scale=True)
                folium.GeoJson(
                    gdf_ll.__geo_interface__,
                    name="Shapefile AOI",
                    style_function=lambda _: {'color': '#4daf4a', 'weight': 2, 'fillOpacity': 0.10}
                ).add_to(m)
                Fullscreen().add_to(m)
                Geocoder(collapsed=True, position='topleft', add_marker=False).add_to(m)
                folium.LayerControl().add_to(m)
                st_folium(m, height=420, width=None)

# ----------------------------
# Run / Reset
# ----------------------------
run_btn   = st.sidebar.button("Run Analysis", type='primary')
reset_btn = st.sidebar.button("Reset")

if reset_btn:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

if run_btn:
    if end_year < start_year:
        st.error("End year must be greater than or equal to start year.")
    elif len(selected_months) == 0:
        st.error("Select at least one month.")
    else:
        if aoi_mode == "County boundary":
            with st.spinner("Loading county AOI…"):
                aoi_ee, aoi_gdf_ll, epsg = load_county_aoi(states[selected_state], counties[selected_county])
        else:
            gj = st.session_state.get('custom_aoi_geojson')
            if gj is None:
                st.error("Define an AOI (city, drawn polygon, or shapefile) before running analysis.")
                st.stop()
            try:
                ee_geom = geemap.geojson_to_ee(gj).geometry()
            except Exception:
                ee_geom = ee.Geometry(gj)
            aoi_ee = ee.FeatureCollection([ee.Feature(ee_geom)])
            aoi_gdf_ll = gpd.GeoDataFrame({'name':['Custom AOI']}, geometry=[shp_shape(gj)], crs="EPSG:4326")

        years = list(range(start_year, end_year + 1))
        results_day, results_night, ee_layers = [], [], {}
        hottest_months = {}
        progress_bar = st.progress(0.0, text="Starting analysis…")

        for i, yr in enumerate(years):
            progress_bar.progress(i / len(years), text=f"Processing {yr}…")
            if source.startswith('MODIS'):
                rec_day, best_m, lst_img_day = process_modis_day_and_best_month(
                    yr, aoi_ee, selected_months,
                    custom_veg_codes if not lulc_ref_mode else None,
                    custom_urban_codes if not lulc_ref_mode else None,
                    use_mcd12q1=use_mcd12q1
                )
                if rec_day:
                    hottest_months[yr] = best_m
                    results_day.append(rec_day)
                    ee_layers[int(yr)] = rec_day.pop('EE_Images', {})
                    rec_nig = process_modis_night_for_month(
                        yr, aoi_ee, best_m,
                        custom_veg_codes if not lulc_ref_mode else None,
                        custom_urban_codes if not lulc_ref_mode else None,
                        use_mcd12q1=use_mcd12q1
                    )
                    if rec_nig:
                        results_night.append(rec_nig)
            else:
                rec_day = process_landsat_data(
                    yr, aoi_ee, selected_months,
                    custom_veg_codes if not lulc_ref_mode else None,
                    custom_urban_codes if not lulc_ref_mode else None,
                    selected_sensors if not landsat_sensor_recommended else None
                )
                if rec_day:
                    hottest_months[yr] = int(rec_day['Month'])
                    results_day.append(rec_day)
                    ee_layers[int(yr)] = rec_day.pop('EE_Images', {})


        progress_bar.progress(1.0, text="Analysis complete.")

        if not results_day:
            st.error("No valid data found for the selected parameters. Adjust years/months/AOI.")
            if use_mcd12q1:
                st.warning("⚠️ You are using MODIS MCD12Q1 land cover (500 m). If your AOI covers a small or low-density urban area, there may be no pixels classified as Urban (class 13) within the boundary. Try switching to NLCD (US-only) for finer 30 m urban detection, or expand your AOI to include more of the urban extent.")
            st.stop()

        df_day = pd.DataFrame(results_day).sort_values('Year').reset_index(drop=True)
        lst_df = df_day[['Year', 'Mean_LST']].copy()
        lst_df.rename(columns={'Year': 'year', 'Mean_LST': 'lst'}, inplace=True)
        lst_df['lst_anomaly'] = lst_df['lst'] - lst_df['lst'].mean()

        df_night = pd.DataFrame(results_night).sort_values('Year').reset_index(drop=True) if results_night else None

        st.session_state.analysis_ready    = True
        st.session_state.results_df        = df_day
        st.session_state.results_df_night  = df_night
        st.session_state.ee_layers_by_year = ee_layers
        st.session_state.aoi_gdf           = aoi_gdf_ll
        st.session_state.aoi_ee            = aoi_ee
        st.session_state["analysis_results"] = {
            "aoi": aoi_ee,
            "years": years,
            "hottest_months": hottest_months,
            "lst_df": lst_df
        }

        st.success("Analysis complete.")
        st.rerun()

# ----------------------------
# Output tabs
# ----------------------------
if st.session_state.analysis_ready and st.session_state.results_df is not None:
    df = st.session_state.results_df.copy()
    df_n = st.session_state.results_df_night.copy() if st.session_state.results_df_night is not None else None

    # UHI MA slope & p (table + charts use)
    years_np = df['Year'].astype(int).to_numpy()
    uhi_ma_day = df['UHI'].astype(float).rolling(window=3, center=True, min_periods=1).mean()
    slope_day, p_day = sens_slope_and_p(years_np, uhi_ma_day.to_numpy())

    slope_night, p_night = None, None
    years_np_n = None
    if df_n is not None and not df_n.empty:
        years_np_n = df_n['Year'].astype(int).to_numpy()
        uhi_ma_n = df_n['UHI'].astype(float).rolling(window=3, center=True, min_periods=1).mean()
        slope_night, p_night = sens_slope_and_p(years_np_n, uhi_ma_n.to_numpy())

    t1, t2, t3, t4, t5, t6 = st.tabs(["Results Table", "Charts", "Interactive Map", "Land Cover Change", "Shapefile Export", "Validation"])

    # ----- Results Table
    with t1:
        st.subheader("UHI Analysis Results")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("UHI 3-yr MA Sen’s slope (Day, °C/yr)", f"{(slope_day or 0):.4f}")
        with c2:
            st.metric("UHI 3-yr MA Mann–Kendall p (Day)", f"{(p_day or 1):.4f}")

        # Day table (add slope/p columns)
        display_df = df.copy()
        display_df['Year'] = display_df['Year'].astype(int).astype(str)
        if 'NLCD_Year' in display_df.columns and display_df['NLCD_Year'].notna().any():
            display_df['NLCD_Year'] = display_df['NLCD_Year'].astype(int).astype(str)

        display_df['UHI_MA_SenSlope_Day'] = slope_day if slope_day is not None else None
        display_df['UHI_MA_p_Day'] = p_day if p_day is not None else None

        cols_day = ['Year','Month','Satellite','LC_Source','Image_Date','Urban','Vegetative','UHI','Mean_LST',
                    'Mean_NDVI','Mean_NDMI','Mean_NDBI','Urban_Percent','Vegetative_Percent','NLCD_Year',
                    'UHI_MA_SenSlope_Day','UHI_MA_p_Day']
        cols_day = [c for c in cols_day if c in display_df.columns]  # skip missing cols gracefully
        st.markdown("**Daytime (primary)**")
        st.dataframe(display_df[cols_day], use_container_width=True)

        csv_day = display_df[cols_day].to_csv(index=False).encode('utf-8')
        fname_day = f"{selected_state}_{selected_county}_{'MODIS' if source.startswith('MODIS') else 'Landsat'}_{start_year}_{end_year}_DAY.csv"
        st.download_button("Download Daytime CSV", csv_day, file_name=fname_day, mime='text/csv')

        # Night table (MODIS only) + slope/p columns
        if df_n is not None and not df_n.empty:
            st.markdown("---")
            st.markdown("**Nighttime (MODIS)** — (no NDVI/NDMI/NDBI fields)")
            c3, c4 = st.columns(2)
            with c3:
                st.metric("UHI 3-yr MA Sen’s slope (Night, °C/yr)", f"{(slope_night or 0):.4f}")
            with c4:
                st.metric("UHI 3-yr MA Mann–Kendall p (Night)", f"{(p_night or 1):.4f}")

            display_n = df_n.copy()
            display_n['Year'] = display_n['Year'].astype(int).astype(str)
            if 'NLCD_Year' in display_n.columns and display_n['NLCD_Year'].notna().any():
                display_n['NLCD_Year'] = display_n['NLCD_Year'].astype(int).astype(str)
            display_n['UHI_MA_SenSlope_Night'] = slope_night if slope_night is not None else None
            display_n['UHI_MA_p_Night'] = p_night if p_night is not None else None

            cols_n = ['Year','Month','Satellite','Image_Date','Urban','Vegetative','UHI','Mean_LST',
                      'Urban_Percent','Vegetative_Percent','NLCD_Year','UHI_MA_SenSlope_Night','UHI_MA_p_Night']
            st.dataframe(display_n[cols_n], use_container_width=True)

            csv_n = display_n[cols_n].to_csv(index=False).encode('utf-8')
            fname_n = f"{selected_state}_{selected_county}_MODIS_{start_year}_{end_year}_NIGHT.csv"
            st.download_button("Download Nighttime CSV", csv_n, file_name=fname_n, mime='text/csv')

    # ----- Charts
    with t2:
        st.subheader("Trend Analysis & Comparisons")
        st.session_state.chart_figures = {}

        # Daytime slope/p shown before charts
        st.markdown("**Daytime UHI – 3-yr MA trend stats**")
        colA, colB = st.columns(2)
        colA.info(f"Sen’s slope: **{(slope_day or 0):.4f} °C/yr**")
        colB.info(f"Mann–Kendall p: **{(p_day or 1):.4f}**")

        # Daytime charts
        st.markdown("**UHI Trend (Day)**")
        plot_series_with_trends(years_np, df['UHI'].astype(float).to_numpy(),
                                title='Trend of UHI Intensity (Day)', ylabel='UHI (°C)', legend_prefix='UHI',
                                store_key='uhi_trend_day', night=False)

        st.markdown("**Mean LST Trend (Day)**")
        plot_series_with_trends(years_np, df['Mean_LST'].astype(float).to_numpy(),
                                title='Trend of Mean LST (Day)', ylabel='LST (°C)', legend_prefix='Mean LST',
                                store_key='mean_lst_trend_day', night=False)

        st.markdown("**NDVI Trend (Day)**")
        plot_series_with_trends(years_np, df['Mean_NDVI'].astype(float).to_numpy(),
                                title='Trend of Mean NDVI (Day)', ylabel='Mean NDVI', legend_prefix='NDVI',
                                store_key='ndvi_trend_day', night=False)

        st.markdown("**NDMI Trend (Day)**")
        plot_series_with_trends(years_np, df['Mean_NDMI'].astype(float).to_numpy(),
                                title='Trend of Mean NDMI (Day)', ylabel='Mean NDMI', legend_prefix='NDMI',
                                store_key='ndmi_trend_day', night=False)

        if 'Mean_NDBI' in df.columns and df['Mean_NDBI'].notna().any():
            st.markdown("**NDBI Trend (Day)**")
            plot_series_with_trends(years_np, df['Mean_NDBI'].astype(float).to_numpy(),
                                    title='Trend of Mean NDBI (Day)', ylabel='Mean NDBI', legend_prefix='NDBI',
                                    store_key='ndbi_trend_day', night=False)

        st.markdown("---")
        st.subheader("Urban vs Vegetative Temperature Comparison (Day)")
        plot_urban_vs_rural_comparison(df, selected_county, store_key='urban_rural_day', night=False)

        # Nighttime (if available)
        if df_n is not None and not df_n.empty:
            st.markdown("---")
            st.subheader("Nighttime LST (MODIS) ")
            st.markdown("**Nighttime UHI – 3-yr MA trend stats**")
            colC, colD = st.columns(2)
            colC.info(f"Sen’s slope: **{(slope_night or 0):.4f} °C/yr**")
            colD.info(f"Mann–Kendall p: **{(p_night or 1):.4f}**")

            st.markdown("**UHI Trend (Night)**")
            plot_series_with_trends(years_np_n, df_n['UHI'].astype(float).to_numpy(),
                                    title='Trend of UHI Intensity (Night)', ylabel='UHI (°C)', legend_prefix='UHI',
                                    store_key='uhi_trend_night', night=True)

            st.markdown("**Mean LST Trend (Night)**")
            plot_series_with_trends(years_np_n, df_n['Mean_LST'].astype(float).to_numpy(),
                                    title='Trend of Mean LST (Night)', ylabel='LST (°C)', legend_prefix='Mean LST',
                                    store_key='mean_lst_trend_night', night=True)

            st.markdown("---")
            st.subheader("Urban vs Vegetative Temperature Comparison (Night)")
            plot_urban_vs_rural_comparison(df_n, selected_county, store_key='urban_rural_night', night=True)

        # Downloads
        if st.session_state.chart_figures:
            st.markdown("---")
            st.subheader("Download Charts")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zipf:
                for name, png_bytes in st.session_state.chart_figures.items():
                    if png_bytes:
                        zipf.writestr(f"{name}.png", png_bytes)
            zip_buffer.seek(0)
            st.download_button("Download All Charts as ZIP",
                               data=zip_buffer,
                               file_name=f"UHI_charts_{selected_county}_{start_year}-{end_year}.zip",
                               mime="application/zip")

    # ----- Interactive Map (+ Drive Exports)
    with t3:
        st.subheader("Interactive Map Layers")
        yrs_with = sorted([y for y in st.session_state.ee_layers_by_year.keys()
                           if st.session_state.ee_layers_by_year[y]])
        if not yrs_with:
            st.warning("No map layers were generated.")
        else:
            sel_year = st.selectbox("Select year to visualize", yrs_with, index=len(yrs_with)-1)
            layers = st.session_state.ee_layers_by_year.get(sel_year)
            if not layers:
                st.warning(f"No map layers available for {sel_year}.")
            else:
                center_latlon = get_aoi_center_latlon(st.session_state.aoi_ee)
                m = folium_map_with_layers(layers, st.session_state.aoi_ee.geometry(), center_latlon)
                st_folium(m, height=520, width=None, returned_objects=[])
                st.caption("Use the layer control (top-right) to toggle overlays.")

                st.markdown("**Export rasters to Google Drive (GeoTIFF)**")
                folder = st.text_input("Drive folder name", value=f"UHI_Exports_{selected_state}_{selected_county}")
                if st.button("Queue Drive exports", type="primary"):
                    scale = 1000 if source.startswith('MODIS') else 30
                    export_layers_to_drive(sel_year, layers, st.session_state.aoi_ee, folder, scale)

    # ----- Land Cover Change (with pie downloads)
    with t4:
        st.subheader("Land Cover Change")
        st.session_state.landcover_pies = {}
        if df.empty or len(df) < 2:
            st.info("Run analysis for a period of at least two years to see land cover change.")
        else:
            srow, erow = df.iloc[0], df.iloc[-1]
            ok = all(v is not None for v in [srow.get('Urban_Percent'), srow.get('Vegetative_Percent'),
                                             erow.get('Urban_Percent'), erow.get('Vegetative_Percent')])
            if not ok:
                st.warning("Land cover percentages are unavailable for one or both years.")
            else:
                vs = [float(srow['Urban_Percent']), float(srow['Vegetative_Percent']),
                      float(srow.get('Other_Percent', 100.0 - srow['Urban_Percent'] - srow['Vegetative_Percent']))]
                ve = [float(erow['Urban_Percent']), float(erow['Vegetative_Percent']),
                      float(erow.get('Other_Percent', 100.0 - erow['Urban_Percent'] - erow['Vegetative_Percent']))]
                labels = ['Urban', 'Vegetative', 'Other']
                pie_colors = ['#d7191c', '#1a9641', '#bdbdbd']
                c1, c2 = st.columns(2)
                with c1:
                    fig1 = go.Figure(go.Pie(
                        labels=labels, values=vs,
                        marker=dict(colors=pie_colors),
                        textinfo='label+percent', hole=0.3,
                        hovertemplate='%{label}: %{value:.1f}%<extra></extra>'
                    ))
                    fig1.update_layout(
                        title=f"Land Cover ({int(srow['Year'])})",
                        showlegend=True, height=350, margin=dict(t=50, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig1, use_container_width=True)
                    # Static PNG for ZIP
                    fig_mpl1, ax1 = plt.subplots(figsize=(3.2, 3.2))
                    ax1.pie(vs, labels=labels, autopct='%1.1f%%', startangle=90, colors=pie_colors)
                    ax1.set_title(f"Land Cover ({int(srow['Year'])})")
                    st.session_state.landcover_pies[f"landcover_{int(srow['Year'])}.png"] = _save_fig_to_bytes(fig_mpl1)
                    plt.close(fig_mpl1)
                with c2:
                    fig2 = go.Figure(go.Pie(
                        labels=labels, values=ve,
                        marker=dict(colors=pie_colors),
                        textinfo='label+percent', hole=0.3,
                        hovertemplate='%{label}: %{value:.1f}%<extra></extra>'
                    ))
                    fig2.update_layout(
                        title=f"Land Cover ({int(erow['Year'])})",
                        showlegend=True, height=350, margin=dict(t=50, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                    # Static PNG for ZIP
                    fig_mpl2, ax2 = plt.subplots(figsize=(3.2, 3.2))
                    ax2.pie(ve, labels=labels, autopct='%1.1f%%', startangle=90, colors=pie_colors)
                    ax2.set_title(f"Land Cover ({int(erow['Year'])})")
                    st.session_state.landcover_pies[f"landcover_{int(erow['Year'])}.png"] = _save_fig_to_bytes(fig_mpl2)
                    plt.close(fig_mpl2)
                st.markdown("---")
                st.subheader("Change Over Period")
                st.metric("Urban Area Change",      f"{ve[0]-vs[0]:+.2f}%")
                st.metric("Vegetative Area Change", f"{ve[1]-vs[1]:+.2f}%")

                # Download pies
                if st.session_state.landcover_pies:
                    zbuf = io.BytesIO()
                    with zipfile.ZipFile(zbuf, 'w') as zf:
                        for name, png_bytes in st.session_state.landcover_pies.items():
                            zf.writestr(name, png_bytes)
                    zbuf.seek(0)
                    st.download_button("Download Land-cover Pie Charts (ZIP)",
                                       data=zbuf,
                                       file_name=f"LandCoverPies_{selected_county}_{start_year}-{end_year}.zip",
                                       mime="application/zip")

    # ----- Shapefile Export (AOI + per-year center points with attributes)
    with t5:
        st.subheader("Shapefile Export (ZIP)")
        st.caption("Exports AOI polygon and per-year center-point features with time-series attributes (includes Day + Night data for MODIS).")
        if st.button("Build Shapefile ZIP"):
            try:
                # AOI polygon GeoDataFrame
                if st.session_state.aoi_gdf is not None:
                    aoi_poly_gdf = st.session_state.aoi_gdf.copy()
                    aoi_poly_gdf['name'] = f"{selected_state}-{selected_county}"
                else:
                    gj = st.session_state.get('custom_aoi_geojson')
                    geom = shp_shape(gj)
                    aoi_poly_gdf = gpd.GeoDataFrame({'name':[f"{selected_state}-{selected_county}"]}, geometry=[geom], crs="EPSG:4326")
    
                # Per-year center-point GDF with attributes
                center_lat, center_lon = get_aoi_center_latlon(st.session_state.aoi_ee)
                center_point = shp_Point(center_lon, center_lat)
                
                rows = []
                df_day = st.session_state.results_df
                df_night = st.session_state.results_df_night
                
                # Merge day and night data
                for _, r_day in df_day.iterrows():
                    year = int(r_day['Year'])
                    
                    # Find matching night record (if exists)
                    r_night = None
                    if df_night is not None and not df_night.empty:
                        night_match = df_night[df_night['Year'] == year]
                        if not night_match.empty:
                            r_night = night_match.iloc[0]
                    
                    # Build row with day + night data
                    row = {
                        'Year': year,
                        'Month': str(r_day['Month']),
                        'Sat': str(r_day.get('Satellite', '')),
                        
                        # DAY data
                        'Urb_D': float(r_day.get('Urban') or np.nan),
                        'Veg_D': float(r_day.get('Vegetative') or np.nan),
                        'UHI_D': float(r_day.get('UHI') or np.nan),
                        'LST_D': float(r_day.get('Mean_LST') or np.nan),
                        'NDVI': float(r_day.get('Mean_NDVI') or np.nan) if r_day.get('Mean_NDVI') is not None else np.nan,
                        'NDMI': float(r_day.get('Mean_NDMI') or np.nan) if r_day.get('Mean_NDMI') is not None else np.nan,
                        'NDBI': float(r_day.get('Mean_NDBI') or np.nan) if r_day.get('Mean_NDBI') is not None else np.nan,
                        
                        # NIGHT data (if available)
                        'Urb_N': float(r_night.get('Urban') or np.nan) if r_night is not None else np.nan,
                        'Veg_N': float(r_night.get('Vegetative') or np.nan) if r_night is not None else np.nan,
                        'UHI_N': float(r_night.get('UHI') or np.nan) if r_night is not None else np.nan,
                        'LST_N': float(r_night.get('Mean_LST') or np.nan) if r_night is not None else np.nan,
                        
                        # Land cover
                        'NLCD': int(r_day.get('NLCD_Year') or 0),
                        'UrbPct': float(r_day.get('Urban_Percent') or np.nan),
                        'VegPct': float(r_day.get('Vegetative_Percent') or np.nan),
                        
                        # Trend statistics
                        'Slp_D': float(slope_day or 0.0),
                        'P_D': float(p_day or 1.0),
                        'Slp_N': float(slope_night or 0.0) if slope_night is not None else np.nan,
                        'P_N': float(p_night or 1.0) if p_night is not None else np.nan,
                    }
                    rows.append(row)
                
                pts_gdf = gpd.GeoDataFrame(rows, geometry=[center_point]*len(rows), crs="EPSG:4326")
    
                # Write both layers as separate shapefiles and zip
                tmpdir = tempfile.mkdtemp()
                aoi_dir = os.path.join(tmpdir, "aoi")
                pts_dir = os.path.join(tmpdir, "ts_points")
                os.makedirs(aoi_dir, exist_ok=True); os.makedirs(pts_dir, exist_ok=True)
                aoi_poly_gdf.to_file(os.path.join(aoi_dir, "aoi_polygon.shp"), driver="ESRI Shapefile")
                pts_gdf.to_file(os.path.join(pts_dir, "uhi_timeseries_points.shp"), driver="ESRI Shapefile")
    
                # Zip them up
                zip_path = os.path.join(tmpdir, f"UHI_Shapefiles_{selected_state}_{selected_county}_{start_year}-{end_year}.zip")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for d in [aoi_dir, pts_dir]:
                        for f in os.listdir(d):
                            zf.write(os.path.join(d, f), arcname=os.path.join(os.path.basename(d), f))
    
                with open(zip_path, "rb") as f:
                    st.download_button(
                        "Download Shapefiles (ZIP)",
                        data=f.read(),
                        file_name=os.path.basename(zip_path),
                        mime="application/zip"
                    )
            except Exception as e:
                st.error(f"Shapefile export failed: {e}")
            
    with t6:
        render_validation_tab()
