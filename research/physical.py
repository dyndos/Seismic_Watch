"""Physical layers K2-K4 for the offline historical hindcast.

K3 uses half-space triangular dislocations (CUTDE) and resolves the resulting
stress tensor onto explicitly labelled receiver-fault scenarios. When a true
finite-fault model is unavailable, a magnitude-scaled rectangle derived from a
moment-tensor plane is used and clearly marked as a proxy.

K4 is the Dieterich rate-and-state response to a Coulomb stress step. It is not
a direct model of afterslip or viscoelastic relaxation; measured transient
stress histories can be added later as separate input time series.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

MU_PA = 30.0e9
POISSON = 0.25
EFFECTIVE_FRICTION = 0.4
ROOT = Path(__file__).resolve().parents[1]


def _find_coord(ds: Any, names: tuple[str, ...]) -> str | None:
    """Find geographic coordinate arrays; don't mistake projected x/y for degrees."""
    available = {str(k).lower(): str(k) for k in list(ds.coords) + list(ds.variables)}
    for name in names:
        actual = available.get(name.lower())
        if actual is None:
            continue
        candidate = ds[actual]
        if candidate.ndim not in (1, 2):
            continue
        attrs = {str(k).lower(): str(v).lower() for k, v in candidate.attrs.items()}
        units = attrs.get("units", "")
        standard_name = attrs.get("standard_name", "")
        if name.lower() in {"x", "y"}:
            expected = "longitude" if name.lower() == "x" else "latitude"
            if standard_name != expected and "degree" not in units:
                continue
        values = np.asarray(candidate.values, dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        if name.lower() in {"latitude", "lat", "y"} and (
            np.nanmin(finite) < -90.01 or np.nanmax(finite) > 90.01
        ):
            continue
        if name.lower() in {"longitude", "lon", "x"} and (
            np.nanmin(finite) < -360.01 or np.nanmax(finite) > 360.01
        ):
            continue
        return actual
    return None


def _unit_sphere_xyz(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    lat = np.radians(np.asarray(latitude, dtype=float))
    lon = np.radians(np.asarray(longitude, dtype=float))
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))


