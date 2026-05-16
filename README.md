# 🌡️ Urban Heat Island (UHI) Analyzer

A web-based tool for satellite-derived urban heat island analysis using **Google Earth Engine**, **Landsat**, and **MODIS**. Analyze land surface temperature, spectral indices, and UHI intensity for any city, county, or custom area of interest — from 2000 to present.

**Live app:** [uhi-analyzer.streamlit.app](https://uhi-analyzer.streamlit.app)

---

## Features

- **Dual satellite pipelines** — Landsat Collection 2 (30 m, 2000–present) and MODIS Terra/Aqua merged (1 km, 2000–present)
- **Automatic hottest-month selection** per year from user-defined month set
- **Spectral indices** — LST, NDVI, NDMI, NDBI computed annually
- **UHI intensity** = urban median LST − vegetated median LST
- **Daytime and nighttime LST** (MODIS only)
- **Land cover** — NLCD (30 m, US only) or MODIS MCD12Q1 IGBP (500 m, global, annual)
- **Trend analysis** — Sen's slope + Mann–Kendall on annual values and 3-year moving average
- **ERA5-Land validation** — Pearson correlation of LST anomalies against reanalysis 2 m air temperature
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

The app runs entirely on your own GEE quota. Your credentials are session-only and cleared when you close the tab.

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
- **Land cover source** *(MODIS only)* — NLCD or MCD12Q1
- **Urban & Vegetative classes** *(optional)* — customize which land cover classes define urban and vegetated zones

**6. Run Analysis**

Click **Run Analysis**. Processing typically takes 1–5 minutes depending on AOI size and year range.

**7. Explore outputs**

| Tab | Contents |
|---|---|
| **Results Table** | Per-year metrics: Urban LST, Vegetated LST, UHI, Mean LST, NDVI, NDMI, NDBI, land-cover percentages, Sen's slope, MK p-value. Download as CSV. |
| **Charts** | Annual values + 3-year moving average with trend lines for each metric. Urban vs Vegetated comparison. Download as ZIP of PNGs. |
| **Interactive Map** | Toggle LST, NDVI, NDMI, NDBI, LULC, UHI, and AOI boundary layers. Select any year. Export rasters to Google Drive. |
| **Land Cover Change** | Pie charts comparing urban/vegetated/other proportions for first and last year. |
| **Shapefile Export** | AOI polygon + per-year center-point features with all metrics as attributes. Download as ZIP. |
| **Validation** | Pearson correlation of satellite LST anomalies vs ERA5-Land 2 m air temperature reanalysis. |

---

## Local Setup

Run the app on your own machine for development or offline use.

### Prerequisites

- Python 3.10 or later
- A Google Earth Engine account

### Installation

```bash
# Clone the repository
git clone https://github.com/suyogautam/global-uhi-analyzer
cd global-uhi-analyzer

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

### Files

```
App.py                 # Main Streamlit application
auth_handler.py        # GEE authentication UI (hosted and local)
ee_folium_map.py       # Folium map wrapper (replaces geemap.foliumap for cloud compatibility)
validation_era5.py     # ERA5-Land validation tab
requirements.txt       # Python dependencies
```

---

## Data Sources

| Data | Source | Resolution | Coverage |
|---|---|---|---|
| Landsat LST + SR | USGS Landsat Collection 2 Level-2 (`LANDSAT/LT05`, `LC08`, `LC09`) | 30 m | US-focused, 2000–present |
| MODIS Daytime LST | MOD11A1 + MYD11A1 merged | 1 km | Global, 2000–present |
| MODIS Nighttime LST | MOD11A1 + MYD11A1 merged | 1 km | Global, 2000–present |
| MODIS Surface Reflectance | MOD09GA | 500 m | Global, 2000–present |
| NLCD Land Cover | USGS NLCD Releases 2019/2021 | 30 m | US only, biennial |
| MODIS Land Cover | MCD12Q1 IGBP Type 1 | 500 m | Global, annual 2001–present |
| ERA5-Land | ECMWF ERA5-Land Monthly Aggregated | ~11 km | Global |
| County/City Boundaries | US Census Bureau TIGER/Line 2023 | — | US only |

---

## Methodology Notes

**Hottest month selection** — For each year, the app computes the AOI-median LST for every month in the selected set and picks the month with the highest value. This ensures UHI metrics are always derived from peak thermal conditions rather than a fixed calendar month.

**Outlier filtering (Landsat)** — LST values are clipped to the 5th–95th percentile within the AOI before statistics are computed, reducing the effect of cloud/shadow residuals.

**UHI intensity** — Defined as the difference between median LST over urban pixels and median LST over vegetated pixels, using NLCD or MCD12Q1 land cover to define both classes. Cropland (NLCD class 82) and open water (class 11) are excluded from the vegetated reference.

**Trend analysis** — Sen's slope and Mann–Kendall test are applied separately to the original annual time series and the 3-year centered moving average. Both slope and p-value are reported and included in exports.

**Spectral indices**

| Index | Formula | Bands (L8/L9) | Bands (L5/L7) |
|---|---|---|---|
| NDVI | (NIR − Red) / (NIR + Red) | B5, B4 | B4, B3 |
| NDMI | (NIR − SWIR1) / (NIR + SWIR1) | B5, B6 | B4, B5 |
| NDBI | (SWIR1 − NIR) / (SWIR1 + NIR) | B6, B5 | B5, B4 |


## Developer

**Suyog Gautam**

🔗 [GitHub](https://github.com/suyogautam) · 💼 [LinkedIn](https://www.linkedin.com/in/suyog-gautam-76488a253/)

This project is open source. Contributions, forks, and adaptations are welcome — please cite appropriately.

---

## License

See `LICENSE` file in this repository.
