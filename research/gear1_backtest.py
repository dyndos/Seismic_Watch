#!/usr/bin/env python3
"""Spatially score an original GEAR1 CSEP XML forecast against a normalized catalogue.

The XML is streamed cell-by-cell; the full 6.48-million-cell forecast is never
held in memory. The primary score is spatial information gain versus a
spherical-area-uniform forecast with the same global expected count.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_N_LON = 3600
DEFAULT_N_LAT = 1800
DEFAULT_STEP = 0.1
DEFAULT_DEPTH_MIN = 0.0
DEFAULT_DEPTH_MAX = 70.0
BIN_TAGS = {"bin", "magnitudeBin", "magBin"}
METADATA_TAGS = {
    "modelName", "version", "author", "issueDate", "forecastStartDate",
    "forecastEndDate", "forecastDuration", "magnitudeMinValue",
    "magnitudeBinDimension", "lastMagBinOpen",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_datetime(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    result = datetime.fromisoformat(raw)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_cell_values(cell: ET.Element) -> list[float]:
    """Read either CSEP child-bin values or the compact text-bin representation."""
    children = [node for node in cell.iter() if node is not cell and local_name(node.tag) in BIN_TAGS]
    if children:
        result: list[float] = []
        for node in children:
            raw = (node.text or node.attrib.get("value") or "").strip()
            if not raw:
                raise ValueError("empty <bin> value")
            result.append(float(raw))
        return result
    raw_text = " ".join(part.strip() for part in cell.itertext() if part.strip())
    return [float(token) for token in re.split(r"[\s,;]+", raw_text) if token]


class HashingReader:
    def __init__(self, path: Path) -> None:
        self.stream = path.open("rb")
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self.stream.read(size)
        self.digest.update(chunk)
        return chunk

    def close(self) -> None:
        self.stream.close()

    @property
    def sha256(self) -> str:
        return self.digest.hexdigest()


def cell_index(lat: float, lon: float, step: float, n_lat: int, n_lon: int) -> tuple[int, int]:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("non-finite event/cell coordinates")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("coordinates outside geographic bounds")
    # Longitude is periodic: +180° and -180° identify the same meridian.
    lon = ((lon + 180.0) % 360.0) - 180.0
    i_lat = min(int(math.floor((lat + 90.0) / step)), n_lat - 1)
    i_lon = min(int(math.floor((lon + 180.0) / step)), n_lon - 1)
    if i_lat < 0 or i_lon < 0:
        raise ValueError("coordinates outside forecast grid")
    return i_lat, i_lon


def suffix_sums(values: list[float | int]) -> list[float | int]:
    result: list[float | int] = [0] * len(values)
    total: float | int = 0
    for index in range(len(values) - 1, -1, -1):
        total += values[index]
        result[index] = total
    return result


def load_events(
    catalogue_path: Path,
    *,
    start: datetime,
    end: datetime,
    issue_date: datetime | None,
    magnitude_min: float,
    magnitude_step: float,
    n_bins: int,
    depth_min: float,
    depth_max: float,
    grid_step: float,
    n_lat: int,
    n_lon: int,
    summary_degrees: float,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    events_by_cell: dict[int, list[dict[str, Any]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    seen_ids: set[str] = set()
    summary_per_lat = int(round(summary_degrees / grid_step))
    summary_per_lon = summary_per_lat
    summary_n_lon = int(round(n_lon / summary_per_lon))

    with catalogue_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"event_id", "origin_time", "latitude", "longitude", "depth_km", "mw", "mw_eligible"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Catalogue is missing required columns: {sorted(missing)}")
        for row in reader:
            if str(row.get("mw_eligible", "")).strip().lower() not in {"true", "1", "yes"}:
                excluded["not_mw_eligible"] += 1
                continue
            mag = finite_number(row.get("mw"))
            if mag is None:
                excluded["missing_or_invalid_mw"] += 1
                continue
            if mag < magnitude_min:
                excluded["below_forecast_magnitude"] += 1
                continue
            depth = finite_number(row.get("depth_km"))
            if depth is None:
                excluded["unknown_depth"] += 1
                continue
            if not depth_min <= depth <= depth_max:
                excluded["outside_depth_layer"] += 1
                continue
            try:
                origin = parse_datetime(str(row.get("origin_time", "")))
            except (ValueError, TypeError):
                excluded["invalid_origin_time"] += 1
                continue
            if not start <= origin < end:
                excluded["outside_forecast_period"] += 1
                continue
            lat, lon = finite_number(row.get("latitude")), finite_number(row.get("longitude"))
            if lat is None or lon is None:
                excluded["invalid_coordinates"] += 1
                continue
            try:
                lat_idx, lon_idx = cell_index(lat, lon, grid_step, n_lat, n_lon)
            except ValueError:
                excluded["invalid_coordinates"] += 1
                continue
            event_id = str(row.get("event_id") or "").strip()
            if not event_id:
                excluded["missing_event_id"] += 1
                continue
            if event_id in seen_ids:
                raise ValueError(f"Duplicate event_id in catalogue: {event_id}")
            seen_ids.add(event_id)

            # GEAR1 bins represent [5.95, 6.05), [6.05, 6.15), ...;
            # the final bin is open-ended (m >= 8.95).
            bin_index = int(math.floor((mag - magnitude_min) / magnitude_step + 1e-9))
            bin_index = min(bin_index, n_bins - 1)
            post_issue = issue_date is not None and origin > issue_date
            cell_id = lat_idx * n_lon + lon_idx
            summary_id = (lat_idx // summary_per_lat) * summary_n_lon + (lon_idx // summary_per_lon)
            event = {
                "event_id": event_id,
                "origin_time": origin.isoformat().replace("+00:00", "Z"),
                "latitude": lat,
                "longitude": lon,
                "depth_km": depth,
                "mw": mag,
                "magnitude_bin_index": bin_index,
                "magnitude_bin_lower_edge": round(magnitude_min + bin_index * magnitude_step, 6),
                "cell_lat_index": lat_idx,
                "cell_lon_index": lon_idx,
                "cell_id": cell_id,
                "summary_cell_id": summary_id,
                "post_issue": post_issue,
            }
            events.append(event)
            events_by_cell[cell_id].append(event)

    return events, events_by_cell, {
        "input_rows_eligible_for_scoring": len(events),
        "excluded_rows_by_reason": dict(excluded),
        "unique_event_ids": len(seen_ids),
        "depth_range_km": [depth_min, depth_max],
        "minimum_magnitude": magnitude_min,
        "magnitude_rule": "incremental bins [lower, upper); final bin open-ended",
        "period_rule": "forecast interval is start-inclusive and end-exclusive; post-issue interval excludes events at or before issueDate",
    }


def spherical_row_area_fraction(lat_index: int, step: float, n_lon: int, n_lat: int) -> float:
    low = math.radians(-90.0 + lat_index * step)
    high = math.radians(-90.0 + (lat_index + 1) * step)
    domain_low = math.radians(-90.0)
    domain_high = math.radians(-90.0 + n_lat * step)
    total_lat_weight = math.sin(domain_high) - math.sin(domain_low)
    return (math.sin(high) - math.sin(low)) / (total_lat_weight * n_lon)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_backtest(
    xml_path: Path,
    catalogue_path: Path,
    output_dir: Path,
    *,
    n_lon: int = DEFAULT_N_LON,
    n_lat: int = DEFAULT_N_LAT,
    grid_step: float = DEFAULT_STEP,
    summary_degrees: float = 5.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if n_lon <= 0 or n_lat <= 0 or grid_step <= 0:
        raise ValueError("Grid dimensions and step must be positive")
    if abs((360.0 / summary_degrees) - round(360.0 / summary_degrees)) > 1e-8:
        raise ValueError("summary_degrees must divide 360 exactly")
    if abs((180.0 / summary_degrees) - round(180.0 / summary_degrees)) > 1e-8:
        raise ValueError("summary_degrees must divide 180 exactly")
    cells_per_group = summary_degrees / grid_step
    if abs(cells_per_group - round(cells_per_group)) > 1e-8:
        raise ValueError("summary_degrees must be an integer multiple of the forecast grid step")
    cells_per_group = int(round(cells_per_group))
    if n_lon % cells_per_group or n_lat % cells_per_group:
        raise ValueError("summary grid must divide the configured forecast grid dimensions")

    reader = HashingReader(xml_path)
    metadata: dict[str, str] = {}
    cell_dimension: dict[str, str] = {}
    depth_layer: dict[str, str] = {}
    depth_layer_count = 0
    forecast_data_seen = False
    cells_seen = bytearray((n_lon * n_lat + 7) // 8)
    cell_count = 0
    zero_count = 0
    negative_count = 0
    nonfinite_count = 0
    magnitude_sums = [0.0] * 31
    # Kahan compensation for stable sums of millions of small expected counts.
    magnitude_comp = [0.0] * 31
    summary_n_lon = int(round(n_lon / cells_per_group))
    summary_n_lat = int(round(n_lat / cells_per_group))
    summary_bins = [[0.0] * 31 for _ in range(summary_n_lon * summary_n_lat)]
    events: list[dict[str, Any]] = []
    events_by_cell: dict[int, list[dict[str, Any]]] = {}
    catalogue_meta: dict[str, Any] = {}
    forecast_start: datetime | None = None
    forecast_end: datetime | None = None
    issue_date: datetime | None = None
    magnitude_min: float | None = None
    magnitude_step: float | None = None
    n_bins = 31

    # The CSEP metadata precedes the first cell; load the catalogue at that point.
    catalogue_loaded = False
    summary_obs_full: list[list[int]] | None = None
    summary_obs_post: list[list[int]] | None = None
    observed_full_bins = [0] * 31
    observed_post_bins = [0] * 31
    model_event_log_full = [0.0] * 31
    model_event_log_post = [0.0] * 31
    uniform_area_log_full = [0.0] * 31
    uniform_area_log_post = [0.0] * 31
    zero_rate_events_full = [0] * 31
    zero_rate_events_post = [0] * 31

    try:
        stack: list[ET.Element] = []
        for event_type, elem in ET.iterparse(reader, events=("start", "end")):
            tag = local_name(elem.tag)
            if event_type == "start":
                stack.append(elem)
                if len(stack) == 1:
                    if tag != "CSEPForecast":
                        raise ValueError(f"Unexpected XML root element: {tag}")
                    if not ("csep" in elem.tag.lower() and "forecast" in elem.tag.lower()):
                        raise ValueError(f"Unrecognized CSEP forecast namespace: {elem.tag!r}")
                elif tag == "forecastData":
                    forecast_data_seen = True
                elif tag in {"cellDimension", "defaultCellDimension"}:
                    cell_dimension = dict(elem.attrib)
                elif tag == "depthLayer":
                    depth_layer_count += 1
                    depth_layer = dict(elem.attrib)
                continue

            if tag in METADATA_TAGS:
                metadata[tag] = (elem.text or "").strip()

            if tag == "cell" and not catalogue_loaded:
                forecast_start = parse_datetime(metadata["forecastStartDate"])
                forecast_end = parse_datetime(metadata["forecastEndDate"])
                issue_date = parse_datetime(metadata["issueDate"]) if metadata.get("issueDate") else None
                magnitude_min = float(metadata["magnitudeMinValue"])
                magnitude_step = float(metadata["magnitudeBinDimension"])
                if magnitude_step <= 0:
                    raise ValueError("magnitudeBinDimension must be positive")
                if metadata.get("lastMagBinOpen") != "1":
                    raise ValueError("GEAR1 XML is expected to mark the final magnitude bin as open")
                if abs(float(cell_dimension.get("latRange", grid_step)) - grid_step) > 1e-8:
                    raise ValueError("XML latitude cell dimension does not match requested grid step")
                if abs(float(cell_dimension.get("lonRange", grid_step)) - grid_step) > 1e-8:
                    raise ValueError("XML longitude cell dimension does not match requested grid step")
                depth_min = float(depth_layer.get("min", DEFAULT_DEPTH_MIN))
                depth_max = float(depth_layer.get("max", DEFAULT_DEPTH_MAX))
                events, events_by_cell, catalogue_meta = load_events(
                    catalogue_path,
                    start=forecast_start,
                    end=forecast_end,
                    issue_date=issue_date,
                    magnitude_min=magnitude_min,
                    magnitude_step=magnitude_step,
                    n_bins=n_bins,
                    depth_min=depth_min,
                    depth_max=depth_max,
                    grid_step=grid_step,
                    n_lat=n_lat,
                    n_lon=n_lon,
                    summary_degrees=summary_degrees,
                )
                summary_obs_full = [[0] * n_bins for _ in range(summary_n_lon * summary_n_lat)]
                summary_obs_post = [[0] * n_bins for _ in range(summary_n_lon * summary_n_lat)]
                for item in events:
                    idx = item["magnitude_bin_index"]
                    observed_full_bins[idx] += 1
                    summary_obs_full[item["summary_cell_id"]][idx] += 1
                    if item["post_issue"]:
                        observed_post_bins[idx] += 1
                        summary_obs_post[item["summary_cell_id"]][idx] += 1
                catalogue_loaded = True

            if tag == "cell":
                if not catalogue_loaded:
                    raise ValueError("XML cells appeared before forecast metadata")
                cell_count += 1
                try:
                    lat = float(elem.attrib["lat"])
                    lon = float(elem.attrib["lon"])
                    lat_idx, lon_idx = cell_index(lat, lon, grid_step, n_lat, n_lon)
                    values = parse_cell_values(elem)
                except (KeyError, ValueError, OverflowError) as exc:
                    raise ValueError(f"Invalid cell #{cell_count}: {exc}") from exc
                if len(values) != n_bins:
                    raise ValueError(f"Cell #{cell_count} has {len(values)} bins; expected {n_bins}")
                cell_id = lat_idx * n_lon + lon_idx
                byte_index, bit_index = divmod(cell_id, 8)
                mask = 1 << bit_index
                if cells_seen[byte_index] & mask:
                    raise ValueError(f"Duplicate spatial cell at lat={lat}, lon={lon}")
                cells_seen[byte_index] |= mask

                checked_values: list[float] = []
                for index, raw_value in enumerate(values):
                    value = float(raw_value)
                    if not math.isfinite(value):
                        nonfinite_count += 1
                        raise ValueError(f"Non-finite forecast value in cell #{cell_count}, bin {index}")
                    if value < 0:
                        negative_count += 1
                        raise ValueError(f"Negative forecast value in cell #{cell_count}, bin {index}")
                    if value == 0:
                        zero_count += 1
                    checked_values.append(value)
                    y = value - magnitude_comp[index]
                    t = magnitude_sums[index] + y
                    magnitude_comp[index] = (t - magnitude_sums[index]) - y
                    magnitude_sums[index] = t

                summary_id = (lat_idx // cells_per_group) * summary_n_lon + (lon_idx // cells_per_group)
                for index, value in enumerate(checked_values):
                    summary_bins[summary_id][index] += value

                cell_events = events_by_cell.get(cell_id, [])
                if cell_events:
                    cumulative_lambda = suffix_sums(checked_values)
                    cumulative_event_counts = suffix_sums([
                        sum(1 for item in cell_events if item["magnitude_bin_index"] == index)
                        for index in range(n_bins)
                    ])
                    area_fraction = spherical_row_area_fraction(lat_idx, grid_step, n_lon, n_lat)
                    for threshold_index in range(n_bins):
                        count_full = int(cumulative_event_counts[threshold_index])
                        count_post = sum(
                            1 for item in cell_events
                            if item["post_issue"] and item["magnitude_bin_index"] >= threshold_index
                        )
                        lam = float(cumulative_lambda[threshold_index])
                        if count_full:
                            if lam > 0:
                                model_event_log_full[threshold_index] += count_full * math.log(lam)
                            else:
                                zero_rate_events_full[threshold_index] += count_full
                                model_event_log_full[threshold_index] = -math.inf
                            uniform_area_log_full[threshold_index] += count_full * math.log(area_fraction)
                        if count_post:
                            if lam > 0:
                                model_event_log_post[threshold_index] += count_post * math.log(lam)
                            else:
                                zero_rate_events_post[threshold_index] += count_post
                                model_event_log_post[threshold_index] = -math.inf
                            uniform_area_log_post[threshold_index] += count_post * math.log(area_fraction)
                    for item in cell_events:
                        idx = item["magnitude_bin_index"]
                        item["_cell_incremental_lambda"] = checked_values[idx]
                        item["_cell_cumulative_lambda"] = float(cumulative_lambda[idx])
                        item["_area_fraction"] = area_fraction

                if len(stack) >= 2:
                    stack[-2].remove(elem)
                elem.clear()

            if stack and stack[-1] is elem:
                stack.pop()

    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc
    finally:
        reader.close()

    if not forecast_data_seen or not catalogue_loaded:
        raise ValueError("Missing forecastData or forecast metadata")
    if depth_layer_count != 1:
        raise ValueError(f"Expected exactly one depthLayer; found {depth_layer_count}")
    total_cells = n_lon * n_lat
    unique_cells = sum(byte.bit_count() for byte in cells_seen)
    if cell_count != total_cells or unique_cells != total_cells:
        raise ValueError(
            f"Grid incomplete: read {cell_count:,} cells and found {unique_cells:,} unique; expected {total_cells:,}"
        )
    assert forecast_start is not None and forecast_end is not None and magnitude_min is not None and magnitude_step is not None
    expected_cumulative = suffix_sums(magnitude_sums)
    event_match_rows: list[dict[str, Any]] = []
    fraction_post = post_fraction(forecast_start, forecast_end, issue_date)
    for item in events:
        idx = item["magnitude_bin_index"]
        lam_bin = float(item.pop("_cell_incremental_lambda"))
        lam_threshold = float(item.pop("_cell_cumulative_lambda"))
        area_fraction = float(item.pop("_area_fraction"))
        uniform_lam = float(expected_cumulative[idx]) * area_fraction
        item["forecast_expected_incremental_bin_full_period"] = lam_bin
        item["forecast_expected_cumulative_mw_ge_bin_full_period"] = lam_threshold
        item["uniform_expected_cumulative_mw_ge_bin_full_period"] = uniform_lam
        item["spatial_gain_bits_at_event_threshold_full_period"] = (
            math.log2(lam_threshold / uniform_lam)
            if lam_threshold > 0 and uniform_lam > 0 else None
        )
        item["forecast_expected_incremental_bin_post_issue"] = (
            lam_bin * fraction_post if item["post_issue"] else None
        )
        item["forecast_expected_cumulative_mw_ge_bin_post_issue"] = (
            lam_threshold * fraction_post if item["post_issue"] else None
        )
        item["spatial_gain_bits_at_event_threshold_post_issue"] = (
            item["spatial_gain_bits_at_event_threshold_full_period"]
            if item["post_issue"] else None
        )
        event_match_rows.append(item)
    observed_cumulative_full = suffix_sums(observed_full_bins)
    observed_cumulative_post = suffix_sums(observed_post_bins)

    def make_scores(
        observed: list[int], expected: list[float], model_log: list[float],
        area_log: list[float], zero_events: list[int], exposure: float,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index in range(n_bins):
            n = int(observed[index])
            lam = float(expected[index]) * exposure
            gain: float | None
            bits: float | None
            if n == 0:
                gain, bits = 0.0, None
            elif lam <= 0:
                gain, bits = None, None
            elif int(zero_events[index]) > 0 or (math.isinf(model_log[index]) and model_log[index] < 0):
                # JSON has no portable numeric -infinity; the companion flag
                # states that the true point-process log score is negative infinity.
                gain, bits = None, None
            else:
                uniform_log = n * math.log(lam) + area_log[index]
                gain = model_log[index] + n * math.log(exposure) - uniform_log if exposure > 0 else None
                bits = gain / (n * math.log(2.0)) if gain is not None else None
            output.append({
                "magnitude_threshold": round(magnitude_min + index * magnitude_step, 6),
                "observed_events": n,
                "expected_events": lam,
                "observed_expected_ratio": (n / lam) if lam > 0 else None,
                "count_residual_observed_minus_expected": n - lam,
                "spatial_log_likelihood_gain_nats_vs_area_uniform": gain,
                "spatial_information_gain_bits_per_event": bits,
                "events_in_zero_rate_cells": int(zero_events[index]),
                "score_is_negative_infinity_due_to_zero_rate": int(zero_events[index]) > 0,
            })
        return output

    full_scores = make_scores(
        observed_cumulative_full, expected_cumulative, model_event_log_full,
        uniform_area_log_full, zero_rate_events_full, 1.0,
    )
    post_scores = make_scores(
        observed_cumulative_post, expected_cumulative, model_event_log_post,
        uniform_area_log_post, zero_rate_events_post, fraction_post,
    )

    event_fields = [
        "event_id", "origin_time", "latitude", "longitude", "depth_km", "mw",
        "magnitude_bin_lower_edge", "cell_lat_index", "cell_lon_index",
        "forecast_expected_incremental_bin_full_period",
        "forecast_expected_cumulative_mw_ge_bin_full_period",
        "uniform_expected_cumulative_mw_ge_bin_full_period",
        "spatial_gain_bits_at_event_threshold_full_period",
        "post_issue", "forecast_expected_incremental_bin_post_issue",
        "forecast_expected_cumulative_mw_ge_bin_post_issue",
        "spatial_gain_bits_at_event_threshold_post_issue",
    ]
    write_csv(output_dir / "gear1_event_matches.csv", event_fields, event_match_rows)

    spatial_rows: list[dict[str, Any]] = []
    for summary_id in range(summary_n_lon * summary_n_lat):
        iy, ix = divmod(summary_id, summary_n_lon)
        lat_min = -90.0 + iy * summary_degrees
        lon_min = -180.0 + ix * summary_degrees
        row: dict[str, Any] = {
            "lat_min": lat_min,
            "lat_max": lat_min + summary_degrees,
            "lat_center": lat_min + summary_degrees / 2.0,
            "lon_min": lon_min,
            "lon_max": lon_min + summary_degrees,
            "lon_center": lon_min + summary_degrees / 2.0,
        }
        exp_bins = summary_bins[summary_id]
        obs_full_bins = summary_obs_full[summary_id] if summary_obs_full is not None else [0] * n_bins
        obs_post_bins = summary_obs_post[summary_id] if summary_obs_post is not None else [0] * n_bins
        exp_cum = suffix_sums(exp_bins)
        obs_full_cum = suffix_sums(obs_full_bins)
        obs_post_cum = suffix_sums(obs_post_bins)
        for index in range(n_bins):
            threshold = round(magnitude_min + index * magnitude_step, 2)
            row[f"expected_mw_ge_{threshold:.2f}_full_period"] = exp_cum[index]
            row[f"observed_mw_ge_{threshold:.2f}_full_period"] = obs_full_cum[index]
            row[f"expected_mw_ge_{threshold:.2f}_post_issue"] = exp_cum[index] * fraction_post
            row[f"observed_mw_ge_{threshold:.2f}_post_issue"] = obs_post_cum[index]
        spatial_rows.append(row)
    spatial_fields = list(spatial_rows[0].keys()) if spatial_rows else []
    write_csv(output_dir / "gear1_spatial_summary.csv", spatial_fields, spatial_rows)

    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    result = {
        "schema_version": "1.0.0",
        "model": metadata.get("modelName", "GEAR1"),
        "forecast_metadata": {
            "forecast_start_utc": forecast_start.isoformat().replace("+00:00", "Z"),
            "forecast_end_utc": forecast_end.isoformat().replace("+00:00", "Z"),
            "issue_date_utc": issue_date.isoformat().replace("+00:00", "Z") if issue_date else None,
            "magnitude_bin_lower_edge_first": magnitude_min,
            "magnitude_bin_width": magnitude_step,
            "magnitude_bins": n_bins,
            "last_magnitude_bin_open": metadata.get("lastMagBinOpen") == "1",
            "depth_layer_km": [float(depth_layer.get("min", depth_min)), float(depth_layer.get("max", depth_max))],
            "grid_degrees": [grid_step, grid_step],
            "summary_grid_degrees": summary_degrees,
        },
        "xml": {
            "path": str(xml_path),
            "size_bytes": xml_path.stat().st_size,
            "sha256": reader.sha256,
            "cells_parsed": cell_count,
            "unique_cells": unique_cells,
            "zero_values": zero_count,
            "negative_values": negative_count,
            "nonfinite_values": nonfinite_count,
        },
        "catalogue": {
            "path": str(catalogue_path),
            "sha256": sha256_file(catalogue_path),
            **catalogue_meta,
        },
        "windows": {
            "full_hindcast": {
                "start_inclusive": forecast_start.isoformat().replace("+00:00", "Z"),
                "end_exclusive": forecast_end.isoformat().replace("+00:00", "Z"),
                "forecast_exposure_fraction": 1.0,
                "status": "hindcast_with_catalogue_cutoff_2013_12_29_not_a_pre_2014_operational_issue",
                "scores_by_magnitude_threshold": full_scores,
            },
            "post_issue": {
                "start_exclusive": issue_date.isoformat().replace("+00:00", "Z") if issue_date else None,
                "end_exclusive": forecast_end.isoformat().replace("+00:00", "Z"),
                "forecast_exposure_fraction": fraction_post,
                "status": "post_issue_subset_only" if issue_date else "not_available_no_issue_date",
                "scores_by_magnitude_threshold": post_scores,
            },
        },
        "outputs": [
            "gear1_backtest_metrics.json",
            "gear1_event_matches.csv",
            "gear1_spatial_summary.csv",
        ],
        "interpretation": {
            "primary_spatial_score": "log-likelihood gain of the GEAR1 spatial distribution over an area-uniform forecast with the same global expected event count at each magnitude threshold; divided by observed events and converted to bits/event",
            "positive_information_gain": "GEAR1 assigns more probability intensity to observed event locations than the equal-total-rate area-uniform reference",
            "negative_information_gain": "GEAR1 assigns less probability intensity to observed event locations than the equal-total-rate area-uniform reference",
            "count_calibration": "observed_expected_ratio compares observed count with XML expected count; it is separate from the spatial score",
            "limitations": [
                "This is a single-year global retrospective evaluation, not a multi-year skill estimate.",
                "The catalogue is the modern normalized snapshot supplied to the script; it is not an as-of-2014 event bulletin.",
                "The full-year window is a hindcast, because XML issueDate is after forecastStartDate.",
                "The post-issue window is not a new forecast; it is the subset after the XML issueDate scaled by the corresponding exposure fraction.",
                "No magnitude-of-completeness correction, event-location uncertainty integration, or time-dependent aftershock model is applied.",
                "The area-uniform reference isolates spatial skill; total-count calibration is reported separately.",
                "This scoring implementation is a transparent diagnostic, not a claim of formal CSEP test-suite certification.",
            ],
        },
    }
    report_path = output_dir / "gear1_backtest_metrics.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def post_fraction(start: datetime, end: datetime, issue: datetime | None) -> float:
    if issue is None:
        return 0.0
    effective_start = max(start, issue)
    if effective_start >= end:
        return 0.0
    return (end - effective_start).total_seconds() / (end - start).total_seconds()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True, help="Original GEAR1.global.forecast.xml")
    parser.add_argument("--catalog", type=Path, required=True, help="global_catalogue_normalized.csv")
    parser.add_argument("--output-dir", type=Path, default=Path("research/outputs/gear1-backtest"))
    parser.add_argument("--summary-grid-degrees", type=float, default=5.0)
    args = parser.parse_args()
    report = run_backtest(
        args.xml, args.catalog, args.output_dir,
        summary_degrees=args.summary_grid_degrees,
    )
    m = report["windows"]["full_hindcast"]["scores_by_magnitude_threshold"][0]
    print(f"GEAR1 backtest complete: {report['catalogue']['input_rows_eligible_for_scoring']:,} events")
    print(f"Mw >= {m['magnitude_threshold']:.2f}: observed={m['observed_events']}, expected={m['expected_events']:.3f}, ratio={m['observed_expected_ratio']}")
    print(args.output_dir / "gear1_backtest_metrics.json")


if __name__ == "__main__":
    main()
