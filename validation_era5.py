import ee
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import pearsonr
import streamlit as st
import io
import zipfile
import matplotlib.pyplot as plt

ERA5_COLLECTION = "ECMWF/ERA5_LAND/MONTHLY_AGGR"  # Changed to ERA5-Land (better for land surfaces)


def get_era5_monthly_t2m(aoi, year, month):
    """
    Fetch ERA5-Land monthly mean 2m air temperature.
    ERA5-Land has better spatial resolution (9km vs 25km) for land surfaces.
    """
    try:
        # ERA5-Land collection
        col = (
            ee.ImageCollection(ERA5_COLLECTION)
            .filter(ee.Filter.calendarRange(year, year, "year"))
            .filter(ee.Filter.calendarRange(month, month, "month"))
            .select("temperature_2m")  # ERA5-Land band name
        )

        # Check if collection has data
        size = col.size().getInfo()
        if size == 0:
            st.warning(f"No ERA5 data for {year}-{month:02d}")
            return None

        # Get mean image
        img = col.mean()

        # Convert Kelvin → Celsius
        img_c = img.subtract(273.15)

        # Reduce region with error handling
        stats = img_c.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=11132,  # ERA5-Land native resolution (~11km)
            maxPixels=1e9,
            bestEffort=True
        )

        # Get value with explicit error handling
        t2m_val = stats.get("temperature_2m")
        
        if t2m_val is None:
            return None
            
        result = ee.Number(t2m_val).getInfo()
        
        # Sanity check: ERA5 temperatures should be reasonable (-50 to 50°C)
        if result is not None and (-50 < result < 50):
            return result
        else:
            st.warning(f"Unrealistic ERA5 value for {year}-{month:02d}: {result}")
            return None
            
    except Exception as e:
        st.warning(f"ERA5 retrieval failed for {year}-{month:02d}: {str(e)}")
        return None


def compute_era5_anomalies(aoi, years, hottest_months):
    """
    Compute ERA5 temperature anomalies for each year's hottest month.
    """
    records = []
    
    # Progress indicator
    progress_bar = st.progress(0.0, text="Fetching ERA5 validation data...")

    for i, year in enumerate(years):
        month = hottest_months.get(year)
        
        if month is None:
            st.warning(f"No hottest month recorded for {year}")
            records.append({"year": year, "month": None, "t2m": None})
            continue
        
        # Update progress
        progress_bar.progress((i + 1) / len(years), text=f"Fetching ERA5 for {year}-{month:02d}...")
        
        # Get ERA5 temperature
        t2m = get_era5_monthly_t2m(aoi, year, month)
        
        records.append({
            "year": year,
            "month": month,
            "t2m": t2m
        })

    progress_bar.empty()
    
    df = pd.DataFrame(records)
    
    # Convert to numeric and handle missing data
    df["t2m"] = pd.to_numeric(df["t2m"], errors="coerce")
    
    # Drop rows where ERA5 data is missing
    valid_mask = df["t2m"].notna()
    n_missing = (~valid_mask).sum()
    
    if n_missing > 0:
        st.warning(f"⚠️ ERA5 data unavailable for {n_missing} year(s). These will be excluded from correlation.")
    
    # Compute anomalies only for valid data
    if valid_mask.sum() > 0:
        df["t2m_anomaly"] = df["t2m"] - df.loc[valid_mask, "t2m"].mean()
    else:
        df["t2m_anomaly"] = np.nan

    return df


def plot_timeseries(df):
    """Plot LST and ERA5 anomalies over time using Plotly."""
    valid = df.dropna(subset=["lst_anomaly", "t2m_anomaly"])

    _TEXT = '#1a1a1a'
    _GRID = '#d4d4d4'

    fig = go.Figure()

    if valid.empty:
        fig.add_annotation(text="No valid data to plot", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14, color=_TEXT))
        return fig

    fig.add_trace(go.Scatter(
        x=valid["year"], y=valid["lst_anomaly"],
        mode='lines+markers', name='LST anomaly (satellite)',
        line=dict(color='#e74c3c', width=2.2),
        marker=dict(size=8, symbol='circle'),
        hovertemplate='%{x}: %{y:.3f} °C<extra>LST anomaly</extra>'
    ))

    fig.add_trace(go.Scatter(
        x=valid["year"], y=valid["t2m_anomaly"],
        mode='lines+markers', name='ERA5 T2m anomaly (reanalysis)',
        line=dict(color='#3498db', width=2.2),
        marker=dict(size=8, symbol='square'),
        hovertemplate='%{x}: %{y:.3f} °C<extra>ERA5 T2m</extra>'
    ))

    fig.add_hline(y=0, line=dict(color='#888', dash='dash', width=1), opacity=0.7)

    fig.update_layout(
        title=dict(text='LST vs ERA5 Air Temperature Anomalies',
                   font=dict(size=14, color=_TEXT), x=0.0, xanchor='left'),
        xaxis=dict(
            title=dict(text='Year', font=dict(color=_TEXT, size=11)),
            tickformat='d', tickfont=dict(color=_TEXT, size=10),
            gridcolor=_GRID, linecolor='#888', zeroline=False
        ),
        yaxis=dict(
            title=dict(text='Temperature Anomaly (°C)', font=dict(color=_TEXT, size=11)),
            tickfont=dict(color=_TEXT, size=10),
            gridcolor=_GRID, linecolor='#888', zeroline=False
        ),
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        legend=dict(font=dict(size=10, color=_TEXT), bgcolor='rgba(255,255,255,0.92)',
                    bordercolor='#aaa', borderwidth=1),
        hovermode='x unified',
        margin=dict(l=65, r=20, t=55, b=55),
        height=420
    )
    return fig