def load_coupling_cloud(
    coupling_dir: Path | str | None,
    cells: list[dict[str, Any]],
    max_sample_distance_km: float = 350.0,
) -> dict[str, Any]:
    """Sample rectilinear and 2-D curvilinear Coupling Cloud NetCDF grids.

    Sampling is geodesic (unit-sphere nearest-neighbour), handles longitude
    wrapping, and leaves distant cells missing instead of extrapolating.
    """
    from scipy.spatial import cKDTree

    n = len(cells)
    result = {
        "coupling_fraction": np.full(n, np.nan),
        "slip_deficit_mm_yr": np.full(n, np.nan),
        "model_count": np.zeros(n, dtype=int),
        "files_used": [],
        "variables_used": [],
        "unit_rejections": [],
        "unsupported_grids": [],
        "max_sample_distance_km": float(max_sample_distance_km),
    }
    if not coupling_dir:
        return result
    root = Path(coupling_dir)
    if not root.exists():
        return result
    try:
        import xarray as xr
    except ImportError:
        return result

    sums = {
        "coupling_fraction": np.zeros(n, dtype=float),
        "slip_deficit_mm_yr": np.zeros(n, dtype=float),
    }
    counts = {
        "coupling_fraction": np.zeros(n, dtype=int),
        "slip_deficit_mm_yr": np.zeros(n, dtype=int),
    }
    cell_xyz = _unit_sphere_xyz(
        np.asarray([c["latitude"] for c in cells], dtype=float),
        np.asarray([c["longitude"] for c in cells], dtype=float),
    )
    chord_limit = 2.0 * math.sin((max_sample_distance_km / 6371.0088) / 2.0)

    for file in sorted(root.rglob("*.nc")):
        try:
            with xr.open_dataset(file) as ds:
                lat_name = _find_coord(ds, ("latitude", "lat", "y"))
                lon_name = _find_coord(ds, ("longitude", "lon", "x"))
                if not lat_name or not lon_name:
                    result["unsupported_grids"].append({
                        "file": str(file), "reason": "missing_geographic_coordinates",
                    })
                    continue
                lat_coord, lon_coord = ds[lat_name], ds[lon_name]
                lat_values = np.asarray(lat_coord.values, dtype=float)
                lon_values = np.asarray(lon_coord.values, dtype=float)
                if lat_values.ndim == lon_values.ndim == 1:
                    lat_grid, lon_grid = np.meshgrid(lat_values, lon_values, indexing="ij")
                    spatial_dims = (lat_coord.dims[0], lon_coord.dims[0])
                elif (
                    lat_values.ndim == lon_values.ndim == 2
                    and lat_values.shape == lon_values.shape
                    and lat_coord.dims == lon_coord.dims
                ):
                    lat_grid, lon_grid = lat_values, lon_values
                    spatial_dims = tuple(lat_coord.dims)
                else:
                    result["unsupported_grids"].append({
                        "file": str(file), "reason": "unsupported_coordinate_shape",
                        "latitude_shape": list(lat_values.shape),
                        "longitude_shape": list(lon_values.shape),
                    })
                    continue

                coord_valid = (
                    np.isfinite(lat_grid) & np.isfinite(lon_grid)
                    & (lat_grid >= -90.0) & (lat_grid <= 90.0)
                )
                if not np.any(coord_valid):
                    continue
                grid_xyz = _unit_sphere_xyz(lat_grid[coord_valid], lon_grid[coord_valid])
                sampled_any = False
                for var in ds.data_vars:
                    key = str(var).lower().replace("-", "_").replace(" ", "_")
                    if any(token in key for token in ("uncert", "std", "sigma", "error")):
                        continue
                    if "coupl" in key:
                        target = "coupling_fraction"
                    elif "slip" in key and ("deficit" in key or "rate" in key):
                        target = "slip_deficit_mm_yr"
                    else:
                        continue
                    da = ds[var].squeeze(drop=True)
                    if da.ndim != 2 or set(da.dims) != set(spatial_dims):
                        continue
                    values_grid = np.asarray(da.transpose(*spatial_dims).values, dtype=float)
                    if values_grid.shape != lat_grid.shape:
                        continue
                    values = values_grid[coord_valid]
                    value_valid = np.isfinite(values)
                    if not np.any(value_valid):
                        continue
                    units = str(da.attrs.get("units") or "").strip().lower()
                    units_compact = units.replace(" ", "")
                    tree = cKDTree(grid_xyz[value_valid])
                    distances, nearest = tree.query(cell_xyz, k=1)
                    accepted = np.isfinite(distances) & (distances <= chord_limit)
                    sampled = np.full(n, np.nan, dtype=float)
                    if np.any(accepted):
                        sampled[accepted] = values[value_valid][nearest[accepted]]
                    valid = np.isfinite(sampled)
                    if target == "coupling_fraction":
                        if "%" in units_compact or "percent" in units_compact:
                            sampled[valid] /= 100.0
                        elif np.nanmax(sampled[valid], initial=0.0) > 1.5:
                            sampled[valid] /= 100.0
                        sampled[valid] = np.clip(sampled[valid], 0.0, 1.0)
                    else:
                        conversion = {
                            "mm/yr": 1.0, "mm/year": 1.0, "mm/a": 1.0,
                            "cm/yr": 10.0, "cm/year": 10.0, "cm/a": 10.0,
                            "m/yr": 1000.0, "m/year": 1000.0, "m/a": 1000.0,
                            "mm/yr-1": 1.0, "cm/yr-1": 10.0, "m/yr-1": 1000.0,
                        }
                        factor = conversion.get(units_compact)
                        if factor is None:
                            result["unit_rejections"].append({
                                "file": str(file), "variable": str(var),
                                "units": units or None,
                            })
                            continue
                        sampled[valid] *= factor
                    sums[target][valid] += sampled[valid]
                    counts[target][valid] += 1
                    sampled_any = True
                    result["variables_used"].append({
                        "file": str(file), "variable": str(var), "target": target,
                        "original_units": units or None,
                        "sampled_cells": int(np.sum(valid)),
                        "grid_type": "curvilinear" if lat_values.ndim == 2 else "rectilinear",
                    })
                if sampled_any:
                    result["files_used"].append(str(file))
        except Exception as exc:
            result["unsupported_grids"].append({
                "file": str(file), "reason": f"{type(exc).__name__}: {exc}",
            })

    for key in counts:
        valid = counts[key] > 0
        result[key][valid] = sums[key][valid] / counts[key][valid]
    result["model_count"] = np.maximum(
        counts["coupling_fraction"], counts["slip_deficit_mm_yr"]
    )
    result["coupling_coverage_fraction"] = float(
        np.mean(np.isfinite(result["coupling_fraction"]))
    )
    result["slip_deficit_coverage_fraction"] = float(
        np.mean(np.isfinite(result["slip_deficit_mm_yr"]))
    )
    result["any_physical_coverage_fraction"] = float(np.mean(
        np.isfinite(result["coupling_fraction"])
        | np.isfinite(result["slip_deficit_mm_yr"])
    ))
    result["covered_cells"] = int(np.sum(
        np.isfinite(result["coupling_fraction"])
        | np.isfinite(result["slip_deficit_mm_yr"])
    ))
    return result


