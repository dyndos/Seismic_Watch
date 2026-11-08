"""As-of K0-K4 hindcasts for 2026 Tibet and Flores M7+ earthquakes."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from research.run_blind_test import (
    DAY_MS, HORIZONS_DAYS, MIN_TRAIN_MAG, MODEL_NAMES, TARGET_MAG,
    _event_time, _forecast_snapshot, assign_outcomes_to_grid, catalog_hash,
    download_coupling_cloud, fetch_catalog, fetch_event_detail,
    score_spatial_probability, utc_iso,
)
from research.kinematics import (
    ROOT, annotate_grid, equal_area_grid, load_boundary_segments, load_morvel,
)
from research.physical import load_coupling_cloud, load_source_fault
from research.slab2 import download_slab2, load_slab2


TRIGGERS = (
    {
        "event_id": "us6000u43g",
        "case_id": "tibet_nagqu_2026_m7_0",
        "name": "Baqen / Nagqu, Tibet M7.0",
        "fallback": {
            "updated_utc": "2026-10-22T15:28:59Z",
            "source": "USGS-NEIC-W-phase",
            "strike": 175.0, "dip": 57.0, "rake": -119.0,
            "strike2": 40.0, "dip2": 43.0, "rake2": -54.0,
            "scalar_moment_nm": 3.416e19,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u43g/moment-tensor",
        },
    },
    {
        "event_id": "us6000tkt2",
        "case_id": "flores_indonesia_2026_m7_7",
        "name": "Flores Sea / Ende, Indonesia M7.7",
        "fallback": {
            "updated_utc": "2026-08-15T01:47:14Z",
            "source": "GCMT-Quick-CMT",
            "strike": 94.0, "dip": 33.0, "rake": 96.0,
            "strike2": 267.0, "dip2": 58.0, "rake2": 86.0,
            "scalar_moment_nm": 5.534e20,
            "url": "https://data.unavco.org/app/products/portal/moment_tensor/mt_event.html?id=12144482",
        },
    },
)


def parse_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def filter_products_as_of(feature: dict[str, Any], cutoff_ms: int) -> dict[str, Any]:
    result = json.loads(json.dumps(feature))
    props = result.setdefault("properties", {})
    products = props.get("products") or {}
    retained = {}
    for kind, items in products.items():
        valid = [
            item for item in (items or [])
            if item.get("updateTime") is not None
            and int(item["updateTime"]) <= cutoff_ms
        ]
        if valid:
            retained[kind] = valid
    props["products"] = retained
    return result


def attach_fallback(feature: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(feature))
    products = result.setdefault("properties", {}).setdefault("products", {})
    products.setdefault("moment-tensor", []).append({
        "source": fallback["source"],
        "updateTime": parse_ms(fallback["updated_utc"]),
        "properties": {
            "nodal-plane-1-strike": str(fallback["strike"]),
            "nodal-plane-1-dip": str(fallback["dip"]),
            "nodal-plane-1-rake": str(fallback["rake"]),
            "nodal-plane-2-strike": str(fallback["strike2"]),
            "nodal-plane-2-dip": str(fallback["dip2"]),
            "nodal-plane-2-rake": str(fallback["rake2"]),
            "scalar-moment": str(fallback["scalar_moment_nm"]),
        },
    })
    return result


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def make_forecast_stats(probability: np.ndarray, cells: list[dict[str, Any]],
                        latitude: float, longitude: float) -> dict[str, Any]:
    valid = np.isfinite(probability)
    if not np.any(valid):
        return {"status": "no_probability_surface", "top_cells": []}
    values = np.clip(probability[valid].astype(float), 0.0, 1.0)
    global_any = float(1.0 - np.prod(1.0 - values))
    indexes = np.flatnonzero(valid)
    order = indexes[np.argsort(-probability[valid])]
    distances = np.asarray([
        distance_km(latitude, longitude, float(c["latitude"]), float(c["longitude"]))
        for c in cells
    ])
    local = indexes[distances[indexes] <= 1000.0]
    nearest = int(np.argmin(distances))
    local_rank = None
    if nearest in set(local.tolist()):
        local_order = local[np.argsort(-probability[local])]
        local_rank = int(np.where(local_order == nearest)[0][0]) + 1
    top = []
    for idx in order[:10]:
        cell = cells[int(idx)]
        top.append({
            "rank": len(top) + 1,
            "cell_id": cell["cell_id"],
            "latitude": float(cell["latitude"]),
            "longitude": float(cell["longitude"]),
            "probability": float(probability[int(idx)]),
        })
    return {
        "global_probability_any_event_approx": global_any,
        "top_cells": top,
        "cells_within_1000km": int(local.size),
        "nearest_trigger_cell_id": cells[nearest]["cell_id"],
        "nearest_trigger_cell_distance_km": float(distances[nearest]),
        "nearest_trigger_cell_local_rank": local_rank,
    }


def run(args: argparse.Namespace) -> Path:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    catalog_end = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    print(f"[1/7] Downloading USGS ComCat M>={MIN_TRAIN_MAG} through {catalog_end}...", flush=True)
    catalog = fetch_catalog("1976-01-01T00:00:00Z", catalog_end, MIN_TRAIN_MAG)
    catalog.sort(key=_event_time)
    digest = catalog_hash(catalog)
    by_id = {str(e.get("id") or ""): e for e in catalog}
    snapshot = output / "catalog_snapshot.geojson.gz"
    raw = json.dumps(
        {"type": "FeatureCollection", "features": catalog},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    snapshot.write_bytes(gzip.compress(raw, compresslevel=6))
    write_json(output / "catalog_manifest.json", {
        "source": "USGS ComCat",
        "starttime": "1976-01-01T00:00:00Z",
        "endtime": catalog_end,
        "minmagnitude": MIN_TRAIN_MAG,
        "returned_events": len(catalog),
        "sha256": digest,
        "compressed_snapshot": snapshot.name,
        "strict_historical_snapshot": False,
        "limitation": "Current ComCat is not a versioned historical archive.",
    })

    print("[2/7] Building 500-km equal-area grid and tectonic annotations...", flush=True)
    cells = equal_area_grid(500.0)
    cells = annotate_grid(cells, load_morvel(), load_boundary_segments())

    print("[3/7] Loading Slab2...", flush=True)
    slab_dir = Path(args.slab2_dir)
    if args.download_slab2:
        download_slab2(slab_dir)
    cells, slab_manifest = load_slab2(slab_dir, cells)
    write_json(output / "slab2_manifest.json", slab_manifest)

    print("[4/7] Loading Coupling Cloud...", flush=True)
    coupling_dir = Path(args.coupling_dir)
    if args.download_coupling:
        download_coupling_cloud(coupling_dir)
    coupling = load_coupling_cloud(coupling_dir, cells)
    write_json(output / "coupling_manifest.json", {
        key: coupling.get(key) for key in (
            "coupling_coverage_fraction", "slip_deficit_coverage_fraction",
            "any_physical_coverage_fraction", "covered_cells", "variables_used",
            "unit_rejections", "unsupported_grids", "files_used",
        )
    })
    write_json(output / "grid.json", cells)

    print("[5/7] Freezing each forecast at trigger + 7 days...", flush=True)
    metadata = []
    source_checks = []
    for spec in TRIGGERS:
        event_id = spec["event_id"]
        event = by_id.get(event_id)
        if event is None:
            raise RuntimeError(f"Target event {event_id} not found in current ComCat M>=6.5 catalog.")
        origin_ms = _event_time(event)
        cutoff_ms = origin_ms + 7 * DAY_MS
        detail = fetch_event_detail(event_id)
        if detail is None:
            raise RuntimeError(f"Event detail unavailable for {event_id}.")

        detail_as_of = filter_products_as_of(detail, cutoff_ms)
        source = load_source_fault(
            detail_as_of, cutoff_ms,
            custom_fault_dir=ROOT / "research" / "data" / "finite_faults",
        )
        fallback_used = False
        if source is None:
            detail_as_of = filter_products_as_of(
                attach_fallback(detail, spec["fallback"]), cutoff_ms
            )
            source = load_source_fault(
                detail_as_of, cutoff_ms,
                custom_fault_dir=ROOT / "research" / "data" / "finite_faults",
            )
            fallback_used = True
        if source is None:
            raise RuntimeError(f"No mechanism available by cutoff for {event_id}.")
        update_ms = int(
            source.get("finite_fault_product_update_ms")
            or source.get("mechanism_product_update_ms")
            or 0
        )
        if update_ms <= 0 or update_ms > cutoff_ms:
            raise RuntimeError(f"Invalid or future-dated source mechanism for {event_id}.")

        coords = (event.get("geometry") or {}).get("coordinates") or [None, None, None]
        trigger_location = {
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
        }
        cutoff = {
            "cutoff_id": spec["case_id"] + "_asof_7d",
            "kind": "major_event_trigger",
            "trigger_event_id": event_id,
            "trigger_origin_ms": origin_ms,
            "cutoff_ms": cutoff_ms,
            "cutoff_rule": "mainshock origin + 7 days; source products filtered by updateTime",
            "source_solution_catalog": spec["fallback"]["source"] if fallback_used else "USGS ComCat products",
            "source_solution_name": source.get("quality"),
            "source_solution_update_ms": update_ms,
            "source_solution_update_utc": utc_iso(update_ms),
            "source_solution_delay_days": round((update_ms - origin_ms) / DAY_MS, 5),
        }
        source_checks.append({
            "case_id": spec["case_id"],
            "event_id": event_id,
            "event_name": spec["name"],
            "origin_utc": utc_iso(origin_ms),
            "cutoff_utc": utc_iso(cutoff_ms),
            "source_solution_update_utc": utc_iso(update_ms),
            "source_quality": source.get("quality"),
            "source_geometry": source,
            "fallback_mechanism_attached": fallback_used,
            "fallback_provenance": spec["fallback"]["url"] if fallback_used else None,
            "products_retained_as_of_cutoff": {
                k: [int(p["updateTime"]) for p in v]
                for k, v in (detail_as_of.get("properties") or {}).get("products", {}).items()
            },
        })

        meta = _forecast_snapshot(
            cutoff, catalog, detail_as_of, cells, coupling, output, digest, now_ms
        )
        props = event.get("properties") or {}
        meta["case_id"] = spec["case_id"]
        meta["event_name"] = spec["name"]
        meta["trigger_event"] = {
            "id": event_id,
            "magnitude": props.get("mag"),
            "magnitude_type": props.get("magType"),
            "place": props.get("place"),
            "time_utc": utc_iso(origin_ms),
            "latitude": trigger_location["latitude"],
            "longitude": trigger_location["longitude"],
            "depth_km": float(coords[2]) if len(coords) > 2 else None,
        }
        meta["fallback_mechanism_attached"] = fallback_used
        meta["fallback_provenance"] = spec["fallback"]["url"] if fallback_used else None
        meta["case_limitations"] = [
            "Forecast is a retrospective hindcast frozen seven days after the mainshock.",
            "All events with origin time before cutoff, including the mainshock and first-week aftershocks, are included in training.",
            "Current Coupling Cloud and Slab2 are retrospective modern inputs, not dated historical snapshots.",
            "Current ComCat is not a versioned historical catalogue; occurrences and source products are filtered by available timestamps.",
            "PB2002 receiver orientations are scenarios, not a mapped inventory of active faults.",
            "The 500-km grid is regional and cannot locate an individual fault segment.",
        ]
        metadata.append(meta)
        write_json(output / "forecast_snapshots" / (spec["case_id"] + ".json"), meta)
        print(
            f"    {spec['case_id']}: cutoff={utc_iso(cutoff_ms)}, "
            f"source={source.get('quality')}, training M>=6.5={meta['training_event_count_m_ge_6_5']}",
            flush=True,
        )

    write_json(output / "case_source_checks.json", source_checks)
    write_json(output / "case_manifest.json", {
        "title": "2026 Tibet and Flores K0-K4 event-trigger hindcasts",
        "created_utc": catalog_end,
        "catalog_sha256": digest,
        "catalog_events": len(catalog),
        "target_magnitude": TARGET_MAG,
        "training_min_magnitude": MIN_TRAIN_MAG,
        "grid_cell_count": len(cells),
        "grid_cell_size_km": 500,
        "source_checks": source_checks,
        "physical_data_note": "Current Coupling Cloud and Slab2 are retrospective modern inputs.",
    })

    print("[6/7] Scoring full horizons only; partial horizons remain unscored...", flush=True)
    summaries = {"data_as_of_utc": catalog_end, "target": "global M>=6.5", "cases": {}}
    score_rows = []
    for meta in metadata:
        npz = np.load(output / meta["snapshot_npz"], allow_pickle=False)
        probabilities = npz["probability"]
        trigger = meta["trigger_event"]
        case_summary = {
            "event": trigger,
            "forecast_cutoff_utc": meta["cutoff_utc"],
            "source_status": meta["physical_data_status"],
            "training_event_count_m_ge_6_5": meta["training_event_count_m_ge_6_5"],
            "training_years": meta["training_years"],
            "training_model_status": meta["training_model_status"],
            "models": {},
        }
        for mi, model in enumerate(MODEL_NAMES):
            status = meta["training_model_status"].get(model, "unknown")
            if model in ("K3", "K4"):
                status = meta["physical_data_status"].get("status", "unknown")
            horizons = []
            for hi, days in enumerate(HORIZONS_DAYS):
                probability = probabilities[mi, hi].astype(float)
                stats = make_forecast_stats(
                    probability, cells, trigger["latitude"], trigger["longitude"]
                )
                fully_observed = int(meta["cutoff_ms"]) + days * DAY_MS <= now_ms
                elapsed = max(0.0, min(days, (now_ms - int(meta["cutoff_ms"])) / DAY_MS))
                positives, indexes, matched = assign_outcomes_to_grid(
                    catalog, cells, int(meta["cutoff_ms"]), days, TARGET_MAG
                )
                local_events = [
                    e for e in matched
                    if distance_km(
                        trigger["latitude"], trigger["longitude"],
                        e["latitude"], e["longitude"],
                    ) <= 1000.0
                ]
                if not str(status).startswith("ok") or not np.any(np.isfinite(probability)):
                    score = {"status": status}
                elif fully_observed:
                    score = score_spatial_probability(probability, positives, indexes, cells)
                else:
                    score = {
                        "status": "partial_window_not_scored",
                        "elapsed_days": round(elapsed, 3),
                    }

                row = {
                    "case_id": meta["case_id"],
                    "event_name": meta["event_name"],
                    "cutoff_utc": meta["cutoff_utc"],
                    "model": model,
                    "model_status": status,
                    "horizon_days": days,
                    "fully_observed": fully_observed,
                    "elapsed_days": round(elapsed, 3),
                    "observed_global_events_m_ge_6_5": len(matched),
                    "observed_local_events_within_1000km_m_ge_6_5": len(local_events),
                    "observed_event_ids": [e["id"] for e in matched],
                    "brier_spatial": score.get("brier_spatial"),
                    "log_loss_spatial": score.get("log_loss_spatial"),
                    "event_capture_top_10pct_area": score.get("event_capture_top_10pct_area"),
                    "mean_distance_to_top10pct_area_km": score.get("mean_distance_to_top10pct_area_km"),
                    "score_status": score.get("status"),
                    "global_probability_any_event_approx": stats.get("global_probability_any_event_approx"),
                    "nearest_trigger_cell_id": stats.get("nearest_trigger_cell_id"),
                    "nearest_trigger_cell_local_rank": stats.get("nearest_trigger_cell_local_rank"),
                    "top_cells": stats.get("top_cells", [])[:5],
                }
                score_rows.append(row)
                horizons.append({
                    "days": days,
                    "status": status,
                    "fully_observed": fully_observed,
                    "elapsed_days": round(elapsed, 3),
                    "observed_events": matched,
                    "observed_local_events": local_events,
                    "score": score,
                    **stats,
                })
            case_summary["models"][model] = {"status": status, "horizons": horizons}
        summaries["cases"][meta["case_id"]] = case_summary

    baselines = {
        (r["case_id"], r["horizon_days"]): r["brier_spatial"]
        for r in score_rows
        if r["model"] == "K0" and r["score_status"] == "ok" and r["brier_spatial"] is not None
    }
    for row in score_rows:
        base = baselines.get((row["case_id"], row["horizon_days"]))
        value = row["brier_spatial"]
        row["brier_skill_vs_K0"] = (
            1.0 - float(value) / float(base)
            if value is not None and base is not None and base > 0 else None
        )

    write_json(output / "forecast_summary.json", summaries)
    write_json(output / "scores.json", score_rows)
    if score_rows:
        with (output / "scores.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(score_rows[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(score_rows)

    print("[7/7] Creating report...", flush=True)
    report = [
        "# Seismic Watch: 2026 Tibet and Flores K0-K4 hindcasts",
        "",
        f"Data snapshot: {catalog_end}",
        "",
        "Each forecast was frozen seven days after the mainshock. The mainshock and all catalogued M>=6.5 events before the cutoff are part of the training history. Later events are held out for scoring.",
        "",
        "The model estimates global spatial probabilities of subsequent M>=6.5 events on a 500-km equal-area grid. It does not predict an exact date, hour, or individual fault.",
        "",
        "K0: baseline historical rate. K1: plate-kinematic features. K2: K1 plus Coupling Cloud and Slab2. K3: Coulomb stress step. K4: Dieterich rate-and-state response.",
        "",
    ]
    for meta in metadata:
        case = summaries["cases"][meta["case_id"]]
        ev = case["event"]
        report.extend([
            "## " + meta["event_name"],
            "",
            f"USGS ComCat: {ev['id']} — {ev.get('place')}",
            f"Origin: {ev['time_utc']}; epicentre {ev['latitude']:.3f}, {ev['longitude']:.3f}; depth {ev['depth_km']} km; magnitude {ev['magnitude']}",
            f"Forecast cutoff: {meta['cutoff_utc']}",
            f"Moment tensor / finite-fault product update: {meta['source_solution_update_utc']}",
            f"Training history: {meta['training_event_count_m_ge_6_5']} events M>=6.5 over {meta['training_years']} years",
            f"Physical status: {meta['physical_data_status'].get('status')}; K2 physical coverage {meta.get('k2_physical_coverage_fraction')}; stress coverage {meta['physical_data_status'].get('stress_coverage_fraction')}",
            f"Fallback mechanism inserted: {meta.get('fallback_mechanism_attached')}",
            "",
            "| Model | Approx global P(>=1 event), 30d | 90d | 365d | Nearby cell rank within 1000 km, 90d |",
            "|---|---:|---:|---:|---:|",
        ])
        for model in MODEL_NAMES:
            items = case["models"][model]["horizons"]
            def pct(day: int) -> str:
                x = next(v for v in items if v["days"] == day)
                p = x.get("global_probability_any_event_approx")
                return f"{100*p:.3f}%" if p is not None else "n/a"
            rank = next(v for v in items if v["days"] == 90).get("nearest_trigger_cell_local_rank")
            report.append(
                f"| {model} ({case['models'][model]['status']}) | {pct(30)} | {pct(90)} | {pct(365)} | {rank if rank is not None else 'n/a'} |"
            )
        report.extend(["", "### Top cells at the 90-day horizon", ""])
        for model in MODEL_NAMES:
            item = next(v for v in case["models"][model]["horizons"] if v["days"] == 90)
            top = item.get("top_cells") or []
            points = "; ".join(
                f"{x['latitude']:.1f}, {x['longitude']:.1f} ({100*x['probability']:.4f}%)"
                for x in top[:5]
            )
            report.append(f"- {model}: {points or 'probability surface unavailable'}")
        report.extend(["", "### Observed events after cutoff", ""])
        k0_items = case["models"]["K0"]["horizons"]
        for item in k0_items:
            events = item["observed_events"]
            sample = ", ".join(
                f"M{x['magnitude']:.1f} at {x['latitude']:.2f}, {x['longitude']:.2f} on {x['time'][:10]}"
                for x in events[:6]
            ) or "No M>=6.5 events recorded"
            state = "complete horizon" if item["fully_observed"] else f"partial, {item['elapsed_days']:.1f} of {item['days']} days elapsed"
            report.append(f"- {item['days']} days ({state}): {sample}")
        report.append("")

    report.extend([
        "## Limitations",
        "",
        "A single trigger case cannot establish predictive skill. Brier score is calculated only when the full horizon has elapsed; incomplete horizons are not scored as zero events.",
        "The global-any-event probability is an independence approximation over grid cells and is not a calibrated probability for a specific earthquake.",
        "Coupling Cloud and Slab2 are modern retrospective geophysical layers, not frozen historical snapshots.",
        "Current ComCat is not a versioned historical catalogue. Event occurrence times and current product update timestamps are used for filtering.",
        "PB2002 receiver orientations are scenarios, not a detailed active-fault inventory. The 500-km grid cannot resolve individual fault segments.",
        "Fallback moment tensors, where required, are copied from the timestamped public source cited in case_source_checks.json.",
        "",
        "Reproducibility files: forecast_summary.json, scores.csv, catalog snapshot, source checks, and the frozen NPZ forecast surfaces.",
    ])
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Finished: {output}", flush=True)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coupling-dir", default=str(ROOT / "research" / "data" / "coupling_cloud"))
    parser.add_argument("--download-coupling", action="store_true")
    parser.add_argument("--slab2-dir", default=str(ROOT / "research" / "data" / "slab2"))
    parser.add_argument("--download-slab2", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "research" / "outputs" / "2026-trigger-cases"))
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
