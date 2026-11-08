"""Statistical and physics-augmented spatial rate models for historical hindcasts."""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.physical import rate_state_ensemble

DAYS_PER_YEAR = 365.25


def _feature_array(cells: list[dict[str, Any]], coupling: dict[str, Any] | None = None,
                   use_coupling: bool = False) -> np.ndarray:
    columns = []
    for key in (
        "relative_speed_mm_yr",
        "normal_velocity_mm_yr",
        "parallel_velocity_mm_yr",
        "boundary_distance_km",
    ):
        values = np.asarray([
            np.nan if c.get(key) is None else float(c[key]) for c in cells
        ])
        if key == "boundary_distance_km":
            values = np.log1p(values)
        columns.append(values)
    azimuths = np.asarray([
        np.nan if c.get("motion_azimuth_deg") is None else np.radians(float(c["motion_azimuth_deg"]))
        for c in cells
    ])
    columns.extend([np.sin(azimuths), np.cos(azimuths)])
    if use_coupling:
        if coupling is None:
            coupling = {}
        columns.append(np.asarray(coupling.get("coupling_fraction", np.full(len(cells), np.nan)), dtype=float))
        columns.append(np.asarray(coupling.get("slip_deficit_mm_yr", np.full(len(cells), np.nan)), dtype=float))
        columns.append(np.log1p(np.asarray(coupling.get("model_count", np.zeros(len(cells))), dtype=float)))
    return np.column_stack(columns)


def count_training_events(events: list[dict[str, Any]], cells: list[dict[str, Any]],
                          start_ms: int, cutoff_ms: int,
                          min_magnitude: float = 6.0) -> tuple[np.ndarray, int]:
    """Assign historical events to the nearest equal-area cell, with one count/event."""
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    xy = np.asarray([[c["x_m"], c["y_m"]] for c in cells], dtype=float)
    tree = cKDTree(xy)
    counts = np.zeros(len(cells), dtype=float)
    eligible = 0
    forward = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    for event in events:
        props = event.get("properties") or {}
        t = int(props.get("time") or 0)
        mag = props.get("mag")
        if not (start_ms <= t < cutoff_ms) or mag is None or float(mag) < min_magnitude:
            continue
        coords = (event.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        x, y = forward.transform(float(coords[0]), float(coords[1]))
        _, index = tree.query([x, y], k=1)
        counts[int(index)] += 1.0
        eligible += 1
    return counts, eligible


def fit_spatial_rate_models(cells: list[dict[str, Any]], counts: np.ndarray,
                            training_years: float,
                            coupling: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fit K0-K2 using data strictly before the supplied cutoff."""
    if training_years <= 0:
        raise ValueError("training_years must be positive")
    n = len(cells)
    global_rate = max(float(np.sum(counts)) / max(training_years, 1e-6), 1e-8)
    prior_count = max(1e-4, 0.01 * float(np.sum(counts)) / max(n, 1))
    k0 = (counts + prior_count) / (training_years + 1.0)

    def fit(features: np.ndarray, alpha: float) -> tuple[np.ndarray, str]:
        finite = np.isfinite(features)
        if not np.any(finite):
            return k0.copy(), "no_physical_feature_coverage"
        model = Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("poisson", PoissonRegressor(alpha=alpha, max_iter=1000, tol=1e-7)),
        ])
        try:
            model.fit(features, counts)
            prediction = np.asarray(model.predict(features), dtype=float)
            prediction = np.maximum(prediction, prior_count * 0.02)
            return prediction / (training_years + 1.0), "ok"
        except Exception as exc:
            return k0.copy(), f"fallback:{type(exc).__name__}"

    k1_features = _feature_array(cells)
    k1, k1_status = fit(k1_features, alpha=5.0)

    coupling = coupling or {}
    coupling_values = np.asarray(coupling.get("coupling_fraction", np.full(n, np.nan)), dtype=float)
    slip_values = np.asarray(coupling.get("slip_deficit_mm_yr", np.full(n, np.nan)), dtype=float)
    coverage = np.isfinite(coupling_values) | np.isfinite(slip_values)
    coverage_cells = int(np.sum(coverage))
    coverage_fraction = float(np.mean(coverage))
    # Coupling Cloud is regional by design. Do not discard useful subduction
    # observations because the global-grid coverage is below 2%.
    minimum_coverage_cells = max(8, int(0.005 * n))
    if coverage_cells >= minimum_coverage_cells:
        k2_features = _feature_array(cells, coupling, use_coupling=True)
        k2, k2_status = fit(
            k2_features, alpha=20.0 if coverage_fraction < 0.05 else 8.0
        )
        if k2_status == "ok" and coverage_fraction < 0.05:
            k2_status = "ok_partial_coverage"
    else:
        k2 = k1.copy()
        k2_status = "not_scored_insufficient_coupling_coverage"

    return {
        "K0": k0,
        "K1": k1,
        "K2": k2,
        "status": {
            "K0": "ok",
            "K1": k1_status,
            "K2": k2_status,
        },
        "coupling_coverage_fraction": coverage_fraction,
        "coupling_covered_cells": coverage_cells,
        "training_event_count": int(np.sum(counts)),
        "global_annual_rate": global_rate,
    }


def probabilities_from_rate(rate_per_year: np.ndarray, days: float) -> np.ndarray:
    expected = np.maximum(rate_per_year, 0.0) * days / DAYS_PER_YEAR
    return np.clip(1.0 - np.exp(-expected), 0.0, 1.0)


def forecast_k3(rate_per_year: np.ndarray, delta_cfs_mpa: np.ndarray,
                interval_days: float,
                a_sigma_values_mpa: tuple[float, ...] = (0.03, 0.1, 0.3)) -> dict[str, np.ndarray]:
    """Instantaneous post-step rate ratio exp(ΔCFS/Aσ), integrated over an interval."""
    rates = []
    for a_sigma in a_sigma_values_mpa:
        x = np.clip(np.asarray(delta_cfs_mpa, dtype=float) / a_sigma, -5.0, 5.0)
        adjusted = np.asarray(rate_per_year, dtype=float) * np.exp(x)
        rates.append(probabilities_from_rate(adjusted, interval_days))
    stack = np.stack(rates, axis=0)
    return {
        "probability": np.nanmedian(stack, axis=0),
        "probability_p10": np.nanpercentile(stack, 10, axis=0),
        "probability_p90": np.nanpercentile(stack, 90, axis=0),
    }


def forecast_k4(rate_per_year: np.ndarray, delta_cfs_mpa: np.ndarray,
                start_elapsed_days: float,
                end_elapsed_days: float) -> dict[str, np.ndarray]:
    """Dieterich time-dependent expected rate over an interval after stress step."""
    rate_day = np.asarray(rate_per_year, dtype=float) / DAYS_PER_YEAR
    ensemble = rate_state_ensemble(
        rate_day, delta_cfs_mpa, start_elapsed_days, end_elapsed_days
    )
    expected = ensemble["expected_count_median"]
    expected_p10 = ensemble["expected_count_p10"]
    expected_p90 = ensemble["expected_count_p90"]
    return {
        "probability": np.clip(1.0 - np.exp(-expected), 0.0, 1.0),
        "probability_p10": np.clip(1.0 - np.exp(-expected_p10), 0.0, 1.0),
        "probability_p90": np.clip(1.0 - np.exp(-expected_p90), 0.0, 1.0),
    }
