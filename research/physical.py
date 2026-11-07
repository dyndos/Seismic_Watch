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
    for name in names:
        if name in ds.coords:
            return name
        if name in ds.variables and ds[name].ndim == 1:
            return name
    return None


def load_coupling_cloud(coupling_dir: Path | str | None,
                        cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Sample downloaded Coupling Cloud NetCDF files at equal-area cell centres.

    No value is imputed as zero. Coverage is returned explicitly. Files should
    be downloaded from https://couplingcloud.ucsd.edu/download/all_models and
    extracted under research/data/coupling_cloud/.
    """
    n = len(cells)
    result = {
        "coupling_fraction": np.full(n, np.nan),
        "slip_deficit_mm_yr": np.full(n, np.nan),
        "model_count": np.zeros(n, dtype=int),
        "files_used": [],
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

    sums = {"coupling_fraction": np.zeros(n), "slip_deficit_mm_yr": np.zeros(n)}
    counts = {"coupling_fraction": np.zeros(n, dtype=int), "slip_deficit_mm_yr": np.zeros(n, dtype=int)}
    lats = np.array([c["latitude"] for c in cells], dtype=float)
    lons = np.array([c["longitude"] for c in cells], dtype=float)

    for file in sorted(root.rglob("*.nc")):
        try:
            with xr.open_dataset(file) as ds:
                lat_name = _find_coord(ds, ("latitude", "lat", "y"))
                lon_name = _find_coord(ds, ("longitude", "lon", "x"))
                if not lat_name or not lon_name:
                    continue
                lat_coord = ds[lat_name]
                lon_coord = ds[lon_name]
                if lat_coord.ndim != 1 or lon_coord.ndim != 1:
                    continue
                work = ds.sortby(lat_name)
                work = work.sortby(lon_name)
                lon_values = np.asarray(work[lon_name].values, dtype=float)
                if np.nanmin(lon_values) >= 0 and np.nanmax(lon_values) > 180:
                    query_lons = lons % 360.0
                else:
                    query_lons = (lons + 180.0) % 360.0 - 180.0
                query = {
                    lat_name: xr.DataArray(lats, dims="point"),
                    lon_name: xr.DataArray(query_lons, dims="point"),
                }
                sampled_any = False
                for var in work.data_vars:
                    key = var.lower().replace("-", "_").replace(" ", "_")
                    if "uncert" in key or "std" in key or "sigma" in key:
                        continue
                    if "coupl" in key:
                        target = "coupling_fraction"
                    elif "slip" in key and ("deficit" in key or "rate" in key):
                        target = "slip_deficit_mm_yr"
                    else:
                        continue
                    da = work[var].squeeze(drop=True)
                    if lat_name not in da.dims or lon_name not in da.dims or da.ndim != 2:
                        continue
                    values = np.asarray(da.interp(query, method="nearest").values, dtype=float).reshape(-1)
                    valid = np.isfinite(values)
                    if target == "coupling_fraction":
                        # Some published models are percent (0..100), others fraction (0..1).
                        if np.nanmax(values[valid], initial=0) > 1.5:
                            values[valid] = values[valid] / 100.0
                        values = np.clip(values, 0.0, 1.0)
                    sums[target][valid] += values[valid]
                    counts[target][valid] += 1
                    sampled_any = True
                if sampled_any:
                    result["files_used"].append(str(file))
        except Exception:
            # One malformed or unsupported model must not suppress other regions.
            continue

    for key in counts:
        valid = counts[key] > 0
        result[key][valid] = sums[key][valid] / counts[key][valid]
    result["model_count"] = np.maximum(counts["coupling_fraction"], counts["slip_deficit_mm_yr"])
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


def load_source_fault(feature: dict[str, Any], as_of_ms: int,
                      custom_fault_dir: Path | str | None = None) -> dict[str, Any] | None:
    """Load a normalized finite-fault file, otherwise a dated moment tensor proxy."""
    event_id = str(feature.get("id") or "unknown")
    if custom_fault_dir:
        candidate = Path(custom_fault_dir) / f"{event_id}.json"
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            payload["quality"] = "user_supplied_finite_fault"
            payload["event_id"] = event_id
            return payload
    mechanism = _extract_moment_tensor(feature, as_of_ms)
    if mechanism is None:
        return None
    source = _magnitude_scaled_rectangle(feature, mechanism)
    source["event_id"] = event_id
    source["mechanism_product_update_ms"] = mechanism["product_update_ms"]
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
    slips_tdcs = np.einsum("nij,nj->ni", rotations, slips_efcs)
    return triangles, slips_tdcs


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
    """Compute a stress-transfer scenario map using CUTDE's elastic half-space TDEs."""
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
    triangles, slips = _rectangle_triangles(source, transformer)
    lons = np.asarray([c["longitude"] for c in cells], dtype=float)
    lats = np.asarray([c["latitude"] for c in cells], dtype=float)
    xs, ys = transformer.transform(lons, lats)
    xs, ys = np.asarray(xs), np.asarray(ys)
    distances = np.hypot(xs, ys) / 1000.0
    active = distances <= max_distance_km
    points = np.column_stack([xs, ys, np.full(len(cells), -receiver_depth_km * 1000.0)])
    strain = np.zeros((len(cells), 6), dtype=float)
    if np.any(active):
        strain[active] = halfspace.strain_free(
            points[active].astype(np.float64),
            triangles.astype(np.float64),
            slips.astype(np.float64),
            POISSON,
        )
    stress = halfspace.strain_to_stress(strain, MU_PA, POISSON)

    cfs = np.full(len(cells), np.nan, dtype=float)
    cfs_p10 = np.full(len(cells), np.nan, dtype=float)
    cfs_p90 = np.full(len(cells), np.nan, dtype=float)
    for i, cell in enumerate(cells):
        if not active[i]:
            continue
        scenarios = _receiver_scenarios(cell, source)
        values = np.asarray([
            resolve_coulomb(stress[i], strike, dip, rake)
            for strike, dip, rake in scenarios
        ], dtype=float)
        cfs[i] = float(np.median(values))
        cfs_p10[i] = float(np.percentile(values, 10))
        cfs_p90[i] = float(np.percentile(values, 90))
    return {
        "source": source,
        "delta_cfs_mpa": cfs,
        "delta_cfs_p10_mpa": cfs_p10,
        "delta_cfs_p90_mpa": cfs_p90,
        "coverage_fraction": float(np.isfinite(cfs).mean()),
        "receiver_depth_km": receiver_depth_km,
        "max_distance_km": max_distance_km,
        "effective_friction": EFFECTIVE_FRICTION,
        "shear_modulus_pa": MU_PA,
        "poisson_ratio": POISSON,
    }


def diet_erich_expected_count(rate_per_day: np.ndarray | float,
                              delta_cfs_mpa: np.ndarray | float,
                              days: float,
                              a_sigma_mpa: float,
                              characteristic_time_days: float) -> np.ndarray:
    """Dieterich (1994) cumulative count after a Coulomb stress step.

    N(T) = r*T + r*t_a*ln[exp(x) + (1-exp(x))*exp(-T/t_a)],
    x = ΔCFS/(Aσ). Both Aσ and ΔCFS are in MPa; time is in days.
    """
    if a_sigma_mpa <= 0 or characteristic_time_days <= 0 or days < 0:
        raise ValueError("Aσ and t_a must be positive; horizon cannot be negative")
    rate = np.asarray(rate_per_day, dtype=float)
    x = np.clip(np.asarray(delta_cfs_mpa, dtype=float) / a_sigma_mpa, -20.0, 20.0)
    ex = np.exp(x)
    inside = ex + (1.0 - ex) * np.exp(-days / characteristic_time_days)
    inside = np.maximum(inside, np.finfo(float).tiny)
    expected = rate * days + rate * characteristic_time_days * np.log(inside)
    return np.maximum(expected, 0.0)


def rate_state_ensemble(rate_per_day: np.ndarray,
                        delta_cfs_mpa: np.ndarray,
                        days: float,
                        a_sigma_values_mpa: tuple[float, ...] = (0.03, 0.1, 0.3),
                        characteristic_times_days: tuple[float, ...] = (30.0, 90.0, 365.0)) -> dict[str, np.ndarray]:
    """Parameter-sensitivity ensemble; these are scenarios, not fitted constants."""
    outputs = []
    for a_sigma in a_sigma_values_mpa:
        for t_a in characteristic_times_days:
            outputs.append(diet_erich_expected_count(
                rate_per_day, delta_cfs_mpa, days, a_sigma, t_a
            ))
    stack = np.stack(outputs, axis=0)
    return {
        "expected_count_median": np.median(stack, axis=0),
        "expected_count_p10": np.percentile(stack, 10, axis=0),
        "expected_count_p90": np.percentile(stack, 90, axis=0),
        "scenario_count": np.asarray(len(outputs)),
    }
