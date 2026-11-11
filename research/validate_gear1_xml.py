#!/usr/bin/env python3
"""Stream-validate a large GEAR1 CSEP XML forecast with bounded memory.

Supports the traditional CSEP XML shape:
CSEPForecast/forecastData/depthLayer/cell/bin,
where each cell contains individual <bin m="...">value</bin> elements.
A compact whitespace-separated cell representation is also accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET

N_LONGITUDE = 3600
N_LATITUDE = 1800
N_CELLS = N_LONGITUDE * N_LATITUDE
N_BINS = 31
GRID_STEP = 0.1
BIN_TAGS = {"bin", "magnitudeBin", "magBin"}
METADATA_TAGS = {
    "modelName", "version", "author", "authorURI", "issueDate",
    "forecastStartDate", "forecastEndDate", "forecastDuration",
    "defaultMagBinDimension", "magnitudeBinDimension", "magnitudeMinValue",
    "lastMagBinOpen",
}


class HashingReader:
    """Hash bytes as ElementTree streams through the XML file."""
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


class KahanSum:
    def __init__(self) -> None:
        self.value = 0.0
        self.correction = 0.0

    def add(self, x: float) -> None:
        y = x - self.correction
        t = self.value + y
        self.correction = (t - self.value) - y
        self.value = t


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_expected_summary(path: Path) -> tuple[list[float], list[float], str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    columns = data["step_3_rates"]["columns"]
    rows = data["step_3_rates"]["rows"]
    mi = columns.index("threshold_magnitude")
    ri = columns.index("hybrid_rate_above_threshold_events_per_year")
    thresholds = [float(row[mi]) for row in rows]
    rates = [float(row[ri]) for row in rows]
    return (
        thresholds,
        rates,
        data["configuration"]["forecast_start_utc"],
        data["configuration"]["forecast_end_utc"],
    )


def infer_axis_index(value: float, *, axis: str) -> tuple[int, str] | None:
    """Map either cell-centre or lower-edge CSEP coordinates onto global grid indices."""
    if axis == "lon":
        candidates = [(-179.95, "centre"), (-180.0, "lower_edge")]
        size = N_LONGITUDE
    else:
        candidates = [(-89.95, "centre"), (-90.0, "lower_edge")]
        size = N_LATITUDE

    best: tuple[float, int, str] | None = None
    for origin, mode in candidates:
        raw = (value - origin) / GRID_STEP
        idx = int(round(raw))
        residual = abs(value - (origin + idx * GRID_STEP))
        if 0 <= idx < size and (best is None or residual < best[0]):
            best = (residual, idx, mode)
    if best is None or best[0] > 0.0051:
        return None
    return best[1], best[2]


def parse_cell_values(cell: ET.Element) -> tuple[list[float], list[float | None]]:
    bin_nodes = [
        node for node in cell.iter()
        if node is not cell and local_name(node.tag) in BIN_TAGS
    ]
    values: list[float] = []
    labels: list[float | None] = []

    if bin_nodes:
        for node in bin_nodes:
            raw = (node.text or "").strip()
            if not raw and "value" in node.attrib:
                raw = node.attrib["value"]
            if not raw:
                raise ValueError("A magnitude-bin element has no numeric text/value")
            values.append(float(raw))
            label = node.attrib.get("m", node.attrib.get("magnitude"))
            labels.append(float(label) if label is not None else None)
        return values, labels

    # Some CSEP writers place the 31 numeric rates directly in the cell text.
    raw_text = " ".join(part.strip() for part in cell.itertext() if part.strip())
    tokens = [token for token in re.split(r"[\s,;]+", raw_text) if token]
    values = [float(token) for token in tokens]
    labels = [None] * len(values)
    return values, labels


def close_enough(actual: float, expected: float, tolerance: float = 0.005) -> bool:
    return abs(actual - expected) <= max(5e-4, abs(expected) * tolerance)


def validate(xml_path: Path, summary_path: Path) -> dict[str, object]:
    thresholds, expected_rates, expected_start, expected_end = parse_expected_summary(summary_path)
    if len(thresholds) != N_BINS or len(expected_rates) != N_BINS:
        raise ValueError(f"Expected exactly {N_BINS} thresholds in run-summary JSON")

    reader = HashingReader(xml_path)
    metadata: dict[str, str] = {}
    cell_dimension: dict[str, str] = {}
    depth_layer: dict[str, str] = {}
    root_tag: str | None = None
    forecast_data_seen = False
    depth_layer_seen = 0
    cell_count = 0
    value_count = 0
    zero_count = 0
    negative_count = 0
    nonfinite_count = 0
    min_value = math.inf
    max_value = -math.inf
    first_cells: list[dict[str, float]] = []
    last_cells: list[dict[str, float]] = []
    errors: list[str] = []
    bin_labels: list[float | None] | None = None
    bin_sums = [KahanSum() for _ in range(N_BINS)]
    seen = bytearray((N_CELLS + 7) // 8)
    centre_mode: dict[str, str] = {}

    try:
        stack: list[ET.Element] = []
        for event, elem in ET.iterparse(reader, events=("start", "end")):
            tag = local_name(elem.tag)

            if event == "start":
                stack.append(elem)
                if len(stack) == 1:
                    root_tag = elem.tag
                    if tag != "CSEPForecast":
                        errors.append(f"Unexpected root element: {tag}")
                    elif not (
                        elem.tag.startswith("{")
                        and "csep" in elem.tag.lower()
                        and "forecast" in elem.tag.lower()
                    ):
                        errors.append(f"Root element does not declare a recognized CSEP forecast namespace: {elem.tag!r}")
                elif tag == "forecastData":
                    forecast_data_seen = True
                elif tag == "defaultCellDimension":
                    cell_dimension = dict(elem.attrib)
                elif tag == "depthLayer":
                    depth_layer_seen += 1
                    if depth_layer_seen == 1:
                        depth_layer = dict(elem.attrib)
                continue

            if tag in METADATA_TAGS:
                metadata[tag] = (elem.text or "").strip()

            if tag == "cell":
                cell_count += 1
                if cell_count > N_CELLS:
                    errors.append(f"More than {N_CELLS:,} cells encountered")
                    break

                try:
                    lon = float(elem.attrib["lon"])
                    lat = float(elem.attrib["lat"])
                    if not (math.isfinite(lon) and math.isfinite(lat)):
                        raise ValueError("non-finite coordinate")
                except (KeyError, ValueError) as exc:
                    errors.append(f"Cell {cell_count}: invalid lon/lat attributes ({exc})")
                    lon = lat = math.nan

                if math.isfinite(lon) and math.isfinite(lat):
                    lon_result = infer_axis_index(lon, axis="lon")
                    lat_result = infer_axis_index(lat, axis="lat")
                    if lon_result is None or lat_result is None:
                        if len(errors) < 100:
                            errors.append(f"Cell {cell_count}: coordinate outside or off global 0.1-degree grid ({lon}, {lat})")
                    else:
                        lon_idx, lon_mode = lon_result
                        lat_idx, lat_mode = lat_result
                        if lon_mode != centre_mode.get("lon", lon_mode):
                            if "lon" in centre_mode and len(errors) < 100:
                                errors.append(f"Cell {cell_count}: mixed longitude coordinate convention")
                        else:
                            centre_mode.setdefault("lon", lon_mode)
                        if lat_mode != centre_mode.get("lat", lat_mode):
                            if "lat" in centre_mode and len(errors) < 100:
                                errors.append(f"Cell {cell_count}: mixed latitude coordinate convention")
                        else:
                            centre_mode.setdefault("lat", lat_mode)

                        bit_index = lat_idx * N_LONGITUDE + lon_idx
                        byte_index, bit = divmod(bit_index, 8)
                        mask = 1 << bit
                        if seen[byte_index] & mask:
                            if len(errors) < 100:
                                errors.append(f"Cell {cell_count}: duplicate spatial cell ({lon}, {lat})")
                        else:
                            seen[byte_index] |= mask

                try:
                    values, labels = parse_cell_values(elem)
                except (ValueError, OverflowError) as exc:
                    if len(errors) < 100:
                        errors.append(f"Cell {cell_count}: cannot parse magnitude values ({exc})")
                    values, labels = [], []

                if len(values) != N_BINS:
                    if len(errors) < 100:
                        errors.append(f"Cell {cell_count}: has {len(values)} magnitude values; expected {N_BINS}")
                else:
                    if bin_labels is None:
                        bin_labels = labels
                    elif any(
                        a is not None and b is not None and abs(a - b) > 1e-5
                        for a, b in zip(bin_labels, labels)
                    ):
                        if len(errors) < 100:
                            errors.append(f"Cell {cell_count}: magnitude-bin labels/order differ from the first cell")

                    for index, value in enumerate(values):
                        value_count += 1
                        if not math.isfinite(value):
                            nonfinite_count += 1
                        elif value < 0.0:
                            negative_count += 1
                        else:
                            if value == 0.0:
                                zero_count += 1
                            min_value = min(min_value, value)
                            max_value = max(max_value, value)
                            bin_sums[index].add(value)

                point = {
                    "lon": lon if math.isfinite(lon) else None,
                    "lat": lat if math.isfinite(lat) else None,
                }
                if len(first_cells) < 5:
                    first_cells.append(point)
                last_cells.append(point)
                if len(last_cells) > 5:
                    last_cells.pop(0)

                # Remove processed global cells immediately to bound memory.
                if len(stack) >= 2:
                    stack[-2].remove(elem)
                elem.clear()

            if stack and stack[-1] is elem:
                stack.pop()

        # iterparse consumes the full input on success, so this digest covers the complete file.
    except ET.ParseError as exc:
        errors.append(f"XML parse error: {exc}")
    finally:
        reader.close()

    unique_cells = sum(byte.bit_count() for byte in seen)
    if cell_count != N_CELLS:
        errors.append(f"Expected {N_CELLS:,} cells; parsed {cell_count:,}")
    if unique_cells != N_CELLS:
        errors.append(f"Expected {N_CELLS:,} unique spatial cells; found {unique_cells:,}")
    if value_count != N_CELLS * N_BINS:
        errors.append(f"Expected {N_CELLS * N_BINS:,} numeric values; parsed {value_count:,}")
    if negative_count or nonfinite_count:
        errors.append(f"Invalid forecast values: negative={negative_count:,}, nonfinite={nonfinite_count:,}")

    if not forecast_data_seen:
        errors.append("Missing forecastData element")
    if depth_layer_seen != 1:
        errors.append(f"Expected one depthLayer; found {depth_layer_seen}")
    if not cell_dimension:
        errors.append("Missing defaultCellDimension element")

    # Check fixed metadata when supplied by the XML. Some older CSEP writers use different names.
    if metadata.get("forecastStartDate") and metadata["forecastStartDate"] != expected_start:
        errors.append(f"forecastStartDate={metadata['forecastStartDate']!r}; expected {expected_start!r}")
    if metadata.get("forecastEndDate") and metadata["forecastEndDate"] != expected_end:
        errors.append(f"forecastEndDate={metadata['forecastEndDate']!r}; expected {expected_end!r}")

    for key in ("latRange", "lonRange"):
        if key in cell_dimension and not close_enough(float(cell_dimension[key]), GRID_STEP, tolerance=0.0):
            errors.append(f"defaultCellDimension {key}={cell_dimension[key]!r}; expected {GRID_STEP}")
    if "min" in depth_layer and not close_enough(float(depth_layer["min"]), 0.0, tolerance=0.0):
        errors.append(f"depthLayer min={depth_layer['min']!r}; expected 0")
    if "max" in depth_layer and not close_enough(float(depth_layer["max"]), 70.0, tolerance=0.0):
        errors.append(f"depthLayer max={depth_layer['max']!r}; expected 70")

    if bin_labels and all(label is not None for label in bin_labels):
        if any(float(bin_labels[i]) >= float(bin_labels[i + 1]) for i in range(len(bin_labels) - 1)):
            errors.append("Magnitude-bin labels are not strictly increasing")

    totals = [item.value for item in bin_sums]
    cumulative = [math.fsum(totals[i:]) for i in range(N_BINS)]
    rate_comparisons = []
    for threshold, actual, expected in zip(thresholds, cumulative, expected_rates):
        relative = abs(actual - expected) / abs(expected) if expected else 0.0
        rate_comparisons.append({
            "threshold_magnitude": threshold,
            "xml_cumulative_expected_count": actual,
            "run_log_cumulative_rate_events_per_year": expected,
            "relative_difference": relative,
            "within_0_5_percent": close_enough(actual, expected),
        })

    structure_errors = list(errors)
    rates_match = all(item["within_0_5_percent"] for item in rate_comparisons)
    return {
        "xml_path": str(xml_path),
        "xml_size_bytes": xml_path.stat().st_size,
        "xml_sha256": reader.sha256,
        "root_element": root_tag,
        "metadata": metadata,
        "default_cell_dimension": cell_dimension,
        "depth_layer": depth_layer,
        "depth_layer_count": depth_layer_seen,
        "cells_parsed": cell_count,
        "unique_spatial_cells": unique_cells,
        "magnitude_values_parsed": value_count,
        "magnitude_bins_per_cell": N_BINS,
        "magnitude_bin_labels_first_cell": bin_labels,
        "coordinate_convention": centre_mode,
        "first_5_cells": first_cells,
        "last_5_cells": last_cells,
        "zero_values": zero_count,
        "negative_values": negative_count,
        "nonfinite_values": nonfinite_count,
        "minimum_finite_value": None if math.isinf(min_value) else min_value,
        "maximum_finite_value": None if math.isinf(max_value) else max_value,
        "distinct_bin_expected_counts_over_forecast_period": totals,
        "cumulative_expected_counts_by_threshold": cumulative,
        "run_log_rate_comparisons": rate_comparisons,
        "structure_and_value_validation": "passed" if not structure_errors else "failed",
        "rate_comparison": "within_0.5_percent" if rates_match else "differs_by_more_than_0.5_percent",
        "overall_validation": "passed" if not structure_errors and rates_match else "review_required",
        "errors": structure_errors[:100],
        "notes": [
            "This is a streaming parser; processed <cell> elements are removed immediately to keep memory bounded.",
            "The expected 0.1-degree grid is checked with a bitset, so duplicate/missing spatial cells are detected using under 1 MB of memory.",
            "CSEP XML magnitude bins may be stored as child <bin m=...> elements or as 31 numeric values in cell text.",
            "The XML's cumulative sums are compared to the 2014-2015 run log. A mismatch is reported, not silently adjusted.",
            "A completed STEP #5 marker in the log does not replace this independent XML check.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path, help="Path to GEAR1.global.forecast.xml")
    parser.add_argument(
        "--run-summary",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "gear1_original_run_2014-2015.json",
    )
    parser.add_argument("--output", type=Path, help="Path for the small JSON validation report")
    args = parser.parse_args()

    result = validate(args.xml, args.run_summary)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["overall_validation"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
