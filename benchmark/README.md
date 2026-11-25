# Benchmark and sensitivity runs (SoftwareX revision)

Files supporting Sections 2.3 and 3.1 of the SoftwareX article.

## End-to-end benchmark
`benchmark_notebook_vs_app_14cities.csv` compares annual SUHI from the app with an
independent copy of the Earth Engine pipeline run in a separate notebook (MODIS Terra + Aqua,
hottest month of June–August, NLCD, Census place boundary with the recommended buffer,
2000–2024), for 14 U.S. cities, day and night.

- `max_abs_diff_C`: largest absolute difference between the two annual SUHI values in any year (°C)
- `mean_abs_diff_C`: mean absolute annual difference (°C)
- `identical_years`: years with identical values (difference < 0.005 °C)

Twelve cities are identical in all 25 years. Atlanta and Chicago differ in one year each
(maximum absolute annual difference 0.08 and 0.14 °C).

## Option sensitivity (Table 3)
`04_softwarex_option_sensitivity.ipynb` runs the app's processing for eight cities and
seven settings (default; Terra only; Aqua only; fixed June, July, August; vegetated reference
without NLCD class 21). Set A = random draw (seed 2026), Set B = one city per contrasting climate.

- `runs/`: one CSV per city, setting and day/night, in the app's export format
- `option_sensitivity_by_city_set*.csv`, `option_sensitivity_summary_set*.csv`,
  `option_sensitivity_setA_vs_setB.csv`: differences from the default (mean, mean absolute,
  Pearson r, difference in Sen's slope in °C per decade). Aqua-only comparisons use 2003–2024
  for both series.
- `trend_test_comparison_set*.csv`: Sen's slope and Mann–Kendall p of the default series,
  original and Hamed–Rao tests on the raw series, and the original test on the 3-year moving
  average (for comparison only; the app no longer uses it).

Re-running needs an Earth Engine account; set `EE_PROJECT` in the first code cell.