def plot_scatter(df, r, p):
    """Scatter plot of LST vs ERA5 anomalies using Plotly."""
    valid = df.dropna(subset=["lst_anomaly", "t2m_anomaly"])

    _TEXT = '#1a1a1a'
    _GRID = '#d4d4d4'

    fig = go.Figure()

    if valid.empty:
        fig.add_annotation(text="No valid data to plot", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False, font=dict(size=14, color=_TEXT))
        return fig

    x = valid["t2m_anomaly"].values
    y = valid["lst_anomaly"].values
    years_labels = valid["year"].astype(int).astype(str).tolist()

    m_coef, b_coef = np.polyfit(x, y, 1)
    x_line = np.linspace(x.min(), x.max(), 100)
    y_line = m_coef * x_line + b_coef

    fig.add_trace(go.Scatter(
        x=x_line, y=y_line, mode='lines',
        name=f'y = {m_coef:.2f}x + {b_coef:.2f}',
        line=dict(color='#e74c3c', width=2, dash='dash')
    ))

    fig.add_trace(go.Scatter(
        x=x, y=y, mode='markers+text',
        name='Year observations',
        marker=dict(size=11, color='#2c7bb6', line=dict(color='#1a1a1a', width=1.2)),
        text=years_labels,
        textposition='top center',
        textfont=dict(size=9, color=_TEXT),
        hovertemplate='ERA5: %{x:.3f} °C<br>LST: %{y:.3f} °C<br>Year: %{text}<extra></extra>'
    ))

    fig.update_layout(
        title=dict(text=f'LST vs ERA5 Correlation<br><sup>r = {r:.3f}, p = {p:.4f}</sup>',
                   font=dict(size=13, color=_TEXT), x=0.0, xanchor='left'),
        xaxis=dict(
            title=dict(text='ERA5 T2m Anomaly (°C)', font=dict(color=_TEXT, size=11)),
            tickfont=dict(color=_TEXT, size=10),
            gridcolor=_GRID, linecolor='#888', zeroline=True, zerolinecolor='#bbb'
        ),
        yaxis=dict(
            title=dict(text='LST Anomaly (°C)', font=dict(color=_TEXT, size=11)),
            tickfont=dict(color=_TEXT, size=10),
            gridcolor=_GRID, linecolor='#888', zeroline=True, zerolinecolor='#bbb'
        ),
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        legend=dict(font=dict(size=9, color=_TEXT), bgcolor='rgba(255,255,255,0.92)',
                    bordercolor='#aaa', borderwidth=1),
        margin=dict(l=65, r=20, t=70, b=55),
        height=430
    )
    return fig


