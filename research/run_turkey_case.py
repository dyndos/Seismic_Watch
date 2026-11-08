"""Focused Turkey 2023 case study with strict as-of source-product filtering.

Two source-information cutoffs are evaluated:
- 2023-02-06 02:00 UTC: rapid USGS internal moment tensor, before the M7.5 event;
- 2023-02-22 00:00 UTC: USGS finite-fault product is available.

The first cutoff is the primary prospective-style test of the M7.8 source event.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from research.run_blind_test import (
    DAY_MS,
    HORIZONS_DAYS,
    MIN_TRAIN_MAG,
    MODEL_NAMES,
    TARGET_MAG,
    _event_time,
    _forecast_snapshot,
    assign_outcomes_to_grid,
    catalog_hash,
    download_coupling_cloud,
    fetch_catalog,
    fetch_event_detail,
    score_spatial_probability,
    utc_iso,
)
from research.kinematics import (
    ROOT,
    annotate_grid,
    equal_area_grid,
    load_boundary_segments,
    load_morvel,
)
from research.physical import load_coupling_cloud, load_source_fault
from research.slab2 import download_slab2, load_slab2

EVENT_ID = "us6000jllz"
CASE_CUTOFFS = (
    {
        "cutoff_id": "turkey_pazarcik_early_2023-02-06T0200Z",
        "cutoff_utc": "2023-02-06T02:00:00+00:00",
        "expected_source_quality": "moment_tensor_plus_empirical_rectangle_proxy",
        "source_stage": "rapid_internal_moment_tensor",
        "description": "43 minutes after the M7.8 mainshock; before the M7.5 Elbistan event",
    },
    {
        "cutoff_id": "turkey_pazarcik_finite_fault_2023-02-22T0000Z",
        "cutoff_utc": "2023-02-22T00:00:00+00:00",
        "expected_source_quality": "usgs_finite_fault_geometry_uniform_slip",
        "source_stage": "USGS finite-fault version 4",
        "description": "After the USGS finite-fault product update; M7.5 event is already in the training history",
    },
)


def parse_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def filter_products_as_of(feature: dict[str, Any], cutoff_ms: int) -> dict[str, Any]:
    """Keep only USGS products whose current product update time is <= cutoff."""
    result = deepcopy(feature)
    props = result.setdefault("properties", {})
    products = props.get("products") or {}
    filtered: dict[str, list[dict[str, Any]]] = {}
    for kind, items in products.items():
        valid = [
            item for item in (items or [])
            if item.get("updateTime") is not None
            and int(item["updateTime"]) <= cutoff_ms
        ]
        if valid:
            filtered[kind] = valid
    props["products"] = filtered
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_case(args: argparse.Namespace) -> Path:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    data_dir = ROOT / "research" / "data"
    coupling_dir = Path(args.coupling_dir)
    slab2_dir = Path(args.slab2_dir)

    catalog_start = "1976-01-01"
    catalog_end = datetime.now(timezone.utc).date().isoformat()
    print(f"[1/6] Downloading USGS ComCat M>={MIN_TRAIN_MAG} from {catalog_start} to {catalog_end}...", flush=True)
    catalog = fetch_catalog(catalog_start, catalog_end, MIN_TRAIN_MAG)
    catalog.sort(key=_event_time)
    digest = catalog_hash(catalog)
    catalog_end_ms = parse_ms(f"{catalog_end}T00:00:00+00:00")
    target = next((e for e in catalog if str(e.get("id") or "") == EVENT_ID), None)
    if target is None:
        raise RuntimeError(f"Target event {EVENT_ID} was not returned by the USGS ComCat query.")
    origin_ms = _event_time(target)
    target_props = target.get("properties") or {}

    catalog_bytes = json.dumps(
        {"type": "FeatureCollection", "features": catalog},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    catalog_path = output / "catalog_snapshot.geojson.gz"
    catalog_path.write_bytes(gzip.compress(catalog_bytes, compresslevel=6))
    _write_json(output / "catalog_manifest.json", {
        "source": "USGS ComCat",
        "query": {
            "starttime": catalog_start,
            "endtime": catalog_end,
            "minmagnitude": MIN_TRAIN_MAG,
            "orderby": "time-asc",
        },
        "returned_events": len(catalog),
        "sha256": digest,
        "compressed_snapshot": catalog_path.name,
        "strict_historical_snapshot": False,
    })

    print("[2/6] Loading plate kinematics and equal-area grid...", flush=True)
    cells = equal_area_grid(500.0)
    cells = annotate_grid(cells, load_morvel(), load_boundary_segments())

    print("[3/6] Loading Slab2 receiver geometry...", flush=True)
    if args.download_slab2:
        download_slab2(slab2_dir)
    cells, slab2_manifest = load_slab2(slab2_dir, cells)
    _write_json(output / "slab2_manifest.json", slab2_manifest)

    print("[4/6] Loading Coupling Cloud geodetic models...", flush=True)
    if args.download_coupling:
        download_coupling_cloud(coupling_dir)
    coupling = load_coupling_cloud(coupling_dir, cells)
    coupling_manifest = {
        key: coupling.get(key) for key in (
            "coupling_coverage_fraction", "slip_deficit_coverage_fraction",
            "any_physical_coverage_fraction", "covered_cells", "variables_used",
            "unit_rejections", "unsupported_grids", "files_used",
        )
    }
    _write_json(output / "coupling_manifest.json", coupling_manifest)
    _write_json(output / "grid.json", cells)

    print("[5/6] Freezing two Turkey source-time forecasts...", flush=True)
    current_detail = fetch_event_detail(EVENT_ID)
    if current_detail is None:
        raise RuntimeError(f"USGS event detail unavailable for {EVENT_ID}.")

    case_meta: list[dict[str, Any]] = []
    source_checks: list[dict[str, Any]] = []
    filtered_details: dict[str, dict[str, Any]] = {}
    for spec in CASE_CUTOFFS:
        cutoff_ms = parse_ms(spec["cutoff_utc"])
        if cutoff_ms <= origin_ms:
            raise ValueError("Case cutoff must be after the mainshock origin time.")
        detail = filter_products_as_of(current_detail, cutoff_ms)
        source = load_source_fault(detail, cutoff_ms)
        if source is None:
            raise RuntimeError(f"No source mechanism is available as of {spec['cutoff_utc']}.")
        if source.get("quality") != spec["expected_source_quality"]:
            raise RuntimeError(
                f"Unexpected source quality for {spec['cutoff_id']}: "
                f"{source.get('quality')} (expected {spec['expected_source_quality']})."
            )
        if source.get("finite_fault_product_update_ms", source.get("mechanism_product_update_ms", 0)) > cutoff_ms:
            raise RuntimeError("Future source product leaked past the case cutoff.")

        source_checks.append({
            "cutoff_id": spec["cutoff_id"],
            "cutoff_utc": spec["cutoff_utc"],
            "source_stage": spec["source_stage"],
            "source_quality": source.get("quality"),
            "source_product_update_utc": utc_iso(int(
                source.get("finite_fault_product_update_ms")
                or source.get("mechanism_product_update_ms")
            )),
            "source_geometry": source,
            "products_retained_as_of_cutoff": {
                kind: [int(x["updateTime"]) for x in items]
                for kind, items in (detail.get("properties") or {}).get("products", {}).items()
            },
        })
        cutoff = {
            "cutoff_id": spec["cutoff_id"],
            "kind": "major_event_trigger",
            "trigger_event_id": EVENT_ID,
            "trigger_origin_ms": origin_ms,
            "cutoff_ms": cutoff_ms,
            "cutoff_rule": "fixed_case_study_as_of_cutoff; future source products filtered",
            "source_solution_catalog": "USGS event products",
            "source_solution_name": spec["source_stage"],
            "source_solution_update_ms": int(
                source.get("finite_fault_product_update_ms")
                or source.get("mechanism_product_update_ms")
            ),
            "source_solution_update_utc": utc_iso(int(
                source.get("finite_fault_product_update_ms")
                or source.get("mechanism_product_update_ms")
            )),
            "source_solution_delay_days": round(
                (int(source.get("finite_fault_product_update_ms")
                     or source.get("mechanism_product_update_ms")) - origin_ms) / DAY_MS, 4
            ),
        }
        filtered_details[spec["cutoff_id"]] = detail
        meta = _forecast_snapshot(
            cutoff, catalog, detail, cells, coupling, output, digest, catalog_end_ms
        )
        if source.get("quality") == "usgs_finite_fault_geometry_uniform_slip":
            meta["physical_data_status"]["source_model_warning"] = (
                "USGS finite-fault product geometry is used, but the product adapter "
                "converts scalar moment to uniform average slip; the heterogeneous "
                "subfault slip distribution is not ingested."
            )
        else:
            meta["physical_data_status"]["source_model_warning"] = (
                "Rapid internal moment tensor is converted to a magnitude-scaled "
                "rectangular source proxy; this is not a measured finite-fault slip model."
            )
        meta["case_description"] = spec["description"]
        meta["expected_source_quality"] = spec["expected_source_quality"]
        meta["training_history_start_utc"] = "1976-01-01T00:00:00+00:00"
        meta["case_study_note"] = (
            "Retrospective occurrence-time hindcast. ComCat revisions and modern "
            "Coupling Cloud/Slab2 inputs are not historical snapshots."
        )
        case_meta.append(meta)
        _write_json(output / "forecast_snapshots" / f"{spec['cutoff_id']}.json", meta)
        print(
            f"      {spec['cutoff_id']}: K3/K4 source={source['quality']}; "
            f"physical={meta['physical_data_status']['status']}",
            flush=True,
        )

    _write_json(output / "case_source_checks.json", source_checks)
    _write_json(output / "case_manifest.json", {
        "title": "Turkey 2023 Kahramanmaras sequence K0-K4 case study",
        "target_event": {
            "id": EVENT_ID,
            "magnitude": target_props.get("mag"),
            "time_utc": utc_iso(origin_ms),
            "latitude": (target.get("geometry") or {}).get("coordinates", [None, None])[1],
            "longitude": (target.get("geometry") or {}).get("coordinates", [None, None])[0],
            "depth_km": (target.get("geometry") or {}).get("coordinates", [None, None, None])[2],
            "name": "Pazarcik / Kahramanmaras M7.8",
        },
        "companion_event": {
            "id": "us6000jlqa",
            "magnitude": 7.5,
            "time_utc": "2023-02-06T10:24:48.811+00:00",
            "name": "Elbistan M7.5",
            "role": "Future outcome for the early cutoff; part of training history for the later cutoff",
        },
        "catalog_sha256": digest,
        "cutoffs": [
            {
                "cutoff_id": m["cutoff_id"],
                "cutoff_utc": m["cutoff_utc"],
                "source_quality": m["physical_data_status"].get("source", {}).get("quality")
                    if isinstance(m.get("physical_data_status"), dict) else None,
                "physical_data_status": m["physical_data_status"],
            }
            for m in case_meta
        ],
        "important_limitations": [
            "The 02:00 UTC case uses the rapid USGS internal moment tensor and an empirical rectangular source proxy; the later finite-fault solution is excluded.",
            "The 22 February case uses the USGS finite-fault version 4 geometry, but the M7.5 Elbistan earthquake is already in its pre-cutoff training history.",
            "Current Coupling Cloud and Slab2 products are retrospective modern geophysical inputs.",
            "Current USGS ComCat is not a versioned historical archive; origin-time filtering does not reconstruct precisely what the public catalogue showed at each historical time.",
        ],
    })

    # Score only after both forecast snapshots have been frozen.
    print("[6/6] Opening post-cutoff outcomes and scoring all five models...", flush=True)
    scores: list[dict[str, Any]] = []
    for meta in case_meta:
        cutoff_ms = int(meta["cutoff_ms"])
        npz = np.load(output / meta["snapshot_npz"], allow_pickle=False)
        probability = npz["probability"]
        interval_probability = npz["interval_probability"]
        previous_end = 0
        for h_idx, days in enumerate(HORIZONS_DAYS):
            positives, event_indices, matched = assign_outcomes_to_grid(
                catalog, cells, cutoff_ms, days, TARGET_MAG
            )
            interval_positives, interval_indices, interval_matched = assign_outcomes_to_grid(
                catalog, cells, cutoff_ms, days, TARGET_MAG, start_days=previous_end
            )
            stack = probability[:, h_idx, :].astype(float)
            common_cells = np.all(np.isfinite(stack), axis=0)
            for model_idx, model in enumerate(MODEL_NAMES):
                row: dict[str, Any] = {
                    "cutoff_id": meta["cutoff_id"],
                    "cutoff_utc": meta["cutoff_utc"],
                    "model": model,
                    "horizon_days": days,
                    "target_magnitude": TARGET_MAG,
                    "common_forecast_cells": int(np.sum(common_cells)),
                    "total_grid_cells": len(cells),
                    "status": "ok",
                    "observed_events": len(matched),
                    "outcome_event_ids": [e["id"] for e in matched],
                    "outcome_events": matched,
                    "hindcast_class": (
                        "retrospective_modern_geophysics" if model in ("K2", "K3", "K4")
                        else "occurrence_time_hindcast"
                    ),
                }
                if model == "K2" and not str(meta["training_model_status"]["K2"]).startswith("ok"):
                    row["status"] = meta["training_model_status"]["K2"]
                elif model in ("K3", "K4") and meta["physical_data_status"]["status"] != "ok":
                    row["status"] = meta["physical_data_status"]["status"]
                else:
                    p = np.where(common_cells, stack[model_idx], np.nan)
                    cumulative = score_spatial_probability(p, positives, event_indices, cells)
                    interval_p = np.where(
                        common_cells, interval_probability[model_idx, h_idx].astype(float), np.nan
                    )
                    interval = score_spatial_probability(
                        interval_p, interval_positives, interval_indices, cells
                    )
                    row.update(cumulative)
                    row["brier_interval"] = interval.get("brier_spatial")
                    row["log_loss_interval"] = interval.get("log_loss_spatial")
                    row["observed_interval_events"] = interval.get("observed_events")
                    row["interval_event_ids"] = [e["id"] for e in interval_matched]
                scores.append(row)
            previous_end = days

    k0_by_key = {
        (r["cutoff_id"], r["horizon_days"]): r.get("brier_spatial")
        for r in scores if r["model"] == "K0" and r.get("status") == "ok"
    }
    for row in scores:
        baseline = k0_by_key.get((row["cutoff_id"], row["horizon_days"]))
        value = row.get("brier_spatial")
        row["brier_skill_vs_K0"] = (
            1.0 - float(value) / float(baseline)
            if value is not None and baseline is not None and baseline > 0 else None
        )

    _write_json(output / "scores.json", scores)
    fields = [
        "cutoff_id", "cutoff_utc", "model", "horizon_days", "status",
        "hindcast_class", "target_magnitude", "observed_events",
        "common_forecast_cells", "total_grid_cells", "brier_spatial",
        "log_loss_spatial", "brier_interval", "log_loss_interval",
        "brier_skill_vs_K0", "event_capture_top_5pct_area",
        "event_capture_top_10pct_area", "event_capture_top_20pct_area",
        "mean_distance_to_top10pct_area_km",
    ]
    with (output / "scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(scores)

    aggregate: list[dict[str, Any]] = []
    common_sample: dict[str, Any] = {"title": "Turkey case K0-K4 shared spatial/time sample", "cases": {}}
    for meta in case_meta:
        case_scores = [r for r in scores if r["cutoff_id"] == meta["cutoff_id"]]
        for days in HORIZONS_DAYS:
            subset = [
                r for r in case_scores
                if r["horizon_days"] == days and r.get("status") == "ok"
            ]
            models_ok = sorted(r["model"] for r in subset)
            common = len(models_ok) == len(MODEL_NAMES) and set(models_ok) == set(MODEL_NAMES)
            common_sample["cases"].setdefault(meta["cutoff_id"], {})[str(days)] = {
                "models_all_valid": common,
                "models": models_ok,
                "common_forecast_cells": subset[0]["common_forecast_cells"] if subset else 0,
            }
            baseline = next((r.get("brier_spatial") for r in subset if r["model"] == "K0"), None)
            for row in subset:
                aggregate.append({
                    "cutoff_id": meta["cutoff_id"],
                    "cutoff_utc": meta["cutoff_utc"],
                    "model": row["model"],
                    "horizon_days": days,
                    "all_five_models_comparable": common,
                    "eligible_models": len(models_ok),
                    "observed_events": row.get("observed_events"),
                    "brier_spatial": row.get("brier_spatial"),
                    "log_loss_spatial": row.get("log_loss_spatial"),
                    "brier_skill_vs_K0": row.get("brier_skill_vs_K0"),
                    "event_capture_top_10pct_area": row.get("event_capture_top_10pct_area"),
                    "mean_distance_to_top10pct_area_km": row.get("mean_distance_to_top10pct_area_km"),
                })
    _write_json(output / "common_sample_manifest.json", common_sample)
    _write_json(output / "aggregate_scores.json", aggregate)
    with (output / "aggregate_scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregate[0].keys()))
        writer.writeheader()
        writer.writerows(aggregate)

    print(f"Finished Turkey case study. Results: {output}", flush=True)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coupling-dir", default=str(ROOT / "research" / "data" / "coupling_cloud"))
    parser.add_argument("--download-coupling", action="store_true")
    parser.add_argument("--slab2-dir", default=str(ROOT / "research" / "data" / "slab2"))
    parser.add_argument("--download-slab2", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "research" / "outputs" / "turkey-2023-case"))
    return parser


if __name__ == "__main__":
    run_case(build_parser().parse_args())
