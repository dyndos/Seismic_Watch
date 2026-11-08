"""USGS Slab2 global subduction-interface geometry loader.

The strike, dip and depth grids are modern static geometry inputs. They are
not time-dependent historical snapshots.
"""
from __future__ import annotations

import math
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import requests

SLAB2_URL = "https://apps.usgs.gov/shakemap_geodata/slabs/slab2.zip"


def download_slab2(destination: Path | str) -> Path:
    """Download and safely extract the official USGS Slab2 grid archive."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.rglob("*_slab2_str_*.grd")):
        return root

    response = requests.get(
        SLAB2_URL, timeout=(30, 300),
        headers={"User-Agent": "Seismic-Watch-research/0.2"},
    )
    response.raise_for_status()
    archive_path = root.parent / "slab2.zip"
    archive_path.write_bytes(response.content)
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                raise RuntimeError(f"Unsafe path in Slab2 archive: {member.filename}")
        archive.extractall(root)
    if not any(root.rglob("*_slab2_str_*.grd")):
        raise RuntimeError("USGS Slab2 archive did not contain strike grids")
    return root


def _coordinate_name(ds: Any, aliases: tuple[str, ...]) -> str | None:
    available = {str(key).lower(): str(key) for key in list(ds.coords) + list(ds.variables)}
    for alias in aliases:
        actual = available.get(alias.lower())
        if actual is None:
            continue
        coord = ds[actual]
        if coord.ndim != 1:
            continue
        values = np.asarray(coord.values, dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        attrs = {str(key).lower(): str(value).lower() for key, value in coord.attrs.items()}
        units = attrs.get("units", "")
        standard = attrs.get("standard_name", "")
        if alias.lower() in {"x", "y"} and "degree" not in units:
            expected = "longitude" if alias.lower() == "x" else "latitude"
            if standard != expected:
                continue
        if alias.lower() in {"latitude", "lat", "y"} and (
            np.nanmin(finite) < -90.01 or np.nanmax(finite) > 90.01
        ):
            continue
        if alias.lower() in {"longitude", "lon", "x"} and (
            np.nanmin(finite) < -360.01 or np.nanmax(finite) > 360.01
        ):
            continue
        return actual
    return None


def _sample_grid(path: Path, cells: list[dict[str, Any]]) -> np.ndarray | None:
    try:
        import xarray as xr
    except ImportError:
        return None

    with xr.open_dataset(path) as ds:
        lat_name = _coordinate_name(ds, ("latitude", "lat", "y"))
        lon_name = _coordinate_name(ds, ("longitude", "lon", "x"))
        if not lat_name or not lon_name:
            return None
        lat_coord, lon_coord = ds[lat_name], ds[lon_name]
        if lat_coord.ndim != 1 or lon_coord.ndim != 1:
            return None
        lat_dim, lon_dim = lat_coord.dims[0], lon_coord.dims[0]
        work = ds.sortby(lat_name).sortby(lon_name)
        lon_values = np.asarray(work[lon_name].values, dtype=float)
        query_lons = np.asarray([c["longitude"] for c in cells], dtype=float)
        if np.nanmin(lon_values) >= 0.0 and np.nanmax(lon_values) > 180.0:
            query_lons = query_lons % 360.0
        else:
            query_lons = (query_lons + 180.0) % 360.0 - 180.0
        query_lats = np.asarray([c["latitude"] for c in cells], dtype=float)

        variable = None
        for name in work.data_vars:
            da = work[name].squeeze(drop=True)
            if da.ndim == 2 and set(da.dims) == {lat_dim, lon_dim}:
                variable = da.transpose(lat_dim, lon_dim)
                break
        if variable is None:
            return None
        sampled = variable.interp(
            {
                lat_name: xr.DataArray(query_lats, dims="point"),
                lon_name: xr.DataArray(query_lons, dims="point"),
            },
            method="nearest",
        ).values
        return np.asarray(sampled, dtype=float).reshape(-1)


def load_slab2(
    slab2_dir: Path | str | None,
    cells: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach nearest Slab2 strike/dip/depth values to the equal-area cells."""
    root = Path(slab2_dir) if slab2_dir else None
    n = len(cells)
    strike_sin = np.zeros(n, dtype=float)
    strike_cos = np.zeros(n, dtype=float)
    dip_sum = np.zeros(n, dtype=float)
    depth_sum = np.zeros(n, dtype=float)
    orientation_count = np.zeros(n, dtype=int)
    depth_count = np.zeros(n, dtype=int)
    used_regions: list[str] = []
    used_files: list[str] = []
    errors: list[dict[str, str]] = []

    if root is not None and root.exists():
        strike_files = sorted(root.rglob("*_slab2_str_*.grd"))
        for strike_file in strike_files:
            marker = "_slab2_str_"
            prefix, version = strike_file.name.split(marker, 1)
            dip_file = strike_file.with_name(f"{prefix}_slab2_dip_{version}")
            depth_file = strike_file.with_name(f"{prefix}_slab2_dep_{version}")
            if not dip_file.exists():
                errors.append({"file": str(dip_file), "reason": "missing_matching_dip_grid"})
                continue
            try:
                strikes = _sample_grid(strike_file, cells)
                dips = _sample_grid(dip_file, cells)
                depths = _sample_grid(depth_file, cells) if depth_file.exists() else None
                if strikes is None or dips is None:
                    errors.append({
                        "file": str(strike_file),
                        "reason": "unsupported_grid_coordinates_or_data_dimensions",
                    })
                    continue
                valid = (
                    np.isfinite(strikes) & np.isfinite(dips)
                    & (strikes >= 0.0) & (strikes <= 360.0)
                    & (dips > 0.0) & (dips <= 90.0)
                )
                if not np.any(valid):
                    continue
                radians = np.radians(2.0 * strikes[valid])
                strike_sin[valid] += np.sin(radians)
                strike_cos[valid] += np.cos(radians)
                dip_sum[valid] += dips[valid]
                orientation_count[valid] += 1
                if depths is not None:
                    depth_values = np.abs(depths)
                    depth_valid = valid & np.isfinite(depth_values) & (
                        (depth_values > 0.1) & (depth_values <= 700.0)
                    )
                    depth_sum[depth_valid] += depth_values[depth_valid]
                    depth_count[depth_valid] += 1
                used_regions.append(prefix)
                used_files.extend(
                    [str(strike_file), str(dip_file)]
                    + ([str(depth_file)] if depth_file.exists() else [])
                )
            except Exception as exc:
                errors.append({
                    "file": str(strike_file),
                    "reason": f"{type(exc).__name__}: {exc}",
                })

    has_orientation = orientation_count > 0
    has_depth = depth_count > 0
    strikes_out = np.full(n, np.nan, dtype=float)
    dips_out = np.full(n, np.nan, dtype=float)
    depths_out = np.full(n, np.nan, dtype=float)
    strikes_out[has_orientation] = (
        np.degrees(
            0.5 * np.arctan2(
                strike_sin[has_orientation], strike_cos[has_orientation]
            )
        ) % 180.0
    )
    dips_out[has_orientation] = dip_sum[has_orientation] / orientation_count[has_orientation]
    depths_out[has_depth] = depth_sum[has_depth] / depth_count[has_depth]

    for index, cell in enumerate(cells):
        cell["slab2_strike_deg"] = (
            float(strikes_out[index]) if has_orientation[index] else None
        )
        cell["slab2_dip_deg"] = (
            float(dips_out[index]) if has_orientation[index] else None
        )
        cell["slab2_depth_km"] = (
            float(depths_out[index]) if has_depth[index] else None
        )
        cell["slab2_model_count"] = int(orientation_count[index])

    manifest = {
        "source": "USGS Slab2 global subduction-interface geometry",
        "url": "https://doi.org/10.5066/F7PV6JNV",
        "download_url": SLAB2_URL,
        "grid_spacing_degrees": 0.05,
        "regions_used": sorted(set(used_regions)),
        "files_used": sorted(set(used_files)),
        "strike_dip_coverage_fraction": float(np.mean(has_orientation)),
        "depth_coverage_fraction": float(np.mean(has_depth)),
        "cells_with_strike_dip": int(np.sum(has_orientation)),
        "cells_with_depth": int(np.sum(has_depth)),
        "grid_errors": errors,
        "time_dependent": False,
    }
    return cells, manifest
