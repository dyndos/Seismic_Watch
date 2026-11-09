"""Exact GEAR1-style log-linear combination of two global parent rate grids.

Inputs are parent earthquake rate densities in events / km^2 / year on the
same global grid. The parent grids must be fully defined and strictly positive;
missing physical coverage is not imputed here. This module combines parents
but does not recreate Kagan-Jackson smoothing or SHIFT-GSRM2f generation.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DAYS_PER_YEAR = 365.25
PREFERRED_SEISMICITY_EXPONENT = 0.6


def combine_parent_rates(
    seismicity_rate_density: np.ndarray,
    tectonic_rate_density: np.ndarray,
    cell_area_km2: np.ndarray,
    target_global_rate_per_year: float,
    seismicity_exponent: float = PREFERRED_SEISMICITY_EXPONENT,
    floor_rate_density: float | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Combine GEAR1 parent forecasts and normalize their global rate.

    The published log-linear combination is:
        H' = max(S**d * T**(1-d), f)
        H  = f + (H' - f) * (R - G*f) / (sum(A*H') - G*f)

    where A is cell area, G=sum(A), R is the requested global event rate and
    f is the minimum positive rate density. The preferred published GEAR1
    exponent is d=0.6 on the smoothed seismicity parent.
    """
    seismicity = np.asarray(seismicity_rate_density, dtype=np.float64)
    tectonic = np.asarray(tectonic_rate_density, dtype=np.float64)
    area = np.asarray(cell_area_km2, dtype=np.float64)

    if seismicity.shape != tectonic.shape or seismicity.shape != area.shape:
        raise ValueError("Both parent grids and cell areas must have identical shapes")
    if seismicity.size == 0:
        raise ValueError("Parent grids cannot be empty")
    if not (0.0 <= seismicity_exponent <= 1.0):
        raise ValueError("seismicity_exponent must be between 0 and 1")
    if not np.all(np.isfinite(seismicity)) or not np.all(np.isfinite(tectonic)):
        raise ValueError("Parent grids must be complete; NaN/inf inputs are not imputed")
    if np.any(seismicity <= 0.0) or np.any(tectonic <= 0.0):
        raise ValueError("Parent rate densities must be strictly positive")
    if not np.all(np.isfinite(area)) or np.any(area <= 0.0):
        raise ValueError("Every cell must have a finite positive area")
    if not np.isfinite(target_global_rate_per_year) or target_global_rate_per_year <= 0:
        raise ValueError("target_global_rate_per_year must be finite and positive")

    floor = float(
        min(np.min(seismicity), np.min(tectonic))
        if floor_rate_density is None else floor_rate_density
    )
    if not np.isfinite(floor) or floor <= 0:
        raise ValueError("floor_rate_density must be finite and positive")

    raw = np.maximum(
        np.power(seismicity, seismicity_exponent)
        * np.power(tectonic, 1.0 - seismicity_exponent),
        floor,
    )
    earth_area = float(np.sum(area))
    floor_integral = floor * earth_area
    raw_integral = float(np.sum(raw * area))
    excess = raw_integral - floor_integral
    target_excess = target_global_rate_per_year - floor_integral

    if target_excess < -1e-10:
        raise ValueError(
            "Target global rate is below the minimum floor integrated over Earth"
        )
    if excess <= 0.0:
        if abs(target_excess) > 1e-10:
            raise ValueError("Uniform floor parent cannot be normalized to requested rate")
        combined = np.full_like(raw, floor)
        scale = 0.0
    else:
        scale = max(0.0, target_excess / excess)
        combined = floor + (raw - floor) * scale

    achieved = float(np.sum(combined * area))
    if not np.isclose(achieved, target_global_rate_per_year, rtol=1e-9, atol=1e-10):
        raise ArithmeticError(
            f"Global-rate normalization failed: expected {target_global_rate_per_year}, got {achieved}"
        )
    metadata = {
        "seismicity_exponent": float(seismicity_exponent),
        "tectonic_exponent": float(1.0 - seismicity_exponent),
        "floor_rate_density_per_km2_year": floor,
        "global_area_km2": earth_area,
        "raw_hybrid_global_rate_per_year": raw_integral,
        "target_global_rate_per_year": float(target_global_rate_per_year),
        "achieved_global_rate_per_year": achieved,
        "normalization_scale": float(scale),
    }
    return combined, metadata