def _parse_float(props: dict[str, Any], key: str) -> float | None:
    value = props.get(key)
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _extract_moment_tensor(feature: dict[str, Any], as_of_ms: int) -> dict[str, float] | None:
    products = (feature.get("properties") or {}).get("products") or {}
    candidates = []
    for kind in ("moment-tensor", "focal-mechanism"):
        candidates.extend(products.get(kind) or [])
    candidates.sort(key=lambda p: int(p.get("updateTime") or 0), reverse=True)
    for product in candidates:
        updated = product.get("updateTime")
        if updated is None or int(updated) > as_of_ms:
            continue
        props = product.get("properties") or {}
        values = {
            "strike": _parse_float(props, "nodal-plane-1-strike"),
            "dip": _parse_float(props, "nodal-plane-1-dip"),
            "rake": _parse_float(props, "nodal-plane-1-rake"),
            "strike2": _parse_float(props, "nodal-plane-2-strike"),
            "dip2": _parse_float(props, "nodal-plane-2-dip"),
            "rake2": _parse_float(props, "nodal-plane-2-rake"),
            "scalar_moment_nm": _parse_float(props, "scalar-moment"),
        }
        if all(values[k] is not None for k in ("strike", "dip", "rake")):
            return {**values, "product_update_ms": float(updated)}
    return None


