#!/usr/bin/env python3
"""Stream-audit the Kagan-Jackson parent grid used by the published GEAR1 source."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

EXPECTED_SHA256 = "a8b6f73b8ae2a7f98868972d8b49e05055e4d1efe8f8264385ec0b07128663bf"
HEADER_LINES = 16
N_ROWS = 1800
N_COLUMNS = 3600
LAT_MAX = 89.95
LON_MIN = -179.95
D_LAT = 0.1
D_LON = 0.1
EARTH_RADIUS_M = 6_371_000.0
PI = 3.1415927
RADIANS_PER_DEGREE = 0.0174533
SECONDS_PER_DAY = 86_400.0
SECONDS_PER_YEAR = 365.25 * SECONDS_PER_DAY


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_cell_area_m2(row_index: int) -> float:
    """Return spherical cell area using GEAR1 Integrate_DP_Grid constants/formula."""
    top_lat = min(LAT_MAX + 0.5 * D_LAT - row_index * D_LAT, 90.0)
    bottom_lat = max(top_lat - D_LAT, -90.0)
    strip_area_sr = (
        2.0 * PI * (1.0 - math.cos((90.0 - bottom_lat) * RADIANS_PER_DEGREE))
        - 2.0 * PI * (1.0 - math.cos((90.0 - top_lat) * RADIANS_PER_DEGREE))
    )
    return strip_area_sr * EARTH_RADIUS_M**2 * D_LON / 360.0


def audit_grid(path: Path, expected_sha256: str | None = EXPECTED_SHA256) -> dict[str, object]:
    actual_sha256 = sha256_file(path)
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}")

    record_count = 0
    min_density = math.inf
    max_density = -math.inf
    value_sum = 0.0
    total_integral_per_second = 0.0
    total_area_m2 = 0.0

    with path.open("r", encoding="ascii", errors="strict") as stream:
        for _ in range(HEADER_LINES):
            if stream.readline() == "":
                raise ValueError("Grid ended before its 16-line header was complete")

        for row_index in range(N_ROWS):
            row_values: list[float] = []
            expected_lat = LAT_MAX - row_index * D_LAT
            for column_index in range(N_COLUMNS):
                line = stream.readline()
                if not line:
                    raise ValueError(f"Unexpected EOF at row {row_index + 1}, column {column_index + 1}")
                fields = line.split()
                if len(fields) < 3:
                    raise ValueError(f"Expected at least 3 columns at record {record_count + 1}: {line!r}")
                longitude, latitude, density = map(float, fields[:3])
                expected_lon = LON_MIN + column_index * D_LON
                if abs(longitude - expected_lon) > 1e-5:
                    raise ValueError(f"Longitude mismatch at record {record_count + 1}: {longitude} != {expected_lon}")
                if abs(latitude - expected_lat) > 1e-5:
                    raise ValueError(f"Latitude mismatch at record {record_count + 1}: {latitude} != {expected_lat}")
                if not math.isfinite(density) or density <= 0.0:
                    raise ValueError(f"Non-finite or non-positive density at record {record_count + 1}")
                row_values.append(density)
                min_density = min(min_density, density)
                max_density = max(max_density, density)
                value_sum += density
                record_count += 1

            row_area = row_cell_area_m2(row_index)
            total_integral_per_second += math.fsum(row_values) * row_area / (1.0e6 * SECONDS_PER_DAY)
            total_area_m2 += row_area * N_COLUMNS

        if stream.read().strip():
            raise ValueError("Unexpected extra non-whitespace content after the expected global grid")

    expected_count = N_ROWS * N_COLUMNS
    if record_count != expected_count:
        raise ValueError(f"Expected {expected_count} records, parsed {record_count}")

    return {
        "dataset": "Kagan-Jackson smoothed seismicity parent grid supplied with Bird GEAR1 archive",
        "source_file": path.name,
        "sha256": actual_sha256,
        "header_lines": HEADER_LINES,
        "rows": N_ROWS,
        "columns": N_COLUMNS,
        "records": record_count,
        "grid_spacing_degrees": {"longitude": D_LON, "latitude": D_LAT},
        "magnitude_label_in_source_header": "M>5.8",
        "input_units": "expected earthquakes / day / km^2",
        "density_min": min_density,
        "density_max": max_density,
        "density_mean": value_sum / record_count,
        "integrated_global_rate_events_per_year": total_integral_per_second * SECONDS_PER_YEAR,
        "integrated_grid_area_m2": total_area_m2,
        "method": "Spherical cell-area integral using the same constants/formula as GEAR1 Integrate_DP_Grid; density converted from per day per km^2 to per second per m^2.",
        "scope_limit": "This is the integral of the seismicity parent input grid labelled M>5.8. It is not the final GEAR1 hybrid forecast and is not an independent forecast skill test."
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grid", type=Path, help="Path to GL_HAZTBLT_M5_B2_2013.TMP")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--skip-sha256-check", action="store_true", help="Skip the archive-specific SHA-256 check")
    args = parser.parse_args()

    result = audit_grid(args.grid, expected_sha256=None if args.skip_sha256_check else EXPECTED_SHA256)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