def cell_expected_count(
    rate_density_per_km2_year: np.ndarray,
    cell_area_km2: np.ndarray,
    duration_days: float,
) -> np.ndarray:
    if not np.isfinite(duration_days) or duration_days < 0:
        raise ValueError("duration_days must be finite and non-negative")
    rate = np.asarray(rate_density_per_km2_year, dtype=np.float64)
    area = np.asarray(cell_area_km2, dtype=np.float64)
    if rate.shape != area.shape:
        raise ValueError("rate and cell-area arrays must have identical shapes")
    if not np.all(np.isfinite(rate)) or np.any(rate < 0):
        raise ValueError("rates must be finite and non-negative")
    if not np.all(np.isfinite(area)) or np.any(area <= 0):
        raise ValueError("cell areas must be finite and positive")
    return rate * area * (duration_days / DAYS_PER_YEAR)


def poisson_probability_at_least_one(expected_count: np.ndarray) -> np.ndarray:
    """Poisson conversion; only valid if the selected event count is Poisson."""
    mu = np.asarray(expected_count, dtype=np.float64)
    if not np.all(np.isfinite(mu)) or np.any(mu < 0):
        raise ValueError("expected_count must be finite and non-negative")
    return -np.expm1(-mu)


def regional_probability_at_least_one(
    rate_density_per_km2_year: np.ndarray,
    cell_area_km2: np.ndarray,
    duration_days: float,
) -> float:
    """Aggregate disjoint Poisson cells using their summed expected count."""
    mu = cell_expected_count(rate_density_per_km2_year, cell_area_km2, duration_days)
    return float(-np.expm1(-np.sum(mu)))


def run(parent_npz: Path, output_dir: Path, target_rate: float,
        exponent: float = PREFERRED_SEISMICITY_EXPONENT) -> dict[str, Any]:
    with np.load(parent_npz, allow_pickle=False) as archive:
        required = {"seismicity_rate_density", "tectonic_rate_density", "cell_area_km2"}
        missing = required - set(archive.files)
        if missing:
            raise ValueError(f"Parent NPZ is missing arrays: {sorted(missing)}")
        s = archive["seismicity_rate_density"].astype(np.float64)
        t = archive["tectonic_rate_density"].astype(np.float64)
        a = archive["cell_area_km2"].astype(np.float64)
        coords = {
            name: archive[name]
            for name in ("latitude", "longitude")
            if name in archive.files
        }
    combined, meta = combine_parent_rates(s, t, a, target_rate, exponent)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_dir / "gear1_style_baseline.npz",
        rate_density_per_km2_year=combined,
        expected_count_30d=cell_expected_count(combined, a, 30.0),
        probability_30d=poisson_probability_at_least_one(
            cell_expected_count(combined, a, 30.0)
        ),
        expected_count_90d=cell_expected_count(combined, a, 90.0),
        probability_90d=poisson_probability_at_least_one(
            cell_expected_count(combined, a, 90.0)
        ),
        cell_area_km2=a,
        **coords,
    )
    manifest = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method": "GEAR1 published log-linear parent combination",
        "input_npz": str(parent_npz),
        "input_sha256": __import__("hashlib").sha256(parent_npz.read_bytes()).hexdigest(),
        **meta,
        "time_dependence": "none; this is a stationary long-term rate surface",
        "probability_conversion": "Poisson 1-exp(-mu); use only as a long-term rate conversion, not for clustered short-term ETAS counts",
        "required_parent_provenance": [
            "seismicity parent source, catalogue window, magnitude/depth threshold, smoothing method and grid",
            "tectonic parent source, GSRM version, strain-rate units, tectonic classes, coupling/thickness assumptions and grid",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parents", type=Path, required=True,
                        help="NPZ with global parent rates and per-cell areas")
    parser.add_argument("--target-global-rate", type=float, required=True,
                        help="Expected shallow events per year at the selected magnitude threshold")
    parser.add_argument("--seismicity-exponent", type=float, default=PREFERRED_SEISMICITY_EXPONENT)
    parser.add_argument("--output", type=Path, default=Path("research/outputs/gear1-baseline"))
    args = parser.parse_args()
    manifest = run(args.parents, args.output, args.target_global_rate, args.seismicity_exponent)
    print(f"GEAR1-style baseline normalized to {manifest['achieved_global_rate_per_year']:.6g} events/year")
    print(args.output / "gear1_style_baseline.npz")


if __name__ == "__main__":
    main()
