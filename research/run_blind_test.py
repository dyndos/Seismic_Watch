"""Reproducible blind-style historical hindcast for K0-K4.

Phase 1 writes immutable forecast snapshots using events strictly before each
cutoff. Phase 2 reads future events only to score those already-written files.
Current ComCat is not a historical archive; results are labelled
occurrence-time hindcasts, not strict reconstructions of what the USGS site
displayed on each historical day.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import gzip
import io
import zipfile
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
from pyproj import Transformer
from scipy.spatial import cKDTree

from research.kinematics import (
    ROOT, annotate_grid, equal_area_grid, load_boundary_segments, load_morvel,
)
from research.modeling import (
    fit_spatial_rate_models, forecast_k3, forecast_k4,
    probabilities_from_rate, count_training_events,
)
from research.physical import calculate_delta_cfs, load_coupling_cloud

USGS_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
DAY_MS = 86_400_000
HORIZONS_DAYS = (1, 3, 7, 14, 30, 90, 180, 365)
MODEL_NAMES = ("K0", "K1", "K2", "K3", "K4")
MIN_TRAIN_MAG = 6.5
TARGET_MAG = 6.5


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def parse_time_ms(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_catalog(start: str, end: str, min_magnitude: float) -> list[dict[str, Any]]:
    params = {
        "format": "geojson",
        "starttime": start,
        "endtime": end,
        "minmagnitude": str(min_magnitude),
        "orderby": "time-asc",
        "limit": "20000",
    }
    response = requests.get(USGS_QUERY, params=params, timeout=90,
                            headers={"User-Agent": "Seismic-Watch-research/0.1"})
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if len(features) >= 20_000:
        raise RuntimeError("USGS returned the 20,000-event limit; split the date range into smaller windows.")
    return features


def fetch_event_detail(event_id: str) -> dict[str, Any] | None:
    response = requests.get(
        USGS_QUERY,
        params={"format": "geojson", "eventid": event_id},
        timeout=45,
        headers={"User-Agent": "Seismic-Watch-research/0.1"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if payload.get("type") == "Feature":
        return payload
    features = payload.get("features") or []
    return features[0] if features else None


def catalog_hash(features: list[dict[str, Any]]) -> str:
    raw = json.dumps(features, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_time(feature: dict[str, Any]) -> int:
    return int((feature.get("properties") or {}).get("time") or 0)


def _event_mag(feature: dict[str, Any]) -> float:
    value = (feature.get("properties") or {}).get("mag")
    return float(value) if value is not None else float("-inf")


def select_cutoffs(catalog: list[dict[str, Any]], start_year: int, end_year: int,
                   max_triggers: int, include_controls: bool) -> list[dict[str, Any]]:
    start_ms = int(datetime(start_year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(end_year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    candidates = [
        e for e in catalog
        if start_ms <= _event_time(e) < end_ms and _event_mag(e) >= TARGET_MAG
    ]
    candidates.sort(key=_event_time)
    if max_triggers > 0 and len(candidates) > max_triggers:
        # Deterministic evenly spaced sampling over the whole predeclared interval.
        indexes = np.linspace(0, len(candidates) - 1, max_triggers, dtype=int)
        candidates = [candidates[int(i)] for i in indexes]

    cutoffs: list[dict[str, Any]] = []
    for feature in candidates:
        origin_ms = _event_time(feature)
        cutoff_ms = origin_ms + 7 * DAY_MS
        cutoffs.append({
            "cutoff_id": f"trigger_{feature.get('id')}",
            "kind": "major_event_trigger",
            "trigger_event_id": feature.get("id"),
            "trigger_origin_ms": origin_ms,
            "cutoff_ms": cutoff_ms,
            "cutoff_rule": "origin_time_plus_7_days",
        })
    if include_controls:
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                cutoff_ms = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)
                cutoffs.append({
                    "cutoff_id": f"control_{year}-{month:02d}-01",
                    "kind": "calendar_control",
                    "trigger_event_id": None,
                    "trigger_origin_ms": None,
                    "cutoff_ms": cutoff_ms,
                    "cutoff_rule": "first_day_of_month_00_utc",
                })
    dedup = {}
    for item in cutoffs:
        dedup[item["cutoff_id"]] = item
    return sorted(dedup.values(), key=lambda c: c["cutoff_ms"])


def assign_outcomes_to_grid(events: list[dict[str, Any]],
                            cells: list[dict[str, Any]],
                            cutoff_ms: int, days: int,
                            min_magnitude: float = TARGET_MAG,
                            start_days: int = 0) -> tuple[np.ndarray, list[int], list[dict[str, Any]]]:
    """Assign events in (cutoff+start_days, cutoff+days] to the nearest grid cell."""
    xy = np.asarray([[c["x_m"], c["y_m"]] for c in cells], dtype=float)
    tree = cKDTree(xy)
    forward = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    positives = np.zeros(len(cells), dtype=np.uint8)
    indices: list[int] = []
    matched: list[dict[str, Any]] = []
    start_ms = cutoff_ms + start_days * DAY_MS
    end_ms = cutoff_ms + days * DAY_MS
    for event in events:
        props = event.get("properties") or {}
        t = int(props.get("time") or 0)
        mag = props.get("mag")
        if not (start_ms < t <= end_ms) or mag is None or float(mag) < min_magnitude:
            continue
        coords = (event.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        x, y = forward.transform(float(coords[0]), float(coords[1]))
        distance, index = tree.query([x, y], k=1)
        idx = int(index)
        positives[idx] = 1
        indices.append(idx)
        matched.append({
            "id": event.get("id"),
            "time": utc_iso(t),
            "magnitude": float(mag),
            "longitude": float(coords[0]),
            "latitude": float(coords[1]),
            "cell_id": cells[idx]["cell_id"],
            "days_after_cutoff": round((t - cutoff_ms) / DAY_MS, 3),
            "cell_assignment_distance_km": round(float(distance) / 1000.0, 2),
        })
    return positives, indices, matched

def score_spatial_probability(probability: np.ndarray, outcomes: np.ndarray,
                               event_indices: list[int], cells: list[dict[str, Any]]) -> dict[str, Any]:
    valid = np.isfinite(probability)
    if not np.any(valid):
        return {"status": "no_probability_surface"}
    p = np.clip(probability[valid], 1e-9, 1 - 1e-9)
    y = outcomes[valid].astype(float)
    brier = float(np.mean((p - y) ** 2))
    logloss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    valid_indexes = np.flatnonzero(valid)
    order = valid_indexes[np.argsort(-probability[valid])]
    n_events = len(event_indices)
    metrics: dict[str, Any] = {
        "status": "ok",
        "brier_spatial": brier,
        "log_loss_spatial": logloss,
        "observed_events": n_events,
        "unique_positive_cells": int(np.sum(outcomes)),
        "mean_cell_probability": float(np.mean(probability[valid])),
        "global_probability_any_event_approx": float(1 - np.prod(1 - np.clip(probability[valid], 0, 1))),
    }
    for pct in (5, 10, 20):
        n_top = max(1, int(math.ceil(len(order) * pct / 100.0)))
        selected = set(order[:n_top].tolist())
        captured = sum(1 for idx in event_indices if idx in selected)
        metrics[f"event_capture_top_{pct}pct_area"] = (
            float(captured / n_events) if n_events else None
        )
        metrics[f"cells_in_top_{pct}pct_area"] = n_top
    n_top10 = max(1, int(math.ceil(len(order) * 0.10)))
    top10 = order[:n_top10]
    coords = np.asarray([[cells[i]["x_m"], cells[i]["y_m"]] for i in top10], dtype=float)
    top_tree = cKDTree(coords)
    if event_indices:
        event_xy = np.asarray([[cells[i]["x_m"], cells[i]["y_m"]] for i in event_indices], dtype=float)
        distances, _ = top_tree.query(event_xy, k=1)
        metrics["mean_distance_to_top10pct_area_km"] = float(np.mean(distances) / 1000.0)
        metrics["median_distance_to_top10pct_area_km"] = float(np.median(distances) / 1000.0)
    else:
        metrics["mean_distance_to_top10pct_area_km"] = None
        metrics["median_distance_to_top10pct_area_km"] = None
    metrics["top_10_cells"] = [
        {"cell_id": cells[int(i)]["cell_id"],
         "latitude": cells[int(i)]["latitude"],
         "longitude": cells[int(i)]["longitude"],
         "probability": float(probability[int(i)])}
        for i in order[:10]
    ]
    return metrics


def _forecast_snapshot(cutoff: dict[str, Any], catalog: list[dict[str, Any]],
                       detail: dict[str, Any] | None, cells: list[dict[str, Any]],
                       coupling: dict[str, Any], output_dir: Path,
                       catalog_digest: str, catalog_end_ms: int) -> dict[str, Any]:
    cutoff_ms = int(cutoff["cutoff_ms"])
    pre_events = [e for e in catalog if _event_time(e) < cutoff_ms]
    start_train_ms = int(datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    training_years = max((cutoff_ms - start_train_ms) / (365.25 * DAY_MS), 1.0)
    counts, training_event_count = count_training_events(
        pre_events, cells, start_train_ms, cutoff_ms, MIN_TRAIN_MAG
    )
    fitted = fit_spatial_rate_models(cells, counts, training_years, coupling)

    n_models, n_horizons, n_cells = len(MODEL_NAMES), len(HORIZONS_DAYS), len(cells)
    interval_probability = np.full((n_models, n_horizons, n_cells), np.nan, dtype=np.float32)
    previous_end = 0
    for h_idx, days in enumerate(HORIZONS_DAYS):
        interval_days = days - previous_end
        for model_idx, model_name in enumerate(("K0", "K1", "K2")):
            if model_name == "K2" and fitted["status"]["K2"] != "ok":
                continue
            interval_probability[model_idx, h_idx] = probabilities_from_rate(
                fitted[model_name], interval_days
            ).astype(np.float32)
        previous_end = days

    stress = None
    stress_meta: dict[str, Any] = {"status": "not_applicable_for_calendar_control"}
    k3_base_model = "K2" if fitted["status"]["K2"] == "ok" else "K1"
    if cutoff["kind"] == "major_event_trigger" and detail is not None:
        try:
            stress = calculate_delta_cfs(
                detail, cutoff_ms, cells,
                custom_fault_dir=ROOT / "research" / "data" / "finite_faults",
            )
            if stress is None:
                stress_meta = {"status": "no_source_mechanism_available_as_of_cutoff"}
            elif stress["coverage_fraction"] < 0.005:
                stress_meta = {
                    "status": "insufficient_receiver_coverage",
                    "stress_coverage_fraction": stress["coverage_fraction"],
                }
                stress = None
            else:
                stress_meta = {
                    "status": "ok",
                    "source": stress["source"],
                    "stress_coverage_fraction": stress["coverage_fraction"],
                    "receiver_depth_km": stress["receiver_depth_km"],
                    "max_distance_km": stress["max_distance_km"],
                    "effective_friction": stress["effective_friction"],
                    "shear_modulus_pa": stress["shear_modulus_pa"],
                    "poisson_ratio": stress["poisson_ratio"],
                    "receiver_fault_scenarios": "PB2002 boundary-type/orientation scenarios; not mapped fault inventory",
                    "source_model_warning": (
                        "Unless a custom finite-fault JSON exists, source is a magnitude-scaled "
                        "rectangular proxy inferred from a moment tensor, not a measured slip model."
                    ),
                }
        except Exception as exc:
            stress_meta = {"status": "calculation_failed", "error": f"{type(exc).__name__}: {exc}"}

    if stress is not None:
        cfs = np.nan_to_num(stress["delta_cfs_mpa"], nan=0.0, posinf=0.0, neginf=0.0)
        base_rate = fitted[k3_base_model]
        event_elapsed_days = max(
            0.0, (cutoff_ms - int(cutoff.get("trigger_origin_ms") or cutoff_ms)) / DAY_MS
        )
        previous_end = 0
        for h_idx, days in enumerate(HORIZONS_DAYS):
            interval_days = days - previous_end
            k3 = forecast_k3(base_rate, cfs, interval_days)
            k4 = forecast_k4(
                base_rate, cfs,
                event_elapsed_days + previous_end,
                event_elapsed_days + days,
            )
            interval_probability[3, h_idx] = k3["probability"].astype(np.float32)
            interval_probability[4, h_idx] = k4["probability"].astype(np.float32)
            previous_end = days

    # Horizons are cumulative probabilities. Consecutive interval risks are
    # combined as independent increments of the fitted Poisson/rate-state process.
    probability = np.full_like(interval_probability, np.nan)
    for model_idx in range(n_models):
        valid = np.isfinite(interval_probability[model_idx])
        running_survival = np.ones(n_cells, dtype=np.float64)
        for h_idx in range(n_horizons):
            step = interval_probability[model_idx, h_idx].astype(np.float64)
            finite = np.isfinite(step)
            running_survival[finite] *= (1.0 - step[finite])
            probability[model_idx, h_idx, finite] = (1.0 - running_survival[finite]).astype(np.float32)

    snapshot_dir = output_dir / "forecast_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stem = cutoff["cutoff_id"].replace(":", "_").replace("/", "_")
    npz_path = snapshot_dir / f"{stem}.npz"
    np.savez_compressed(
        npz_path, probability=probability,
        interval_probability=interval_probability,
        training_counts=counts.astype(np.float32),
    )
    npz_hash = hashlib.sha256(npz_path.read_bytes()).hexdigest()
    source_snapshot_path = None
    source_snapshot_hash = None
    if detail is not None:
        source_snapshot_path = snapshot_dir / f"{stem}.source.geojson.gz"
        source_bytes = json.dumps(detail, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        source_snapshot_path.write_bytes(gzip.compress(source_bytes, compresslevel=6))
        source_snapshot_hash = hashlib.sha256(source_snapshot_path.read_bytes()).hexdigest()
    meta = {
        **cutoff,
        "cutoff_utc": utc_iso(cutoff_ms),
        "forecast_created_utc": datetime.now(timezone.utc).isoformat(),
        "data_cutoff_exclusive": utc_iso(cutoff_ms),
        "training_start_utc": utc_iso(start_train_ms),
        "training_event_count_m_ge_6_5": int(training_event_count),
        "training_years": round(training_years, 4),
        "training_model_status": fitted["status"],
        "coupling_coverage_fraction": fitted["coupling_coverage_fraction"],
        "coupling_data_files": coupling.get("files_used", []),
        "global_annual_rate_m_ge_6_5": fitted["global_annual_rate"],
        "catalog_sha256": catalog_digest,
        "catalog_data_window_end_utc": utc_iso(catalog_end_ms),
        "catalog_mode": "current_usgs_comcat_occurrence_time_hindcast",
        "strict_historical_snapshot": False,
        "strict_snapshot_limitation": (
            "Current ComCat may contain later additions/revisions. Occurrence times are "
            "cut off at t0; source products are filtered by their current updateTime when present, "
            "but historical product versions are not archived here."
        ),
        "geophysical_input_mode": "current_coupling_cloud_retrospective" if coupling.get("files_used") else "no_coupling_cloud_data",
        "physical_data_status": stress_meta,
        "K3_K4_base_rate_model": k3_base_model,
        "K4_model": "Dieterich rate-and-state response to a static Coulomb stress step; no measured afterslip/viscoelastic stress history is ingested",
        "snapshot_npz": str(npz_path.relative_to(output_dir)),
        "snapshot_sha256": npz_hash,
        "source_event_snapshot": (
            str(source_snapshot_path.relative_to(output_dir)) if source_snapshot_path else None
        ),
        "source_event_snapshot_sha256": source_snapshot_hash,
        "model_names": list(MODEL_NAMES),
        "horizons_days": list(HORIZONS_DAYS),
        "intervals_days": [
            [0 if i == 0 else HORIZONS_DAYS[i-1], HORIZONS_DAYS[i]]
            for i in range(len(HORIZONS_DAYS))
        ],
        "target_magnitude": TARGET_MAG,
        "training_min_magnitude": MIN_TRAIN_MAG,
        "grid_cell_count": len(cells),
        "grid_cell_size_km": 500,
    }
    meta_path = snapshot_dir / f"{stem}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def download_coupling_cloud(destination: Path) -> Path:
    """Download the public Coupling Cloud model archive into a local data directory."""
    destination.mkdir(parents=True, exist_ok=True)
    url = "https://couplingcloud.ucsd.edu/download/all_models"
    print("      downloading public Coupling Cloud NetCDF archive...", flush=True)
    response = requests.get(url, timeout=(30, 600),
                            headers={"User-Agent": "Seismic-Watch-research/0.1"})
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise RuntimeError(f"Unsafe path in coupling archive: {member.filename}")
        archive.extractall(destination)
    return destination


def run_blind_test(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print("[1/5] Downloading USGS ComCat catalogue (M>=6.5, 2000-2025)...", flush=True)
    catalog = fetch_catalog("2000-01-01", "2025-01-01", MIN_TRAIN_MAG)
    catalog.sort(key=_event_time)
    digest = catalog_hash(catalog)
    catalog_end_ms = parse_time_ms("2025-01-01T00:00:00+00:00")
    raw_snapshot = output_dir / "catalog_snapshot.geojson.gz"
    raw_bytes = json.dumps(
        {"type": "FeatureCollection", "features": catalog},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    raw_snapshot.write_bytes(gzip.compress(raw_bytes, compresslevel=6))
    raw_path = output_dir / "catalog_manifest.json"
    raw_path.write_text(json.dumps({
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "query": {"starttime": "2000-01-01", "endtime": "2025-01-01",
                  "minmagnitude": MIN_TRAIN_MAG, "orderby": "time-asc"},
        "returned_events": len(catalog), "sha256": digest,
        "compressed_snapshot": raw_snapshot.name,
        "compressed_snapshot_sha256": hashlib.sha256(raw_snapshot.read_bytes()).hexdigest(),
        "strict_historical_snapshot": False,
    }, indent=2), encoding="utf-8")

    print("[2/5] Building equal-area grid and plate-motion features...", flush=True)
    cells = equal_area_grid(500.0)
    plates = load_morvel()
    segments = load_boundary_segments()
    cells = annotate_grid(cells, plates, segments)
    cell_path = output_dir / "grid.json"
    cell_path.write_text(json.dumps(cells, ensure_ascii=False), encoding="utf-8")

    print("[3/5] Loading Coupling Cloud geodetic models...", flush=True)
    if args.download_coupling:
        try:
            download_coupling_cloud(Path(args.coupling_dir))
        except Exception as exc:
            print(f"      warning: Coupling Cloud download failed: {type(exc).__name__}: {exc}", flush=True)
    coupling = load_coupling_cloud(args.coupling_dir, cells)
    print(f"      coupling coverage: {np.mean(np.isfinite(coupling['coupling_fraction'])):.1%}", flush=True)
    if not coupling.get("files_used"):
        print("      K2 will be marked unscored: no compatible coupling NetCDF files found.", flush=True)

    cutoffs = select_cutoffs(catalog, args.start_year, args.end_year,
                             args.max_triggers, not args.no_controls)
    manifest = {
        "title": "Seismic Watch K0-K4 occurrence-time hindcast",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "catalog_sha256": digest,
        "cutoff_selection": {
            "major_event_rule": f"All M>={TARGET_MAG} events in {args.start_year}-{args.end_year}, "
                                f"deterministically subsampled to max {args.max_triggers} if required",
            "trigger_cutoff_rule": "origin time + 7 days",
            "controls": not args.no_controls,
            "control_rule": "first day of each month at 00:00 UTC",
        },
        "cutoffs": [],
    }

    print(f"[4/5] Generating {len(cutoffs)} forecasts using pre-cutoff data only...", flush=True)
    all_meta = []
    for i, cutoff in enumerate(cutoffs, 1):
        detail = None
        if cutoff["trigger_event_id"]:
            try:
                detail = fetch_event_detail(str(cutoff["trigger_event_id"]))
            except Exception as exc:
                print(f"      warning: detail fetch failed for {cutoff['trigger_event_id']}: {exc}", flush=True)
        meta = _forecast_snapshot(
            cutoff, catalog, detail, cells, coupling, output_dir, digest, catalog_end_ms
        )
        all_meta.append(meta)
        manifest["cutoffs"].append({
            "cutoff_id": cutoff["cutoff_id"],
            "cutoff_utc": meta["cutoff_utc"],
            "kind": cutoff["kind"],
            "snapshot_sha256": meta["snapshot_sha256"],
            "physical_data_status": meta["physical_data_status"]["status"],
        })
        print(f"      {i}/{len(cutoffs)} {cutoff['cutoff_id']} [{meta['physical_data_status']['status']}]", flush=True)

    manifest_path = output_dir / "blind_test_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Phase 2 begins only after every forecast snapshot has been written.
    print("[5/5] Opening the outcome windows and scoring the frozen forecasts...", flush=True)
    scores: list[dict[str, Any]] = []
    for meta in all_meta:
        cutoff_ms = int(meta["cutoff_ms"])
        npz_path = output_dir / meta["snapshot_npz"]
        snapshot = np.load(npz_path, allow_pickle=False)
        probability = snapshot["probability"]
        interval_probability = snapshot["interval_probability"]
        previous_end = 0
        for h_idx, days in enumerate(HORIZONS_DAYS):
            positives, event_indices, matched = assign_outcomes_to_grid(
                catalog, cells, cutoff_ms, days, TARGET_MAG
            )
            interval_positives, interval_indices, interval_matched = assign_outcomes_to_grid(
                catalog, cells, cutoff_ms, days, TARGET_MAG, start_days=previous_end
            )
            for model_idx, model_name in enumerate(MODEL_NAMES):
                row: dict[str, Any] = {
                    "cutoff_id": meta["cutoff_id"],
                    "cutoff_kind": meta["kind"],
                    "cutoff_utc": meta["cutoff_utc"],
                    "model": model_name,
                    "horizon_days": days,
                    "interval_start_days": previous_end,
                    "interval_end_days": days,
                    "target_magnitude": TARGET_MAG,
                    "status": "ok",
                    "hindcast_class": (
                        "retrospective_modern_geophysics" if model_name in ("K2", "K3", "K4")
                        else "occurrence_time_hindcast"
                    ),
                }
                if model_name == "K2" and meta["training_model_status"]["K2"] != "ok":
                    row["status"] = "not_scored_no_coupling_coverage"
                elif model_name in ("K3", "K4") and meta["physical_data_status"]["status"] != "ok":
                    row["status"] = meta["physical_data_status"]["status"]
                else:
                    cumulative_metric = score_spatial_probability(
                        probability[model_idx, h_idx].astype(float),
                        positives, event_indices, cells,
                    )
                    interval_metric = score_spatial_probability(
                        interval_probability[model_idx, h_idx].astype(float),
                        interval_positives, interval_indices, cells,
                    )
                    row.update(cumulative_metric)
                    row["brier_interval"] = interval_metric.get("brier_spatial")
                    row["log_loss_interval"] = interval_metric.get("log_loss_spatial")
                    row["observed_interval_events"] = interval_metric.get("observed_events")
                    row["interval_event_ids"] = [e["id"] for e in interval_matched]
                row["outcome_event_ids"] = [e["id"] for e in matched]
                row["outcome_events"] = matched
                if model_name in ("K3", "K4"):
                    row["physical_source_quality"] = (
                        meta["physical_data_status"].get("source", {}).get("quality")
                    )
                    row["K3_K4_base_rate_model"] = meta.get("K3_K4_base_rate_model")
                scores.append(row)
            previous_end = days

    # Paired skill against K0 for the same cutoff and horizon.
    k0_brier = {
        (r["cutoff_id"], r["horizon_days"]): r.get("brier_spatial")
        for r in scores if r["model"] == "K0" and r.get("status") == "ok"
    }
    for row in scores:
        baseline = k0_brier.get((row["cutoff_id"], row["horizon_days"]))
        candidate = row.get("brier_spatial")
        row["brier_skill_vs_K0"] = (
            1.0 - float(candidate) / float(baseline)
            if candidate is not None and baseline is not None and baseline > 0
            else None
        )

    scores_path = output_dir / "scores.json"
    scores_path.write_text(json.dumps(scores, indent=2, ensure_ascii=False), encoding="utf-8")
    csv_path = output_dir / "scores.csv"
    fieldnames = [
        "cutoff_id", "cutoff_kind", "cutoff_utc", "model", "hindcast_class",
        "horizon_days", "interval_start_days", "interval_end_days",
        "target_magnitude", "status", "observed_events", "observed_interval_events",
        "unique_positive_cells", "brier_spatial", "log_loss_spatial",
        "brier_interval", "log_loss_interval", "brier_skill_vs_K0",
        "event_capture_top_5pct_area", "event_capture_top_10pct_area",
        "event_capture_top_20pct_area",
        "mean_distance_to_top10pct_area_km", "median_distance_to_top10pct_area_km",
        "global_probability_any_event_approx",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(scores)

    def mean_non_null(values: list[Any]) -> float | None:
        clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
        return float(np.mean(clean)) if clean else None

    aggregate: list[dict[str, Any]] = []
    for model in MODEL_NAMES:
        for days in HORIZONS_DAYS:
            eligible = [
                r for r in scores if r["model"] == model and r["horizon_days"] == days
                and r.get("status") == "ok"
            ]
            aggregate.append({
                "model": model,
                "horizon_days": days,
                "hindcast_class": (
                    "retrospective_modern_geophysics" if model in ("K2", "K3", "K4")
                    else "occurrence_time_hindcast"
                ),
                "eligible_cutoffs": len(eligible),
                "mean_spatial_brier": mean_non_null([r.get("brier_spatial") for r in eligible]),
                "mean_interval_brier": mean_non_null([r.get("brier_interval") for r in eligible]),
                "mean_log_loss": mean_non_null([r.get("log_loss_spatial") for r in eligible]),
                "mean_brier_skill_vs_K0": mean_non_null([r.get("brier_skill_vs_K0") for r in eligible]),
                "mean_event_capture_top10pct_area": mean_non_null([
                    r.get("event_capture_top_10pct_area") for r in eligible
                ]),
                "mean_localization_error_km": mean_non_null([
                    r.get("mean_distance_to_top10pct_area_km") for r in eligible
                ]),
            })
    (output_dir / "aggregate_scores.json").write_text(
        json.dumps(aggregate, indent=2), encoding="utf-8"
    )
    with (output_dir / "aggregate_scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate[0].keys()))
        writer.writeheader()
        writer.writerows(aggregate)

    print(f"Finished. Results: {output_dir}", flush=True)
    print(f"Forecast snapshots: {output_dir / 'forecast_snapshots'}", flush=True)
    print(f"Score table: {csv_path}", flush=True)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2023)
    parser.add_argument("--max-triggers", type=int, default=24,
                        help="Maximum evenly spaced M>=6.5 trigger events (0 means all)")
    parser.add_argument("--no-controls", action="store_true",
                        help="Do not include monthly calendar control cutoffs")
    parser.add_argument("--coupling-dir", default=str(ROOT / "research" / "data" / "coupling_cloud"))
    parser.add_argument("--download-coupling", action="store_true",
                        help="Download the current public Coupling Cloud NetCDF archive before running K2")
    parser.add_argument("--output", default=str(ROOT / "research" / "outputs" / "blind-test"))
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    run_blind_test(args)
