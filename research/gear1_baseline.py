"""Reproduce the GEAR1 source-code blend from two prepared parent rate grids.

This module reproduces only the final S/T hybrid operation in Bird's released
GEAR1_for_CSEP source. It does NOT generate the Kagan-Jackson or SHIFT-GSRM2f
parent maps. Inputs are event-rate densities in events / km^2 / year on the
same global grid, with matching per-cell areas.
"""
from __future__ import annotations

import argparse
import hashlib
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
    seismicity_exponent: float = PREFERRED_SEISMICITY_EXPONENT,
    target_global_rate_override_per_year: float | None = None,
) -> tuple[np.ndarray, dict[str, float | str]]:
    """Apply the normalization used in Bird's released GEAR1 Fortran source.

    With S and T denoting the two parent rate-density maps and A cell area,
    the source computes:

        R_S = sum(A*S); R_T = sum(A*T)
        R_target = R_S**d * R_T**(1-d)
        S_min = min(S); T_min = min(T)
        H_floor = max(S_min**d * T_min**(1-d), min(S_min, T_min))
        H_raw = max(S**d * T**(1-d), H_floor)
        H = H_floor + c * (H_raw - H_floor)

    where c = (R_target - area(H_floor)) /
              (area(H_raw) - area(H_floor)).

    The optional target override is an experimental calibration variant, not
    the default released-source GEAR1 normalization.
    """
    seismicity = np.asarray(seismicity_rate_density, dtype=np.float64)
    tectonic = np.asarray(tectonic_rate_density, dtype=np.float64)
    area = np.asarray(cell_area_km2, dtype=np.float64)

    if seismicity.shape != tectonic.shape or seismicity.shape != area.shape:
        raise ValueError("Both parent grids and cell areas must have identical shapes")
    if seismicity.size == 0:
        raise ValueError("Parent grids cannot be empty")
    if not np.isfinite(seismicity_exponent) or not (0.0 <= seismicity_exponent <= 1.0):
        raise ValueError("seismicity_exponent must be finite and between 0 and 1")
    if not np.all(np.isfinite(seismicity)) or not np.all(np.isfinite(tectonic)):
        raise ValueError("Parent grids must be complete; NaN/inf inputs are not imputed")
    if np.any(seismicity <= 0.0) or np.any(tectonic <= 0.0):
        raise ValueError("Parent rate densities must be strictly positive")
    if not np.all(np.isfinite(area)) or np.any(area <= 0.0):
        raise ValueError("Every cell must have a finite positive area")

    d = float(seismicity_exponent)
    tectonic_exponent = 1.0 - d
    global_area = float(np.sum(area, dtype=np.float64))
    seismicity_global_rate = float(np.sum(seismicity * area, dtype=np.float64))
    tectonic_global_rate = float(np.sum(tectonic * area, dtype=np.float64))
    if seismicity_global_rate <= 0.0 or tectonic_global_rate <= 0.0:
        raise ValueError("Both parent maps must have positive global event rates")

    source_target_rate = (
        seismicity_global_rate**d * tectonic_global_rate**tectonic_exponent
    )
    if target_global_rate_override_per_year is None:
        target_rate = source_target_rate
        normalization_mode = "released_gear1_parent_integral_rule"
    else:
        target_rate = float(target_global_rate_override_per_year)
        if not np.isfinite(target_rate) or target_rate <= 0.0:
            raise ValueError("target_global_rate_override_per_year must be finite and positive")
        normalization_mode = "experimental_global_rate_override"

    seismicity_floor = float(np.min(seismicity))
    tectonic_floor = float(np.min(tectonic))
    hybrid_floor = max(
        seismicity_floor**d * tectonic_floor**tectonic_exponent,
        min(seismicity_floor, tectonic_floor),
    )
    raw = np.maximum(
        np.power(seismicity, d) * np.power(tectonic, tectonic_exponent),
        hybrid_floor,
    )
    floor_integral = hybrid_floor * global_area
    raw_integral = float(np.sum(raw * area, dtype=np.float64))
    denominator = raw_integral - floor_integral
    numerator = target_rate - floor_integral

    tolerance = max(1e-14, abs(target_rate) * 1e-12)
    if denominator <= 0.0:
        if abs(numerator) <= tolerance:
            correction = 0.0
            combined = np.full_like(raw, hybrid_floor)
        else:
            raise ValueError("The hybrid parent has no spatial contrast to normalize")
    else:
        if numerator < -tolerance:
            raise ValueError(
                "Target global rate is below the integrated GEAR1 hybrid floor"
            )
        correction = numerator / denominator
        if not np.isfinite(correction) or correction < 0.0:
            raise ValueError("GEAR1 floor-preserving normalization is not feasible")
        combined = hybrid_floor + correction * (raw - hybrid_floor)

    achieved = float(np.sum(combined * area, dtype=np.float64))
    if not np.isclose(achieved, target_rate, rtol=1e-9, atol=tolerance):
        raise ArithmeticError(
            f"Global-rate normalization failed: expected {target_rate}, got {achieved}"
        )

    metadata: dict[str, float | str] = {
        "normalization_mode": normalization_mode,
        "seismicity_exponent": d,
        "tectonic_exponent": tectonic_exponent,
        "seismicity_parent_global_rate_per_year": seismicity_global_rate,
        "tectonic_parent_global_rate_per_year": tectonic_global_rate,
        "source_target_global_rate_per_year": source_target_rate,
        "target_global_rate_per_year": target_rate,
        "seismicity_floor_rate_density_per_km2_year": seismicity_floor,
        "tectonic_floor_rate_density_per_km2_year": tectonic_floor,
        "hybrid_floor_rate_density_per_km2_year": hybrid_floor,
        "global_area_km2": global_area,
        "raw_hybrid_global_rate_per_year": raw_integral,
        "floor_integrated_rate_per_year": floor_integral,
        "normalization_correction": float(correction),
        "achieved_global_rate_per_year": achieved,
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


def run(
    parent_npz: Path,
    output_dir: Path,
    target_rate_override: float | None = None,
    exponent: float = PREFERRED_SEISMICITY_EXPONENT,
) -> dict[str, Any]:
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
    combined, meta = combine_parent_rates(
        s, t, a, exponent, target_global_rate_override_per_year=target_rate_override
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    mu30 = cell_expected_count(combined, a, 30.0)
    mu90 = cell_expected_count(combined, a, 90.0)
    np.savez_compressed(
        output_dir / "gear1_style_baseline.npz",
        rate_density_per_km2_year=combined,
        expected_count_30d=mu30,
        probability_30d=poisson_probability_at_least_one(mu30),
        expected_count_90d=mu90,
        probability_90d=poisson_probability_at_least_one(mu90),
        cell_area_km2=a,
        **coords,
    )
    digest = hashlib.sha256(parent_npz.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method": "GEAR1 released-source S/T floor-preserving blend",
        "input_npz": str(parent_npz),
        "input_sha256": digest,
        "reproduction_scope": "final parent-map combination only; parent-map generation is not implemented by this module",
        **meta,
        "time_dependence": "none; this is a stationary long-term rate surface",
        "probability_conversion": "Poisson 1-exp(-mu); a rate conversion only, not an ETAS short-term forecast",
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
    parser.add_argument("--target-global-rate", type=float, default=None,
                        help="Experimental override; omit to use the released GEAR1 parent-integral normalization")
    parser.add_argument("--seismicity-exponent", type=float, default=PREFERRED_SEISMICITY_EXPONENT)
    parser.add_argument("--output", type=Path, default=Path("research/outputs/gear1-baseline"))
    args = parser.parse_args()
    manifest = run(args.parents, args.output, args.target_global_rate, args.seismicity_exponent)
    print(
        f"GEAR1 hybrid normalized to "
        f"{manifest['achieved_global_rate_per_year']:.6g} events/year "
        f"({manifest['normalization_mode']})"
    )
    print(args.output / "gear1_style_baseline.npz")


if __name__ == "__main__":
    main()