def render_validation_tab():
    """Main validation tab rendering function."""
    st.subheader("🌡️ LST Validation against ERA5 Reanalysis")
    
    st.markdown("""
    This validation compares satellite-derived LST anomalies against **ERA5-Land** 2m air temperature reanalysis data.
    
    - **Purpose**: Verify that LST trends align with independent climate data
    - **Method**: Pearson correlation between temperature anomalies
    - **Data**: ERA5-Land monthly aggregated 2m air temperature (~11 km resolution)
    """)
    
    # Check if main analysis has been run
    if "analysis_results" not in st.session_state:
        st.warning("⚠️ Please run the main UHI analysis first (in the sidebar).")
        return

    res = st.session_state["analysis_results"]

    # Extract necessary data
    aoi = res["aoi"].geometry()  # Convert FeatureCollection to Geometry
    years = res["years"]
    hottest_months = res["hottest_months"]
    lst_df = res["lst_df"].copy()

    # Fetch ERA5 data
    with st.spinner("Fetching ERA5 validation data from Google Earth Engine..."):
        era5_df = compute_era5_anomalies(aoi, years, hottest_months)

    # Merge datasets
    validation_df = lst_df.merge(era5_df, on="year", how="left")
    
    # Remove rows with missing data
    valid_df = validation_df.dropna(subset=["lst_anomaly", "t2m_anomaly"])
    
    if len(valid_df) < 3:
        st.error("❌ Insufficient valid data for correlation analysis (need at least 3 years).")
        st.dataframe(validation_df)
        return

    # Compute correlation
    try:
        r, p = pearsonr(valid_df["lst_anomaly"], valid_df["t2m_anomaly"])
    except Exception as e:
        st.error(f"❌ Correlation calculation failed: {e}")
        st.dataframe(validation_df)
        return

    # Display metrics
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Pearson Correlation (r)", f"{r:.3f}")
    with col2:
        st.metric("P-value", f"{p:.4f}")
    with col3:
        significance = "✅ Significant" if p < 0.05 else "⚠️ Not significant"
        st.metric("Statistical Significance (α=0.05)", significance)

    # Interpretation
    if r > 0.7 and p < 0.05:
        st.success("✅ **Strong positive correlation** - LST measurements are well-validated!")
    elif r > 0.4 and p < 0.05:
        st.info("ℹ️ **Moderate correlation** - LST shows reasonable agreement with ERA5.")
    elif p >= 0.05:
        st.warning("⚠️ **Not statistically significant** - More years of data may be needed.")
    else:
        st.warning("⚠️ **Weak correlation** - Check for data quality issues or local effects.")

    st.markdown("---")
    
    # Display data table
    st.subheader("Validation Dataset")
    display_df = validation_df.copy()
    display_df["year"] = display_df["year"].astype(int)
    st.dataframe(display_df, use_container_width=True)

    # Generate plots
    st.markdown("---")
    st.subheader("Visualization")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("**Time Series Comparison**")
        fig_ts = plot_timeseries(valid_df)
        st.plotly_chart(fig_ts, use_container_width=True)
    
    with col_b:
        st.markdown("**Correlation Scatter Plot**")
        fig_sc = plot_scatter(valid_df, r, p)
        st.plotly_chart(fig_sc, use_container_width=True)

    # Downloads
    st.markdown("---")
    st.subheader("📥 Downloads")
    
    col_dl1, col_dl2 = st.columns(2)
    
    with col_dl1:
        csv = validation_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📄 Download Validation CSV",
            csv,
            "LST_ERA5_validation.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col_dl2:
        # Create ZIP with static matplotlib plots for download
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            valid_plot = valid_df.dropna(subset=["lst_anomaly", "t2m_anomaly"])

            # Time-series PNG
            fig_ts_mpl, ax_ts = plt.subplots(figsize=(10, 5))
            ax_ts.plot(valid_plot["year"], valid_plot["lst_anomaly"], marker="o", linewidth=2,
                       markersize=8, label="LST anomaly (satellite)", color="#e74c3c")
            ax_ts.plot(valid_plot["year"], valid_plot["t2m_anomaly"], marker="s", linewidth=2,
                       markersize=8, label="ERA5 T2m anomaly (reanalysis)", color="#3498db")
            ax_ts.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.7)
            ax_ts.set_xlabel("Year", fontsize=11); ax_ts.set_ylabel("Temperature Anomaly (°C)", fontsize=11)
            ax_ts.legend(fontsize=10); ax_ts.set_title("LST vs ERA5 Anomalies", fontsize=13, fontweight='bold')
            ax_ts.grid(True, alpha=0.3); plt.tight_layout()
            ts_buf = io.BytesIO()
            fig_ts_mpl.savefig(ts_buf, format='png', dpi=300, bbox_inches="tight")
            ts_buf.seek(0); z.writestr("validation_timeseries.png", ts_buf.read())
            plt.close(fig_ts_mpl)

            # Scatter PNG
            x_sc = valid_plot["t2m_anomaly"].values; y_sc = valid_plot["lst_anomaly"].values
            m_sc, b_sc = np.polyfit(x_sc, y_sc, 1)
            fig_sc_mpl, ax_sc = plt.subplots(figsize=(6, 6))
            ax_sc.scatter(x_sc, y_sc, s=100, alpha=0.7, edgecolors='black', linewidth=1.5)
            for _, row in valid_plot.iterrows():
                ax_sc.annotate(int(row["year"]), (row["t2m_anomaly"], row["lst_anomaly"]),
                               fontsize=8, ha='center', va='bottom', xytext=(0, 5), textcoords='offset points')
            x_ln = np.linspace(x_sc.min(), x_sc.max(), 100)
            ax_sc.plot(x_ln, m_sc*x_ln+b_sc, 'r--', linewidth=2, label=f'y={m_sc:.2f}x+{b_sc:.2f}')
            ax_sc.set_xlabel("ERA5 T2m Anomaly (°C)", fontsize=11); ax_sc.set_ylabel("LST Anomaly (°C)", fontsize=11)
            ax_sc.set_title(f"LST vs ERA5  r={r:.3f}, p={p:.4f}", fontsize=12, fontweight='bold')
            ax_sc.grid(True, alpha=0.3); ax_sc.legend(fontsize=9); plt.tight_layout()
            sc_buf = io.BytesIO()
            fig_sc_mpl.savefig(sc_buf, format='png', dpi=300, bbox_inches="tight")
            sc_buf.seek(0); z.writestr("validation_scatter.png", sc_buf.read())
            plt.close(fig_sc_mpl)
        
        buf.seek(0)
        st.download_button(
            "📊 Download Validation Plots (ZIP)",
            buf.getvalue(),
            "validation_plots.zip",
            "application/zip",
            use_container_width=True
        )