def _fault_vectors(strike_deg: float, dip_deg: float, rake_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    strike = math.radians(strike_deg)
    dip = math.radians(dip_deg)
    rake = math.radians(rake_deg)
    along_strike = np.array([math.sin(strike), math.cos(strike), 0.0])
    down_dip = np.array([math.cos(strike) * math.cos(dip),
                         -math.sin(strike) * math.cos(dip),
                         -math.sin(dip)])
    normal = np.cross(along_strike, down_dip)
    normal /= np.linalg.norm(normal)
    slip = math.cos(rake) * along_strike + math.sin(rake) * down_dip
    return along_strike, down_dip, slip


def _magnitude_scaled_rectangle(feature: dict[str, Any], mechanism: dict[str, float]) -> dict[str, Any]:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or [0, 0, 10]
    magnitude = float(props.get("mag") or 0.0)
    if not 5.5 <= magnitude <= 9.5:
        raise ValueError("Magnitude outside the supported range for scaling-law source proxy")
    # Wells & Coppersmith (1994), all-slip-type regressions; width is then
    # capped to a broad seismogenic range to avoid implausible thin rectangles.
    length_km = 10 ** (-3.55 + 0.74 * magnitude)
    area_km2 = 10 ** (-3.49 + 0.91 * magnitude)
    width_km = min(40.0, max(5.0, area_km2 / max(length_km, 1.0)))
    length_km = max(5.0, area_km2 / width_km)
    moment = mechanism.get("scalar_moment_nm")
    if not moment or moment <= 0:
        moment = 10 ** (1.5 * magnitude + 9.1)
    slip_m = float(moment) / (MU_PA * length_km * 1000.0 * width_km * 1000.0)
    dip = float(mechanism["dip"])
    depth_km = float(coords[2] if len(coords) > 2 else 10.0)
    min_centroid_depth = (width_km / 2.0) * math.sin(math.radians(dip)) + 0.5
    depth_km = max(depth_km, min_centroid_depth)
    return {
        "longitude": float(coords[0]), "latitude": float(coords[1]),
        "depth_km": depth_km, "length_km": length_km, "width_km": width_km,
        "strike_deg": float(mechanism["strike"]), "dip_deg": dip,
        "rake_deg": float(mechanism["rake"]), "slip_m": slip_m,
        "quality": "moment_tensor_plus_empirical_rectangle_proxy",
    }


def _extract_finite_fault_geometry(feature: dict[str, Any], as_of_ms: int) -> dict[str, Any] | None:
    """Use the latest finite-fault product geometry available by the forecast cutoff.

    USGS product properties expose model length/width/orientation and scalar
    moment. The geometry is finite-fault-derived, but in the absence of a
    parsed subfault slip grid this adapter assumes uniform average slip and
    labels that approximation explicitly.
    """
    products = (feature.get("properties") or {}).get("products") or {}
    candidates = [
        p for p in (products.get("finite-fault") or [])
        if p.get("updateTime") is not None and int(p["updateTime"]) <= as_of_ms
    ]
    candidates.sort(
        key=lambda p: (int(p.get("preferredWeight") or 0), int(p.get("updateTime") or 0)),
        reverse=True,
    )
    if not candidates:
        return None
    props = candidates[0].get("properties") or {}
    length = _parse_float(props, "model-length")
    width = _parse_float(props, "model-width")
    strike = _parse_float(props, "model-strike")
    dip = _parse_float(props, "model-dip")
    rake = _parse_float(props, "model-rake")
    if not all(v is not None and v > 0 for v in (length, width, dip)) or strike is None or rake is None:
        return None
    if not (1.0 <= length <= 2500.0 and 1.0 <= width <= 300.0 and 0.0 < dip <= 90.0):
        return None
    event_props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or [0, 0, 10]
    lon = _parse_float(props, "hypocenter-lon")
    lat = _parse_float(props, "hypocenter-lat")
    if lon is None:
        lon = float(coords[0])
    if lat is None:
        lat = float(coords[1])
    top_km = _parse_float(props, "model-top")
    depth = _parse_float(props, "hypocenter-z")
    if depth is None:
        depth = float(coords[2] if len(coords) > 2 else 10.0)
    if top_km is not None:
        depth = top_km + 0.5 * width * math.sin(math.radians(dip))
    moment = _parse_float(props, "scalar-moment")
    if moment is None:
        moment = _parse_float(event_props, "moment")
    if moment is None or moment <= 0:
        maximum_slip = _parse_float(props, "maximum-slip")
        if maximum_slip is None or maximum_slip <= 0:
            return None
        slip = maximum_slip
        slip_method = "maximum-slip-product-property_not_average"
    else:
        slip = moment / (MU_PA * (length * 1000.0) * (width * 1000.0))
        slip_method = "uniform_average_from_scalar_moment"
    return {
        "event_id": str(feature.get("id") or "unknown"),
        "longitude": lon, "latitude": lat, "depth_km": max(0.1, float(depth)),
        "length_km": float(length), "width_km": float(width),
        "strike_deg": float(strike) % 360.0,
        "dip_deg": float(dip), "rake_deg": float(rake),
        "slip_m": float(slip),
        "scalar_moment_nm": moment,
        "finite_fault_product_update_ms": int(candidates[0]["updateTime"]),
        "finite_fault_product_source": candidates[0].get("source", "unknown"),
        "slip_method": slip_method,
        "quality": "usgs_finite_fault_geometry_uniform_slip",
    }


def load_source_fault(feature: dict[str, Any], as_of_ms: int,
                      custom_fault_dir: Path | str | None = None) -> dict[str, Any] | None:
    """Prefer a supplied finite fault, then an as-of USGS finite fault, then MT proxy."""
    event_id = str(feature.get("id") or "unknown")
    if custom_fault_dir:
        candidate = Path(custom_fault_dir) / f"{event_id}.json"
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            payload["quality"] = "user_supplied_finite_fault"
            payload["event_id"] = event_id
            return payload

    finite_fault = _extract_finite_fault_geometry(feature, as_of_ms)
    if finite_fault is not None:
        return finite_fault

    mechanism = _extract_moment_tensor(feature, as_of_ms)
    if mechanism is None:
        return None
    source = _magnitude_scaled_rectangle(feature, mechanism)
    source["event_id"] = event_id
    source["mechanism_product_update_ms"] = mechanism["product_update_ms"]
    # The moment tensor has two mathematically admissible nodal planes. Unless
    # a finite-fault product resolves the causative plane, preserve both as
    # alternative source scenarios rather than silently treating NP1 as truth.
    if mechanism.get("strike2") is not None and mechanism.get("dip2") is not None and mechanism.get("rake2") is not None:
        source["alternative_plane"] = {
            "strike_deg": float(mechanism["strike2"]),
            "dip_deg": float(mechanism["dip2"]),
            "rake_deg": float(mechanism["rake2"]),
        }
    source["quality"] = "moment_tensor_plus_empirical_rectangle_proxy"
    return source


def _rectangle_triangles(source: dict[str, Any], transformer: Any) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = source["longitude"], source["latitude"]
    x0, y0 = transformer.transform(lon, lat)
    strike_v, dip_v, slip_v = _fault_vectors(
        source["strike_deg"], source["dip_deg"], source["rake_deg"]
    )
    length = source["length_km"] * 1000.0
    width = source["width_km"] * 1000.0
    center = np.array([x0, y0, -source["depth_km"] * 1000.0])
    p00 = center - 0.5 * length * strike_v - 0.5 * width * dip_v
    p10 = center + 0.5 * length * strike_v - 0.5 * width * dip_v
    p11 = center + 0.5 * length * strike_v + 0.5 * width * dip_v
    p01 = center - 0.5 * length * strike_v + 0.5 * width * dip_v
    triangles = np.asarray([[p00, p10, p11], [p00, p11, p01]], dtype=np.float64)
    slips_efcs = np.asarray([slip_v * source["slip_m"], slip_v * source["slip_m"]], dtype=np.float64)

    from cutde.geometry import compute_efcs_to_tdcs_rotations
    rotations = compute_efcs_to_tdcs_rotations(triangles)
    slips_tdcs = np.ascontiguousarray(np.einsum("nij,nj->ni", rotations, slips_efcs))
    return np.ascontiguousarray(triangles), slips_tdcs


def _receiver_scenarios(cell: dict[str, Any], source: dict[str, Any]) -> list[tuple[float, float, float]]:
    strike = cell.get("boundary_tangent_azimuth_deg")
    if strike is None:
        strike = source["strike_deg"]
    kind = str(cell.get("boundary_type") or "").lower()
    if "subduction" in kind or kind in {"c", "convergent"}:
        return [(strike, dip, 90.0) for dip in (15.0, 30.0, 45.0)]
    if "transform" in kind or kind in {"t", "transcurrent"}:
        return [(strike, 85.0, rake) for rake in (0.0, 180.0)]
    if "diverg" in kind or "spread" in kind or kind in {"d", "r", "ridge"}:
        return [(strike, dip, -90.0) for dip in (50.0, 65.0)]
    # Unknown boundary classification: don't guess one mechanism; retain a
    # small, explicit scenario ensemble.
    return [
        (strike, 90.0, 0.0), (strike, 90.0, 180.0),
        (strike, 30.0, 90.0), (strike, 45.0, 90.0),
        (strike, 55.0, -90.0), (strike, 70.0, -90.0),
    ]


def resolve_coulomb(stress: np.ndarray, strike_deg: float, dip_deg: float,
                    rake_deg: float, friction: float = EFFECTIVE_FRICTION) -> float:
    """Resolve tensile-positive ENU stress (Pa) onto a receiver fault; return MPa."""
    s, d, slip = _fault_vectors(strike_deg, dip_deg, rake_deg)
    normal = np.cross(s, d)
    normal /= np.linalg.norm(normal)
    xx, yy, zz, xy, xz, yz = stress
    tensor = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]], dtype=float)
    traction = tensor @ normal
    shear_change = float(np.dot(traction, slip))
    normal_tension_change = float(np.dot(traction, normal))
    # Tensile-positive normal stress reduces clamping and promotes failure.
    return (shear_change + friction * normal_tension_change) / 1e6


