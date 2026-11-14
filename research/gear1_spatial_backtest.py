#!/usr/bin/env python3
"""Spatial Poisson backtest of an original GEAR1 CSEP 1.1 XML forecast.

The XML is streamed cell-by-cell. The script does not load the 6.48-million-cell
forecast into RAM. Observations are read from the normalized catalogue produced
by research.global_catalog; by default only ISC-GEM main-catalogue Mw records
are used for the 2014 evaluation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

N_LONGITUDE = 3600
N_LATITUDE = 1800
N_CELLS = N_LONGITUDE * N_LATITUDE
GRID_STEP = 0.1
MAX_DEPTH_KM = 70.0
DEFAULT_THRESHOLDS = (5.95, 6.45, 6.95, 7.45, 7.95, 8.45, 8.95)
DEFAULT_GRID_THRESHOLDS = (5.95, 6.95, 7.95)
METADATA_TAGS = {
    "modelName", "version", "author", "authorURI", "issueDate",
    "forecastStartDate", "forecastEndDate", "forecastDuration",
    "magnitudeBinDimension", "magnitudeMinValue", "lastMagBinOpen",
}
BIN_TAGS = {"bin", "magnitudeBin", "magBin"}


class KahanSum:
    def __init__(self) -> None:
        self.value = 0.0
        self.correction = 0.0

    def add(self, value: float) -> None:
        adjusted = value - self.correction
        total = self.value + adjusted
        self.correction = (total - self.value) - adjusted
        self.value = total


class HashingReader:
    """File-like reader that calculates SHA-256 while ElementTree reads bytes."""
    def __init__(self, path: Path) -> None:
        self.stream = path.open("rb")
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        block = self.stream.read(size)
        self.digest.update(block)
        return block

    def close(self) -> None:
        self.stream.close()

    @property
    def sha256(self) -> str:
        return self.digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_utc(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def coordinate_to_grid_index(
    longitude: float,
    latitude: float,
    *,
    step: float = GRID_STEP,
    n_longitude: int = N_LONGITUDE,
    n_latitude: int = N_LATITUDE,
) -> tuple[int, int]:
    """Map geographic coordinates into south-to-north, west-to-east cells."""
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        raise ValueError("Event coordinates must be finite")
    if not -180.0 <= longitude <= 180.0 or not -90.0 <= latitude <= 90.0:
        raise ValueError("Event coordinates are outside geographic bounds")
    # Use half-open cells; the north/east outer boundaries belong to the last cell.
    col = min(int(math.floor((longitude + 180.0) / step)), n_longitude - 1)
    row = min(int(math.floor((latitude + 90.0) / step)), n_latitude - 1)
    return row, col


def grid_index_from_xml_center(
    longitude: float,
    latitude: float,
    *,
    step: float = GRID_STEP,
    n_longitude: int = N_LONGITUDE,
    n_latitude: int = N_LATITUDE,
) -> tuple[int, int]:
    """Validate a CSEP cell centre and return its row/column indices."""
    col_float = (longitude - (-180.0 + step / 2.0)) / step
    row_float = (latitude - (-90.0 + step / 2.0)) / step
    col, row = int(round(col_float)), int(round(row_float))
    if not (0 <= col < n_longitude and 0 <= row < n_latitude):
        raise ValueError(f"XML cell centre outside expected grid: lon={longitude}, lat={latitude}")
    if abs(col_float - col) > 0.0051 / step or abs(row_float - row) > 0.0051 / step:
        raise ValueError(f"XML cell is not on the {step}-degree centre grid: lon={longitude}, lat={latitude}")
    return row, col


def load_observations(
    catalogue_path: Path,
    thresholds: tuple[float, ...],
    forecast_start: datetime,
    forecast_end: datetime,
    issue_date: datetime,
    source_filter: str = "ISC-GEM-main",
) -> tuple[dict[str, list[Counter[int]]], dict[str, Any]]:
    """Load qualifying events into per-threshold, per-window sparse cell counts."""
    windows: dict[str, list[Counter[int]]] = {
        "full_period_hindcast": [Counter() for _ in thresholds],
        "post_issue_period": [Counter() for _ in thresholds],
    }
    stats: Counter[str] = Counter()
    all_cell_ids: set[int] = set()

    with catalogue_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"source", "origin_time", "latitude", "longitude", "depth_km", "mw", "mw_eligible"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Normalized catalogue lacks required columns: {sorted(missing)}")

        for row in reader:
            stats["catalogue_rows"] += 1
            if source_filter != "all" and row.get("source", "") != source_filter:
                stats["excluded_source"] += 1
                continue
            if not parse_bool(row.get("mw_eligible", "")):
                stats["excluded_not_mw_eligible"] += 1
                continue
            try:
                event_time = parse_utc(row["origin_time"])
                magnitude = float(row["mw"])
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (ValueError, TypeError, KeyError):
                stats["excluded_invalid_time_magnitude_or_coordinates"] += 1
                continue
            if not (forecast_start <= event_time < forecast_end):
                stats["excluded_outside_forecast_interval"] += 1
                continue
            try:
                depth = float(row["depth_km"])
            except (TypeError, ValueError):
                stats["excluded_unknown_depth"] += 1
                continue
            if not math.isfinite(depth) or not 0.0 <= depth <= MAX_DEPTH_KM:
                stats["excluded_not_shallow_0_70_km"] += 1
                continue
            try:
                grid_row, grid_col = coordinate_to_grid_index(longitude, latitude)
            except ValueError:
                stats["excluded_invalid_coordinates"] += 1
                continue

            cell_id = grid_row * N_LONGITUDE + grid_col
            all_cell_ids.add(cell_id)
            stats["eligible_full_period_events"] += 1
            windows_to_increment = ["full_period_hindcast"]
            if event_time > issue_date:
                windows_to_increment.append("post_issue_period")
                stats["eligible_post_issue_events"] += 1
            for threshold_index, threshold in enumerate(thresholds):
                if magnitude >= threshold:
                    for window_name in windows_to_increment:
                        windows[window_name][threshold_index][cell_id] += 1

    stats["distinct_cells_with_any_eligible_event"] = len(all_cell_ids)
    if not windows["full_period_hindcast"] or not sum(windows["full_period_hindcast"][0].values()):
        raise ValueError(
            "No eligible ISC-GEM main-catalogue events meet the lowest selected Mw threshold "
            "inside the forecast interval. Check the catalogue file, source filter and date range."
        )
    stats["catalogue_sha256"] = sha256_file(catalogue_path)
    stats["catalogue_source_filter"] = source_filter
    return windows, dict(stats)


def parse_cell_values(cell: ET.Element) -> tuple[list[float], list[float | None]]:
    bin_nodes = [node for node in cell.iter() if node is not cell and local_name(node.tag) in BIN_TAGS]
    values: list[float] = []
    labels: list[float | None] = []
    if bin_nodes:
        for node in bin_nodes:
            raw = (node.text or "").strip() or node.attrib.get("value", "")
            if not raw:
                raise ValueError("Magnitude-bin element has no numeric value")
            values.append(float(raw))
            label = node.attrib.get("m", node.attrib.get("magnitude"))
            labels.append(float(label) if label is not None else None)
    else:
        raw_text = " ".join(part.strip() for part in cell.itertext() if part.strip())
        tokens = [token for token in re.split(r"[\s,;]+", raw_text) if token]
        values = [float(token) for token in tokens]
        labels = [None] * len(values)
    if not values:
        raise ValueError("Cell contains no magnitude values")
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("Cell contains negative or non-finite expected counts")
    return values, labels


def parse_thresholds(raw: str) -> tuple[float, ...]:
    values = tuple(sorted({float(token.strip()) for token in raw.split(",") if token.strip()}))
    if not values or any(not math.isfinite(value) for value in values):
        raise argparse.ArgumentTypeError("Provide one or more finite comma-separated thresholds")
    return values


def make_grid_filename(threshold: float) -> str:
    label = f"{threshold:.2f}".replace(".", "p")
    return f"gear1_expected_count_Mw_ge_{label}.npy"


def uniform_area_fraction_by_row(n_latitude: int = N_LATITUDE, step: float = GRID_STEP) -> list[float]:
    fractions = []
    for row in range(n_latitude):
        lower = math.radians(-90.0 + row * step)
        upper = math.radians(-90.0 + (row + 1) * step)
        fractions.append(math.sin(upper) - math.sin(lower))
    return fractions


def poisson_log_likelihood(
    total_expected: float,
    event_counts: Counter[int],
    cell_expected: dict[int, float],
) -> float:
    """Independent-Poisson log likelihood over all cells, including empty cells."""
    score = -total_expected
    for cell_id, observed in event_counts.items():
        mu = cell_expected.get(cell_id, 0.0)
        if mu <= 0.0:
            return float("-inf")
        score += observed * math.log(mu) - math.lgamma(observed + 1)
    return score


def score_window_threshold(
    *,
    window_name: str,
    threshold: float,
    duration_fraction: float,
    event_counts: Counter[int],
    total_expected_full_period: float,
    event_cell_expected_full_period: dict[int, float],
    area_fraction_by_row: list[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total_expected = total_expected_full_period * duration_fraction
    cell_expected_scaled = {
        cell_id: expected * duration_fraction
        for cell_id, expected in event_cell_expected_full_period.items()
    }
    gear1_ll = poisson_log_likelihood(total_expected, event_counts, cell_expected_scaled)

    total_area_weight = N_LONGITUDE * math.fsum(area_fraction_by_row)
    uniform_cell_expected: dict[int, float] = {}
    for cell_id in event_counts:
        row_index = cell_id // N_LONGITUDE
        uniform_cell_expected[cell_id] = (
            total_expected * area_fraction_by_row[row_index] / total_area_weight
        )
    uniform_ll = poisson_log_likelihood(total_expected, event_counts, uniform_cell_expected)

    observed = sum(event_counts.values())
    gain = gear1_ll - uniform_ll
    summary = {
        "window": window_name,
        "threshold_mw_ge": threshold,
        "duration_fraction_of_xml_interval": duration_fraction,
        "observed_events": observed,
        "occupied_spatial_cells": len(event_counts),
        "expected_events_gear1": total_expected,
        "observed_to_expected_ratio": (observed / total_expected) if total_expected > 0 else None,
        "poisson_log_likelihood_gear1": gear1_ll,
        "poisson_log_likelihood_area_uniform_baseline": uniform_ll,
        "information_gain_nats_vs_area_uniform": gain,
        "information_gain_bits_per_event": (gain / observed / math.log(2.0)) if observed else None,
        "scoring_assumption": "independent Poisson counts in 0.1-degree cells; area-uniform baseline has the same global expected count",
    }

    cell_rows = []
    for cell_id, count in sorted(event_counts.items()):
        row_index, col_index = divmod(cell_id, N_LONGITUDE)
        latitude_center = -90.0 + (row_index + 0.5) * GRID_STEP
        longitude_center = -180.0 + (col_index + 0.5) * GRID_STEP
        gear1_mu = cell_expected_scaled[cell_id]
        uniform_mu = uniform_cell_expected[cell_id]
        cell_rows.append({
            "window": window_name,
            "threshold_mw_ge": threshold,
            "row_index_south_to_north": row_index,
            "column_index_west_to_east": col_index,
            "latitude_center": latitude_center,
            "longitude_center": longitude_center,
            "observed_events": count,
            "gear1_expected_count": gear1_mu,
            "area_uniform_expected_count": uniform_mu,
            "gear1_event_log_term": (count * math.log(gear1_mu) - math.lgamma(count + 1)) if gear1_mu > 0 else None,
            "uniform_event_log_term": (count * math.log(uniform_mu) - math.lgamma(count + 1)) if uniform_mu > 0 else None,
        })
    return summary, cell_rows


def validate_metadata(metadata: dict[str, str], cell_dimension: dict[str, str], depth_layer: dict[str, str]) -> None:
    required = {"forecastStartDate", "forecastEndDate", "issueDate", "magnitudeMinValue", "magnitudeBinDimension"}
    missing = required - set(metadata)
    if missing:
        raise ValueError(f"XML metadata is missing required fields: {sorted(missing)}")
    for key in ("latRange", "lonRange"):
        if key not in cell_dimension or not math.isclose(float(cell_dimension[key]), GRID_STEP, abs_tol=1e-8):
            raise ValueError(f"XML cellDimension {key} must be {GRID_STEP}; got {cell_dimension.get(key)!r}")
    if depth_layer:
        if "min" in depth_layer and not math.isclose(float(depth_layer["min"]), 0.0, abs_tol=1e-8):
            raise ValueError("GEAR1 XML depth layer minimum is not 0 km")
        if "max" in depth_layer and not math.isclose(float(depth_layer["max"]), MAX_DEPTH_KM, abs_tol=1e-8):
            raise ValueError("GEAR1 XML depth layer maximum is not 70 km")


def run_backtest(
    xml_path: Path,
    catalogue_path: Path,
    output_dir: Path,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    grid_thresholds: tuple[float, ...] = DEFAULT_GRID_THRESHOLDS,
    source_filter: str = "ISC-GEM-main",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = HashingReader(xml_path)
    metadata: dict[str, str] = {}
    cell_dimension: dict[str, str] = {}
    depth_layer: dict[str, str] = {}
    depth_layer_count = 0
    forecast_data_seen = False
    root_tag: str | None = None
    cell_count = 0
    unique_cell_count = 0
    numeric_value_count = 0
    zero_value_count = 0
    negative_value_count = 0
    nonfinite_value_count = 0
    seen = bytearray((N_CELLS + 7) // 8)
    bin_count: int | None = None
    bin_labels: list[float | None] | None = None
    expected_sums: dict[float, KahanSum] = {value: KahanSum() for value in thresholds}
    event_counts_by_window: dict[str, list[Counter[int]]] | None = None
    event_cell_ids: set[int] = set()
    event_cell_forecasts: dict[int, dict[float, float]] = {}
    grid_maps: dict[float, np.memmap] = {}
    grid_paths: dict[float, Path] = {}

    try:
        stack: list[ET.Element] = []
        for event, elem in ET.iterparse(reader, events=("start", "end")):
            tag = local_name(elem.tag)
            if event == "start":
                stack.append(elem)
                if len(stack) == 1:
                    root_tag = elem.tag
                    if tag != "CSEPForecast" or "csep" not in elem.tag.lower():
                        raise ValueError(f"Unexpected XML root / namespace: {elem.tag!r}")
                elif tag == "forecastData":
                    forecast_data_seen = True
                elif tag in {"cellDimension", "defaultCellDimension"}:
                    cell_dimension = dict(elem.attrib)
                elif tag == "depthLayer":
                    depth_layer_count += 1
                    if depth_layer_count == 1:
                        depth_layer = dict(elem.attrib)
                continue

            if tag in METADATA_TAGS:
                metadata[tag] = (elem.text or "").strip()

            if tag == "cell":
                cell_count += 1
                if cell_count > N_CELLS:
                    raise ValueError(f"XML contains more than {N_CELLS:,} cells")
                validate_metadata(metadata, cell_dimension, depth_layer)
                if bin_count is None:
                    min_mag = float(metadata["magnitudeMinValue"])
                    mag_step = float(metadata["magnitudeBinDimension"])
                    for threshold in (*thresholds, *grid_thresholds):
                        bin_index = int(round((threshold - min_mag) / mag_step))
                        inferred = min_mag + bin_index * mag_step
                        if bin_index < 0 or abs(inferred - threshold) > 1e-6:
                            raise ValueError(
                                f"Threshold {threshold} does not align with XML magnitude bins "
                                f"(start={min_mag}, step={mag_step})"
                            )
                        if threshold not in expected_sums:
                            expected_sums[threshold] = KahanSum()
                    values, labels = parse_cell_values(elem)
                    bin_count = len(values)
                    if bin_count != 31:
                        raise ValueError(f"Expected 31 magnitude bins per cell, found {bin_count}")
                    bin_labels = labels
                    expected_labels = [min_mag + i * mag_step for i in range(bin_count)]
                    if any(label is None for label in labels):
                        # This XML stores numeric bin values as cell text; infer labels from metadata.
                        bin_labels = expected_labels
                    elif any(abs(float(label) - expected) > 1e-6 for label, expected in zip(labels, expected_labels)):
                        raise ValueError("Explicit XML magnitude labels do not match magnitude metadata")
                    elif len(labels) != bin_count:
                        raise ValueError("Inconsistent explicit magnitude labels")
                    for threshold in (*thresholds, *grid_thresholds):
                        threshold_index = int(round((threshold - min_mag) / mag_step))
                        if threshold_index >= bin_count:
                            raise ValueError(f"Threshold {threshold} is outside the XML magnitude range")
                    event_counts_by_window, observation_meta = load_observations(
                        catalogue_path,
                        thresholds=thresholds,
                        forecast_start=parse_utc(metadata["forecastStartDate"]),
                        forecast_end=parse_utc(metadata["forecastEndDate"]),
                        issue_date=parse_utc(metadata["issueDate"]),
                        source_filter=source_filter,
                    )
                    for window_counts in event_counts_by_window.values():
                        for counter in window_counts:
                            event_cell_ids.update(counter)
                    # Open optional memory-mapped grids only once metadata is known.
                    for threshold in grid_thresholds:
                        path = output_dir / make_grid_filename(threshold)
                        grid_maps[threshold] = np.lib.format.open_memmap(
                            path, mode="w+", dtype=np.float32, shape=(N_LATITUDE, N_LONGITUDE)
                        )
                        grid_paths[threshold] = path
                else:
                    values, labels = parse_cell_values(elem)
                    if len(values) != bin_count:
                        raise ValueError(f"Cell {cell_count} has {len(values)} bins; expected {bin_count}")
                    if labels and any(label is not None for label in labels):
                        if bin_labels and any(
                            a is not None and b is not None and abs(a - b) > 1e-6
                            for a, b in zip(bin_labels, labels)
                        ):
                            raise ValueError(f"Cell {cell_count} has inconsistent magnitude labels")

                try:
                    longitude, latitude = float(elem.attrib["lon"]), float(elem.attrib["lat"])
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"Cell {cell_count} has invalid lon/lat attributes") from exc
                row_index, col_index = grid_index_from_xml_center(longitude, latitude)
                cell_id = row_index * N_LONGITUDE + col_index
                byte_index, bit_index = divmod(cell_id, 8)
                bit = 1 << bit_index
                if seen[byte_index] & bit:
                    raise ValueError(f"Duplicate XML spatial cell at lon={longitude}, lat={latitude}")
                seen[byte_index] |= bit
                unique_cell_count += 1

                # One reverse pass produces all cumulative rates without repeated slicing.
                min_mag = float(metadata["magnitudeMinValue"])
                mag_step = float(metadata["magnitudeBinDimension"])
                selected_indices = {
                    int(round((threshold - min_mag) / mag_step)) for threshold in expected_sums
                }
                grid_indices = {
                    threshold: int(round((threshold - min_mag) / mag_step)) for threshold in grid_thresholds
                }
                cumulative_by_index: dict[int, float] = {}
                running = 0.0
                for index in range(len(values) - 1, -1, -1):
                    running += values[index]
                    if index in selected_indices:
                        cumulative_by_index[index] = running
                for threshold in expected_sums:
                    threshold_index = int(round((threshold - min_mag) / mag_step))
                    expected_sums[threshold].add(cumulative_by_index[threshold_index])
                for threshold, grid in grid_maps.items():
                    grid[row_index, col_index] = cumulative_by_index[grid_indices[threshold]]
                if cell_id in event_cell_ids:
                    event_cell_forecasts[cell_id] = {
                        threshold: cumulative_by_index[int(round((threshold - min_mag) / mag_step))]
                        for threshold in thresholds
                    }

                numeric_value_count += len(values)
                zero_value_count += sum(value == 0.0 for value in values)
                negative_value_count += sum(value < 0.0 for value in values)
                nonfinite_value_count += sum(not math.isfinite(value) for value in values)
                if len(stack) >= 2:
                    stack[-2].remove(elem)
                elem.clear()

            if stack and stack[-1] is elem:
                stack.pop()
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc
    finally:
        reader.close()
        for grid in grid_maps.values():
            grid.flush()

    if event_counts_by_window is None:
        raise ValueError("No <cell> elements were found in the XML")
    if not forecast_data_seen:
        raise ValueError("XML is missing forecastData")
    if depth_layer_count != 1:
        raise ValueError(f"Expected one depthLayer, found {depth_layer_count}")
    if cell_count != N_CELLS or unique_cell_count != N_CELLS:
        raise ValueError(
            f"Incomplete global grid: cells={cell_count:,}, unique={unique_cell_count:,}, expected={N_CELLS:,}"
        )
    if numeric_value_count != N_CELLS * 31:
        raise ValueError(f"Expected {N_CELLS * 31:,} magnitude values; found {numeric_value_count:,}")
    if negative_value_count or nonfinite_value_count:
        raise ValueError("XML contains negative or non-finite forecast values")

    forecast_start = parse_utc(metadata["forecastStartDate"])
    forecast_end = parse_utc(metadata["forecastEndDate"])
    issue_date = parse_utc(metadata["issueDate"])
    if not forecast_start < forecast_end:
        raise ValueError("Invalid forecast interval in XML metadata")
    full_duration = (forecast_end - forecast_start).total_seconds()
    post_start = max(forecast_start, issue_date)
    post_fraction = max(0.0, (forecast_end - post_start).total_seconds() / full_duration)
    full_fraction = 1.0
    window_fractions = {
        "full_period_hindcast": full_fraction,
        "post_issue_period": post_fraction,
    }
    area_rows = uniform_area_fraction_by_row()

    score_rows: list[dict[str, Any]] = []
    cell_rows: list[dict[str, Any]] = []
    for window_name, counters in event_counts_by_window.items():
        fraction = window_fractions[window_name]
        for threshold_index, threshold in enumerate(thresholds):
            counter = counters[threshold_index]
            forecasts = {
                cell_id: event_cell_forecasts[cell_id][threshold]
                for cell_id in counter
                if cell_id in event_cell_forecasts
            }
            if len(forecasts) != len(counter):
                missing_cells = len(counter) - len(forecasts)
                raise ValueError(f"Forecast values missing for {missing_cells} observed cells at Mw>={threshold}")
            summary, rows = score_window_threshold(
                window_name=window_name,
                threshold=threshold,
                duration_fraction=fraction,
                event_counts=counter,
                total_expected_full_period=expected_sums[threshold].value,
                event_cell_expected_full_period=forecasts,
                area_fraction_by_row=area_rows,
            )
            score_rows.append(summary)
            cell_rows.extend(rows)

    cell_csv = output_dir / "gear1_observed_event_cells.csv"
    fieldnames = [
        "window", "threshold_mw_ge", "row_index_south_to_north", "column_index_west_to_east",
        "latitude_center", "longitude_center", "observed_events", "gear1_expected_count",
        "area_uniform_expected_count", "gear1_event_log_term", "uniform_event_log_term",
    ]
    with cell_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cell_rows)

    metadata_out = {
        "xml_sha256": reader.sha256,
        "catalogue_sha256": observation_meta["catalogue_sha256"],
        "xml_root": root_tag,
        "metadata": metadata,
        "cell_dimension": cell_dimension,
        "depth_layer": depth_layer,
        "grid": {
            "rows": N_LATITUDE,
            "columns": N_LONGITUDE,
            "step_degrees": GRID_STEP,
            "row_order": "south_to_north",
            "column_order": "west_to_east",
            "latitude_centres": [-89.95, 89.95],
            "longitude_centres": [-179.95, 179.95],
        },
        "cells_parsed": cell_count,
        "unique_spatial_cells": unique_cell_count,
        "numeric_magnitude_values": numeric_value_count,
        "magnitude_bins_per_cell": bin_count,
        "magnitude_bin_labels": bin_labels,
        "zero_negative_nonfinite_values": [zero_value_count, negative_value_count, nonfinite_value_count],
        "expected_global_counts_over_full_xml_interval": {
            f"mw_ge_{threshold:.2f}": expected_sums[threshold].value for threshold in expected_sums
        },
        "observation_filter": {
            **observation_meta,
            "depth_km_inclusive": [0.0, MAX_DEPTH_KM],
            "magnitude_rule": "Mw >= threshold; ISC-GEM main catalogue only by default",
            "full_period_window": "forecastStartDate <= origin_time < forecastEndDate",
            "post_issue_window": "issueDate < origin_time < forecastEndDate",
        },
        "scoring": {
            "method": "independent-cell Poisson log likelihood",
            "baseline": "uniform rate per square kilometre, normalized to the same global expected count as GEAR1",
            "information_gain_units": "nats; positive favours GEAR1 over area-uniform baseline",
            "declustering": "not applied; earthquake clustering/dependence remains a limitation",
            "time_scaling": "static GEAR1 rates scaled linearly by elapsed fraction for post-issue partial interval",
            "issue_date_caveat": "the full-year window is a retrospective hindcast because issueDate falls inside the declared forecast interval",
        },
        "grid_files": [path.name for path in grid_paths.values()],
        "score_rows": score_rows,
        "observed_event_cells_csv": cell_csv.name,
    }
    summary_path = output_dir / "gear1_spatial_backtest_summary.json"
    summary_path.write_text(json.dumps(metadata_out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return metadata_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True, help="Path to GEAR1.global.forecast.xml")
    parser.add_argument("--catalogue", type=Path, required=True, help="global_catalogue_normalized.csv")
    parser.add_argument("--output", type=Path, default=Path("research/outputs/gear1-2014-backtest"))
    parser.add_argument(
        "--thresholds", type=parse_thresholds,
        default=DEFAULT_THRESHOLDS,
        help="Comma-separated Mw thresholds; defaults to 5.95,6.45,...,8.95",
    )
    parser.add_argument(
        "--grid-thresholds", type=parse_thresholds,
        default=DEFAULT_GRID_THRESHOLDS,
        help="Comma-separated thresholds for 2-D NumPy forecast grids",
    )
    parser.add_argument(
        "--no-grids", action="store_true",
        help="Skip writing 2-D NumPy forecast grids (summary and cell scores are still produced)",
    )
    parser.add_argument(
        "--source-filter", default="ISC-GEM-main",
        help="Catalogue source to use (default: ISC-GEM-main; use 'all' to disable source filtering)",
    )
    args = parser.parse_args()
    grid_thresholds = () if args.no_grids else args.grid_thresholds
    result = run_backtest(
        args.xml, args.catalogue, args.output,
        thresholds=args.thresholds,
        grid_thresholds=grid_thresholds,
        source_filter=args.source_filter,
    )
    print(json.dumps({
        "overall": "passed",
        "xml_sha256": result["xml_sha256"],
        "catalogue_sha256": result["catalogue_sha256"],
        "cells": result["cells_parsed"],
        "score_rows": len(result["score_rows"]),
        "summary": str(args.output / "gear1_spatial_backtest_summary.json"),
        "event_cells": str(args.output / "gear1_observed_event_cells.csv"),
        "grid_files": result["grid_files"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())