# 🌡️ Urban Heat Island (UHI) Analyzer

[![tests](https://github.com/suyogautam/Global-UHI-Analyzer-/actions/workflows/tests.yml/badge.svg)](https://github.com/suyogautam/Global-UHI-Analyzer-/actions/workflows/tests.yml)

A web-based tool for satellite-derived surface urban heat island (SUHI) analysis using **Google Earth Engine**, **Landsat**, and **MODIS**. Analyze land surface temperature, spectral indices, and SUHI intensity for any city, county, or custom area of interest — from 2000 to present.

**Live app:** [uhi-analyzer.streamlit.app](https://uhi-analyzer.streamlit.app)

---

## Features

- **Dual satellite pipelines** — Landsat Collection 2 (30 m, 2000–present) and MODIS Terra/Aqua merged (1 km, 2000–present)
- **Month aggregation** — hottest month per year (default) or seasonal mean of all selected months; select one month for a fixed-month analysis
- **Spectral indices** — LST, NDVI, NDMI, NDBI computed annually
- **SUHI intensity** = urban median LST − vegetated-reference median LST (Landsat: mean of 5th–95th percentile-filtered LST)
- **Daytime and nighttime LST** (MODIS only)
- **Land cover** — NLCD (30 m, US only) or MODIS MCD12Q1 IGBP (500 m, global, annual)
- **MODIS platform choice** — Terra + Aqua (combined), Terra only, or Aqua only
- **User-defined reference classes** — choose which land-cover classes form the urban and vegetated reference
- **Trend analysis** — Theil–Sen slope + Mann–Kendall p on the original (unsmoothed) annual series; original or Hamed–Rao (autocorrelation-corrected) test. The 3-year moving average is for display only
- **Quality information** — valid-pixel counts (AOI, urban, reference) per year, a warning when the vegetated reference is very small (< 2 % of the AOI or < 10 valid pixels), and a list of years without valid data (left empty, never set to 0)
- **ERA5-Land consistency check** — Pearson correlation of LST anomalies with ERA5-Land 2 m air temperature anomalies (air temperature is not LST, so this checks consistency of interannual variation; it is not a validation)
- **Multiple AOI modes** — US county, US city (Census boundary or CCA urban cluster), drawn polygon, uploaded shapefile
- **Exports** — results CSV, trend chart PNGs (ZIP), GeoTIFF to Google Drive, shapefile ZIP

---

## Requirements

- **Google Earth Engine account** — [earthengine.google.com/signup](https://earthengine.google.com/signup/) (free for research)
- **Census API key** *(for County and City AOI modes only)* — [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html) (free, instant email)
- **Custom AOI mode** (draw/upload shapefile) works without a Census key and supports global areas

---

## Using the Hosted App

The easiest way — no installation required.

**1. Open the app**
Go to [uhi-analyzer.streamlit.app](https://uhi-analyzer.streamlit.app)

**2. Authenticate with Google Earth Engine**

The app runs entirely on your own GEE quota. Uploaded credentials are kept in memory for your browser session only — they are never written to the server's disk — and are discarded when you close the tab. If you prefer not to upload a credentials file, run the app locally (see Local Setup).

- Choose **"Upload Credentials File"**
- Locate your credentials file:
  - Windows: `C:\Users\YOUR_NAME\.config\earthengine\credentials`
  - Mac/Linux: `~/.config/earthengine/credentials`
- Enter your **GEE Project ID** (find it at [console.cloud.google.com](https://console.cloud.google.com))
- Upload the file and click **Authenticate**

If you have not authenticated before, run `earthengine authenticate` on your local machine first (see Local Setup below), then upload the credentials file.

**3. Enter your Census API key** *(optional — only needed for County and City modes)*

Expand the **🗝️ Census API Key** panel in the sidebar and paste your key. Get a free key at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html).

**4. Define your Area of Interest**

| Mode | Description | Requires |
|---|---|---|
| **County (US only)** | Select a US state and county | Census API key |
| **City (US only)** | Select a state and city; choose Census boundary or CCA urban cluster | Census API key |
| **Custom AOI (US / Global)** | Draw a polygon on the map | Nothing extra |
| **Custom AOI — Shapefile** | Upload a zipped `.shp` file | Nothing extra |

> ⚠️ NLCD-based analysis (Landsat and MODIS + NLCD) is **US only**. For global areas, use **Custom AOI** with **MODIS + MCD12Q1** land cover.

> ⚠️ MODIS MCD12Q1 has 500 m pixels. Small cities with few urban-class pixels in the AOI may return no urban data.

**5. Configure the analysis**

In the sidebar:
- **Sensor platform** — Landsat (30 m, US-focused) or MODIS (1 km, global)
- **Time range** — start and end year (2000–2026)
- **Months / Season** — individual months or preset seasons (DJF, MAM, JJA, SON)
- **Monthly aggregation** — hottest month or seasonal mean
- **MODIS platform** *(MODIS only)* — Terra + Aqua, Terra only, or Aqua only
- **Trend significance test** — original Mann–Kendall or Hamed–Rao modified
- **Land cover source** *(MODIS only)* — NLCD or MCD12Q1
- **Urban & Vegetative classes** *(optional)* — customize which land cover classes define urban and vegetated zones

**6. Run Analysis**

Click **Run Analysis**. Processing typically takes 1–5 minutes depending on AOI size and year range (seasonal mean takes longer).

**Sensitivity testing:** run the same AOI with different month, sensor, land-cover or reference-class settings and compare the CSVs; file names record the settings.

**7. Explore outputs**

| Tab | Contents |
|---|---|
| **Results Table** | Per-year metrics: Urban LST, Vegetated LST, SUHI, Mean LST, NDVI, NDMI, NDBI, land-cover percentages, valid-pixel counts, low-reference flag, Sen's slope, MK p-value. Download as CSV. |
| **Charts** | Annual values with Sen's slope trend line (original series) and a 3-year moving average for visual guidance. Urban vs Vegetated comparison. Download as ZIP of PNGs. |
| **Interactive Map** | Toggle LST, NDVI, NDMI, NDBI, LULC, SUHI (urban-pixel LST minus the reference value) and AOI boundary layers. Select any year. Export rasters to Google Drive. |
| **Land Cover Change** | Pie charts comparing urban/vegetated/other proportions for first and last year. |
| **Shapefile Export** | AOI polygon + per-year center-point features with all metrics as attributes. Download as ZIP. |
| **ERA5 Consistency** | Pearson correlation of satellite LST anomalies with ERA5-Land 2 m air temperature anomalies (consistency check, not validation). |

---


## Local Setup

Run the app on your own machine for development or offline use.

### Prerequisites

- Python 3.10 or later
- A Google Earth Engine account

### Installation

```bash
# Clone the repository
git clone https://github.com/suyogautam/Global-UHI-Analyzer-
cd Global-UHI-Analyzer-

# Install dependencies
pip install -r requirements.txt

# Authenticate with Google Earth Engine (one-time)
earthengine authenticate
```

### Run

```bash
streamlit run App.py
```

The app opens at `http://localhost:8501`.

For local runs, select **"Local / Server (already authenticated)"** on the auth screen and enter your GEE Project ID.

### Tests

```bash
pip install pytest
pytest -q
```

The unit tests (`tests/test_core.py`) cover MODIS scale/offset and QC masking, hottest-month selection, the SUHI difference, land-cover shares (NaN instead of 0 on failure), the seasonal mean, the gap-aware moving average and the trend statistics (checked against SciPy and pymannkendall). They run automatically on GitHub Actions for every push.

### Files

```
App.py                 # Main Streamlit application
uhi_core.py            # Earth Engine-free core logic (scaling, QC, SUHI, trends) used by App.py
auth_handler.py        # GEE authentication UI (hosted and local; in-memory credentials)
ee_folium_map.py       # Folium map wrapper (replaces geemap.foliumap for cloud compatibility)
era5_consistency.py    # ERA5-Land consistency-check tab
requirements.txt       # Python dependencies (exact versions)
tests/                 # pytest unit tests
.github/workflows/     # GitHub Actions: runs the tests
```


## Developer

**Suyog Gautam**

🔗 [GitHub](https://github.com/suyogautam) · 💼 [LinkedIn](https://www.linkedin.com/in/suyog-gautam-76488a253/)

This project is open source. Contributions, forks, and adaptations are welcome — please cite appropriately.

---

## License

See `LICENSE` file in this repository.
