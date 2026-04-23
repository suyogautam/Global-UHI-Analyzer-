"""
geemap_patch.py  –  Fixes geemap.foliumap BoxKeyError on import.

The bug: foliumap.py line 47 calls `basemaps.xyz_to_folium()` but by that
point `basemaps` has been overwritten by `from .common import *` with
xyzservices.providers (which has no xyz_to_folium). We patch the file in
geemap's installed location before it gets imported.

Import this module at the TOP of App.py, before any geemap import:

    import geemap_patch   # must be first
    import geemap
    import geemap.foliumap as geemap_folium
    ...
"""

import os
import sys


def _patch_foliumap():
    # Find geemap installation path
    import importlib.util
    spec = importlib.util.find_spec("geemap")
    if spec is None:
        return  # geemap not installed, nothing to patch

    geemap_dir = os.path.dirname(spec.origin)
    foliumap_path = os.path.join(geemap_dir, "foliumap.py")

    if not os.path.exists(foliumap_path):
        return

    with open(foliumap_path, "r", encoding="utf-8") as f:
        source = f.read()

    BROKEN_LINE = "basemaps = box.Box(basemaps.xyz_to_folium(), frozen_box=True)"
    FIXED_LINE = (
        "# patched by geemap_patch.py\n"
        "from geemap import basemaps as _geemap_basemaps_module\n"
        "basemaps = box.Box(_geemap_basemaps_module.xyz_to_folium(), frozen_box=True)"
    )

    if BROKEN_LINE not in source:
        # Already patched or different version — nothing to do
        return

    patched = source.replace(BROKEN_LINE, FIXED_LINE, 1)

    try:
        with open(foliumap_path, "w", encoding="utf-8") as f:
            f.write(patched)
        print("[geemap_patch] foliumap.py patched successfully.", file=sys.stderr)
    except OSError as e:
        # Read-only filesystem (rare on Streamlit Cloud) — use import hook instead
        print(f"[geemap_patch] Could not write file ({e}), using import hook.", file=sys.stderr)
        _install_import_hook(BROKEN_LINE, FIXED_LINE)


def _install_import_hook(broken: str, fixed: str):
    """
    Fallback: intercept the import of geemap.foliumap and fix the source
    in memory using a custom loader.
    """
    import importlib
    import importlib.abc
    import importlib.machinery
    import types

    class FoliumapLoader(importlib.abc.SourceLoader):
        def __init__(self, path):
            self._path = path

        def get_filename(self, name):
            return self._path

        def get_data(self, path):
            with open(path, "rb") as f:
                raw = f.read()
            source = raw.decode("utf-8")
            if broken in source:
                source = source.replace(broken, fixed, 1)
            return source.encode("utf-8")

    class FoliumapFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname != "geemap.foliumap":
                return None
            import importlib.util
            spec = importlib.util.find_spec("geemap")
            if spec is None:
                return None
            geemap_dir = os.path.dirname(spec.origin)
            foliumap_path = os.path.join(geemap_dir, "foliumap.py")
            if not os.path.exists(foliumap_path):
                return None
            loader = FoliumapLoader(foliumap_path)
            return importlib.machinery.ModuleSpec(
                fullname,
                loader,
                origin=foliumap_path,
                is_package=False,
            )

    sys.meta_path.insert(0, FoliumapFinder())


# Run patch immediately on import
_patch_foliumap()
