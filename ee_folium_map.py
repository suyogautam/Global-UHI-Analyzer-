"""
ee_folium_map.py  –  Drop-in replacement for geemap.foliumap.Map.

Avoids importing geemap.foliumap (which crashes on Streamlit Cloud due to a
geemap bug where `from .common import *` overwrites the local `basemaps`
name with xyzservices.providers, which no longer has xyz_to_folium()).

This module re-implements only the methods App.py actually calls:
  - Map(center, zoom)
  - m.addLayer(ee_image, vis_params, name)
  - m.add_legend(legend_title, legend_dict)
  - m.addLayerControl() / m.add_layer_control()
  - m.add_child(child)   ← used by add_continuous_colorbar via branca
"""

from __future__ import annotations
import json
import ee
import folium
from folium import plugins


# ── EE → tile URL helper ──────────────────────────────────────────────────────

def _sanitize_vis_params(vis_params: dict) -> dict:
    """
    Convert vis_params into the format the EE Python API's getMapId() expects.

    The EE API internally calls .split() on param values to detect
    comma-separated strings (e.g. palette). On Streamlit Cloud (newer
    earthengine-api versions), passing raw Python int/float for min/max
    causes "float object has no attribute 'split'" deep inside EE's
    data serialization layer.

    Fix: convert all scalar numeric values to strings, and convert list
    values (palette) to a comma-joined string — exactly what EE expects.
    """
    safe = {}
    for k, v in vis_params.items():
        if isinstance(v, list):
            # EE accepts palette as comma-joined string or list — use string
            # to be safe across all API versions
            safe[k] = ",".join(str(x) for x in v)
        elif isinstance(v, (int, float)):
            # Must be a string so EE's internal .split() calls don't crash
            safe[k] = str(v)
        else:
            safe[k] = v
    return safe


def _ee_image_to_tile_url(image: ee.Image, vis_params: dict) -> str:
    """
    Get a map tile URL from an Earth Engine image.
    Returns a plain string URL, guaranteed — raises on failure.

    Uses image.getMapId() (instance method) instead of ee.data.getMapId()
    because the instance method handles serialization internally and is
    more stable across earthengine-api versions on hosted environments.
    """
    safe_params = _sanitize_vis_params(vis_params)
    try:
        # Preferred: use the image instance method (more stable)
        map_id_dict = image.getMapId(safe_params)
    except Exception:
        # Fallback: use ee.data.getMapId with image embedded in params
        map_id_dict = ee.data.getMapId({**safe_params, "image": image})

    url = map_id_dict["tile_fetcher"].url_format
    if not isinstance(url, str):
        raise TypeError(f"EE tile_fetcher returned non-string URL: {type(url)} {url!r}")
    return url


# ── Map class ─────────────────────────────────────────────────────────────────

class Map(folium.Map):
    """
    Minimal geemap.foliumap.Map replacement.
    Inherits from folium.Map and adds addLayer / add_legend / addLayerControl.
    """

    def __init__(self, center=(0, 0), zoom=3, **kwargs):
        # folium.Map uses location=[lat, lon], zoom_start
        super().__init__(
            location=list(center),
            zoom_start=zoom,
            tiles="OpenStreetMap",
            **{k: v for k, v in kwargs.items() if k not in ("center", "zoom")},
        )
        self._layer_control_added = False

    # ── addLayer ─────────────────────────────────────────────────────────────

    def addLayer(
        self,
        ee_object,
        vis_params: dict | None = None,
        name: str = "Layer",
        shown: bool = True,
        opacity: float = 1.0,
    ):
        """Add an Earth Engine image as a tile layer."""
        if vis_params is None:
            vis_params = {}

        try:
            # Resolve EE object to an Image
            if isinstance(ee_object, ee.Image):
                img = ee_object
            elif isinstance(ee_object, ee.ImageCollection):
                img = ee_object.mosaic()
            else:
                # FeatureCollection / Geometry — paint as raster outline
                img = ee.Image().byte().paint(ee_object, 1, 2)

            # Get tile URL — this is where 'split' errors originate if vis_params
            # contains raw int/float min/max. _ee_image_to_tile_url sanitizes them.
            url = _ee_image_to_tile_url(img, vis_params)

            folium.TileLayer(
                tiles=url,
                attr="Google Earth Engine",
                name=name,
                overlay=True,
                control=True,
                show=shown,
                opacity=opacity,
            ).add_to(self)

        except Exception as e:
            import streamlit as st
            st.warning(f"⚠️ Could not add layer '{name}': {e}")

    # ── add_legend ───────────────────────────────────────────────────────────

    def add_legend(
        self,
        legend_title: str = "Legend",
        legend_dict: dict | None = None,
        position: str = "bottomright",
        **kwargs,
    ):
        """Add an HTML legend to the map."""
        if not legend_dict:
            return

        items_html = "".join(
            f'<div style="display:flex;align-items:center;margin-bottom:4px">'
            f'<div style="background:{color};width:16px;height:16px;'
            f'margin-right:8px;border:1px solid #555;flex-shrink:0"></div>'
            f'<span style="font-size:12px">{label}</span></div>'
            for label, color in legend_dict.items()
        )

        legend_html = f"""
        <div id="legend" style="
            position: fixed;
            bottom: 30px; right: 10px;
            z-index: 1000;
            background: rgba(255,255,255,0.92);
            border: 1px solid #aaa;
            border-radius: 6px;
            padding: 10px 14px;
            font-family: Arial, sans-serif;
            max-height: 300px;
            overflow-y: auto;
            box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
        ">
            <b style="font-size:13px">{legend_title}</b><br><br>
            {items_html}
        </div>
        """
        self.get_root().html.add_child(folium.Element(legend_html))

    # ── layer control ────────────────────────────────────────────────────────

    def addLayerControl(self):
        if not self._layer_control_added:
            folium.LayerControl(collapsed=False).add_to(self)
            self._layer_control_added = True

    def add_layer_control(self):
        self.addLayerControl()