def calculate_delta_cfs(feature: dict[str, Any], as_of_ms: int,
                        cells: list[dict[str, Any]],
                        custom_fault_dir: Path | str | None = None,
                        receiver_depth_km: float = 10.0,
                        max_distance_km: float = 2500.0) -> dict[str, Any] | None:
    """Compute scenario ΔCFS fields using CUTDE elastic half-space dislocations."""
    source = load_source_fault(feature, as_of_ms, custom_fault_dir)
    if source is None:
        return None
    try:
        from cutde import halfspace
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError("K3/K4 require research/requirements.txt (cutde and pyproj)") from exc

    local_crs = (
        f"+proj=aeqd +lat_0={source['latitude']} +lon_0={source['longitude']} "
        "+datum=WGS84 +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    lons = np.asarray([c["longitude"] for c in cells], dtype=float)
    lats = np.asarray([c["latitude"] for c in cells], dtype=float)
    xs, ys = transformer.transform(lons, lats)
    xs, ys = np.asarray(xs), np.asarray(ys)
    distances = np.hypot(xs, ys) / 1000.0
    active = distances <= max_distance_km
    points = np.column_stack([xs, ys, np.full(len(cells), -receiver_depth_km * 1000.0)])

    # Alternative CMT nodal planes are separate mutually exclusive source
    # hypotheses; stress fields are not added together.
    source_scenarios = [source]
    alt = source.get("alternative_plane")
    if alt:
        source_scenarios.append({**source, **alt})
    stress_scenarios: list[np.ndarray] = []
    for source_scenario in source_scenarios:
        triangles, slips = _rectangle_triangles(source_scenario, transformer)
        strain = np.zeros((len(cells), 6), dtype=float)
        if np.any(active):
            strain[active] = halfspace.strain_free(
                points[active].astype(np.float64),
                triangles.astype(np.float64),
                slips.astype(np.float64),
                POISSON,
            )
        stress_scenarios.append(halfspace.strain_to_stress(strain, MU_PA, POISSON))

    cfs = np.full(len(cells), np.nan, dtype=float)
    cfs_p10 = np.full(len(cells), np.nan, dtype=float)
    cfs_p90 = np.full(len(cells), np.nan, dtype=float)
    for i, cell in enumerate(cells):
        if not active[i]:
            continue
        values: list[float] = []
        for source_scenario, stress in zip(source_scenarios, stress_scenarios):
            receivers = _receiver_scenarios(cell, source_scenario)
            values.extend(
                resolve_coulomb(stress[i], strike, dip, rake)
                for strike, dip, rake in receivers
            )
        array = np.asarray(values, dtype=float)
        cfs[i] = float(np.median(array))
        cfs_p10[i] = float(np.percentile(array, 10))
        cfs_p90[i] = float(np.percentile(array, 90))
    return {
        "source": source,
        "source_plane_scenarios": len(source_scenarios),
        "receiver_scenario_ensemble": True,
        "delta_cfs_mpa": cfs,
        "delta_cfs_p10_mpa": cfs_p10,
        "delta_cfs_p90_mpa": cfs_p90,
        "coverage_fraction": float(np.isfinite(cfs).mean()),
        "receiver_depth_km": receiver_depth_km,
        "max_distance_km": max_distance_km,
        "effective_friction": EFFECTIVE_FRICTION,
        "shear_modulus_pa": MU_PA,
        "poisson_ratio": POISSON,
        "stress_sign_convention": "tension-positive; positive ΔCFS promotes receiver-fault failure",
    }


def dieterich_cumulative_count(rate_per_day: np.ndarray | float,
                               delta_cfs_mpa: np.ndarray | float,
                               elapsed_days: float,
                               a_sigma_mpa: float,
                               characteristic_time_days: float) -> np.ndarray:
    """Cumulative Dieterich (1994) count after a Coulomb stress step."""
    if a_sigma_mpa <= 0 or characteristic_time_days <= 0 or elapsed_days < 0:
        raise ValueError("Aσ and t_a must be positive; elapsed time cannot be negative")
    rate = np.asarray(rate_per_day, dtype=float)
    x = np.clip(np.asarray(delta_cfs_mpa, dtype=float) / a_sigma_mpa, -20.0, 20.0)
    ex = np.exp(x)
    inside = ex + (1.0 - ex) * np.exp(-elapsed_days / characteristic_time_days)
    inside = np.maximum(inside, np.finfo(float).tiny)
    cumulative = rate * elapsed_days + rate * characteristic_time_days * np.log(inside)
    return np.maximum(cumulative, 0.0)


def rate_state_ensemble(rate_per_day: np.ndarray,
                        delta_cfs_mpa: np.ndarray,
                        start_elapsed_days: float,
                        end_elapsed_days: float,
                        a_sigma_values_mpa: tuple[float, ...] = (0.03, 0.1, 0.3),
                        characteristic_times_days: tuple[float, ...] = (30.0, 90.0, 365.0)) -> dict[str, np.ndarray]:
    """Expected counts over [start,end] after the stress step; parameters are scenarios."""
    if end_elapsed_days < start_elapsed_days:
        raise ValueError("end_elapsed_days must be >= start_elapsed_days")
    outputs = []
    for a_sigma in a_sigma_values_mpa:
        for t_a in characteristic_times_days:
            before = dieterich_cumulative_count(
                rate_per_day, delta_cfs_mpa, start_elapsed_days, a_sigma, t_a
            )
            after = dieterich_cumulative_count(
                rate_per_day, delta_cfs_mpa, end_elapsed_days, a_sigma, t_a
            )
            outputs.append(np.maximum(after - before, 0.0))
    stack = np.stack(outputs, axis=0)
    return {
        "expected_count_median": np.median(stack, axis=0),
        "expected_count_p10": np.percentile(stack, 10, axis=0),
        "expected_count_p90": np.percentile(stack, 90, axis=0),
        "scenario_count": np.asarray(len(outputs)),
    }
