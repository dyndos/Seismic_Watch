#!/usr/bin/env python3
"""Stream-validate an original GEAR1 CSEP XML forecast without loading it into RAM."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

NAMESPACE = "http://www.scec.org/xml-ns/csep/forecast/1.1"
EXPECTED_ROWS_DEFAULT = 1800
EXPECTED_COLUMNS_DEFAULT = 3600
EXPECTED_BIN_COUNT = 31
GRID_STEP = 0.1
LON_MIN = -179.95
LAT_MIN = -89.95


class HashingReader:
    """File wrapper that hashes bytes as ElementTree reads them."""
    def __init__(self, path: Path) -> None:
        self._stream = path.open("rb")
        self._hash = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self._hash.update(data)
        return data

    def close(self) -> None:
        self._stream.close()

    @property
    def hexdigest(self) -> str:
        return self._hash.hexdigest()


class KahanSum:
    def __init__(self) -> None:
        self.total = 0.0
        self.compensation = 0.0

    def add(self, value: float) -> None:
        y = value - self.compensation
        t = self.total + y
        self.compensation = (t - self.total) - y
        self.total = t


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_expected(path: Path) -> tuple[list[float], list[float], str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    columns = data["step_3_rates"]["columns"]
    rows = data["step_3_rates"]["rows"]
    mag_i = columns.index("threshold_magnitude")
    rate_i = columns.index("hybrid_rate_above_threshold_events_per_year")
    thresholds = [float(row[mag_i]) for row in rows]
    rates = [float(row[rate_i]) for row in rows]
    start = data["configuration"]["forecast_start_utc"]
    end = data["configuration"]["forecast_end_utc"]
    return thresholds, rates, start, end


def close_enough(actual: float, expected: float, rel_tol: float = 0.005, abs_tol: float = 0.0005) -> bool:
    return abs(actual - expected) <= max(abs_tol, abs(expected) * rel_tol)


def validate(
    xml_path: Path,
    expected_json: Path,
    rows_expected: int = EXPECTED_ROWS_DEFAULT,
    columns_expected: int = EXPECTED_COLUMNS_DEFAULT,
) -> dict[str, object]:
    thresholds, expected_rates, expected_start, expected_end = load_expected(expected_json)
    if len(thresholds) != EXPECTED_BIN_COUNT or len(expected_rates) != EXPECTED_BIN_COUNT:
        raise ValueError(f"Expected summary must have {EXPECTED_BIN_COUNT} magnitude thresholds")

    metadata: dict[str, str] = {}
    depth_attrs: dict[str, str] = {}
    cell_dimension_attrs: dict[str, str] = {}
    sums = [KahanSum() for _ in range(EXPECTED_BIN_COUNT)]
    cell_count = 0
    value_count = 0
    zero_count = 0
    first_cell: dict[str, float] | None = None
    last_cell: dict[str, float] | None = None
    stack: list[ET.Element] = []
    reader = HashingReader(xml_path)

    try:
        for event, elem in ET.iterparse(reader, events=("start", "end")):
            name = local_name(elem.tag)
            if event == "start":
                stack.append(elem)
                if len(stack) == 1:
                    if name != "CSEPForecast" or elem.tag != f"{{{NAMESPACE}}}CSEPForecast":
                        raise ValueError(f"Unexpected XML root/namespace: {elem.tag!r}")
                elif name == "cellDimension":
                    cell_dimension_attrs = dict(elem.attrib)
                elif name == "depthLayer":
                    depth_attrs = dict(elem.attrib)
                continue

            if name == "cell":
                if len(stack) < 2:
                    raise ValueError("Cell element has no forecast container")
                if cell_count >= rows_expected * columns_expected:
                    raise ValueError("XML contains more cells than the configured global grid")
                try:
                    lon = float(elem.attrib["lon"])
                    lat = float(elem.attrib["lat"])
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"Cell {cell_count + 1} has invalid lon/lat attributes") from exc

                col = cell_count // rows_expected
                row = cell_count % rows_expected
                expected_lon = LON_MIN + col * GRID_STEP
                expected_lat = LAT_MIN + row * GRID_STEP
                if not close_enough(lon, expected_lon, rel_tol=0.0, abs_tol=0.0051):
                    raise ValueError(f"Cell {cell_count + 1}: longitude {lon} != expected {expected_lon}")
                if not close_enough(lat, expected_lat, rel_tol=0.0, abs_tol=0.0051):
                    raise ValueError(f"Cell {cell_count + 1}: latitude {lat} != expected {expected_lat}")

                if len(elem):
                    raise ValueError(f"Cell {cell_count + 1} contains child elements; expected numeric text values")
                fields = (elem.text or "").split()
                if len(fields) != EXPECTED_BIN_COUNT:
                    raise ValueError(f"Cell {cell_count + 1} has {len(fields)} values, expected {EXPECTED_BIN_COUNT}")
                for index, field in enumerate(fields):
                    try:
                        value = float(field)
                    except ValueError as exc:
                        raise ValueError(f"Invalid numeric forecast value in cell {cell_count + 1}: {field!r}") from exc
                    if not math.isfinite(value) or value < 0.0:
                        raise ValueError(f"Negative/non-finite forecast value in cell {cell_count + 1}: {field!r}")
                    sums[index].add(value)
                    if value == 0.0:
                        zero_count += 1
                value_count += len(fields)
                cell = {"lon": lon, "lat": lat}
                if first_cell is None:
                    first_cell = cell
                last_cell = cell
                cell_count += 1
                # Remove processed cells from parent to keep memory bounded.
                stack[-2].remove(elem)
                elem.clear()

            elif name in {
                "modelName", "version", "author", "authorURI", "issueDate",
                "forecastStartDate", "forecastEndDate", "forecastDuration",
                "magnitudeBinDimension", "magnitudeMinValue", "lastMagBinOpen",
            }:
                metadata[name] = (elem.text or "").strip()

            if stack and stack[-1] is elem:
                stack.pop()

    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc
    finally:
        reader.close()

    expected_cells = rows_expected * columns_expected
    if cell_count != expected_cells:
        raise ValueError(f"XML has {cell_count:,} cells; expected {expected_cells:,}")
    if value_count != expected_cells * EXPECTED_BIN_COUNT:
        raise ValueError(
            f"XML has {value_count:,} forecast values; expected {expected_cells * EXPECTED_BIN_COUNT:,}"
        )

    required_meta = {
        "modelName": "GEAR1",
        "version": "1.0",
        "forecastStartDate": expected_start,
        "forecastEndDate": expected_end,
        "magnitudeBinDimension": "0.1",
        "magnitudeMinValue": "5.95",
        "lastMagBinOpen": "1",
    }
    for key, expected in required_meta.items():
        actual = metadata.get(key)
        if actual != expected:
            raise ValueError(f"Metadata {key}={actual!r}; expected {expected!r}")
    duration = float(metadata.get("forecastDuration", "nan"))
    if not close_enough(duration, 365.25, rel_tol=0.0, abs_tol=0.01):
        raise ValueError(f"Unexpected forecastDuration: {duration}")
    if cell_dimension_attrs != {"latRange": "0.1", "lonRange": "0.1"}:
        raise ValueError(f"Unexpected cellDimension attributes: {cell_dimension_attrs}")
    if depth_attrs != {"min": "0", "max": "70"}:
        raise ValueError(f"Unexpected depthLayer attributes: {depth_attrs}")

    bin_totals = [item.total for item in sums]
    cumulative_totals = [math.fsum(bin_totals[i:]) for i in range(EXPECTED_BIN_COUNT)]
    comparisons = []
    for threshold, actual, expected in zip(thresholds, cumulative_totals, expected_rates):
        relative_error = abs(actual - expected) / expected if expected else 0.0
        comparisons.append({
            "threshold_magnitude": threshold,
            "xml_cumulative_events": actual,
            "log_cumulative_events_per_year": expected,
            "relative_difference": relative_error,
            "within_0_5_percent": close_enough(actual, expected),
        })
        if not close_enough(actual, expected):
            raise ValueError(
                f"XML cumulative total above M{threshold:.2f} ({actual:.6f}) differs from run log "
                f"({expected:.6f}) by {relative_error:.3%}; tolerance is 0.5%"
            )

    return {
        "validation": "passed",
        "xml_file": str(xml_path),
        "xml_size_bytes": xml_path.stat().st_size,
        "xml_sha256": reader.hexdigest,
        "root": f"{{{NAMESPACE}}}CSEPForecast",
        "metadata": metadata,
        "depth_layer": depth_attrs,
        "cell_dimension": cell_dimension_attrs,
        "cells": cell_count,
        "magnitude_bins_per_cell": EXPECTED_BIN_COUNT,
        "numeric_forecast_values": value_count,
        "zero_values": zero_count,
        "first_cell": first_cell,
        "last_cell": last_cell,
        "xml_global_sum_events_over_forecast_duration": cumulative_totals[0],
        "expected_global_sum_from_run_log_events_per_year": expected_rates[0],
        "cumulative_rate_comparisons": comparisons,
        "magnitude_bin_sums_events_over_forecast_duration": bin_totals,
        "notes": [
            "The XML contains expected event counts per cell and magnitude bin over the configured one-year forecast duration, not rates per second.",
            "Cumulative comparisons sum each bin and all higher-magnitude bins; tolerance allows for per-cell ES10.3 text rounding.",
            "The validation uses a streaming parser and removes processed cell elements to keep memory bounded.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path)
    parser.add_argument(
        "--run-summary",
        type=Path,
        default=Path(__file__).resolve().parent / "results" / "gear1_original_run_2014-2015.json",
    )
    parser.add_argument("--output", type=Path, help="Write validation report to this JSON path")
    parser.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS_DEFAULT, help=argparse.SUPPRESS)
    parser.add_argument("--expected-columns", type=int, default=EXPECTED_COLUMNS_DEFAULT, help=argparse.SUPPRESS)
    args = parser.parse_args()

    result = validate(args.xml, args.run_summary, args.expected_rows, args.expected_columns)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
