"""Global CMT NDK ingestion and as-of event matching.

The NDK Q-/S- timestamp records the analysis time, not a guaranteed public
release timestamp. It is retained as a conservative availability proxy.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import math
import re
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

GCMT_NDK_URL = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/jan76_dec25.ndk.gz"


def _to_ms(value: datetime) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _parse_origin(date_text: str, time_text: str) -> int:
    value = f"{date_text} {time_text}"
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return _to_ms(datetime.strptime(value, fmt))
        except ValueError:
            continue
    raise ValueError(f"Unsupported NDK origin timestamp: {value}")


def _parse_analysis_time(line: str) -> tuple[int | None, str | None]:
    match = re.search(r"\b([QS]-\d{14})\b", line)
    if not match:
        return None, None
    stamp = match.group(1)
    return _to_ms(datetime.strptime(stamp[2:], "%Y%m%d%H%M%S")), stamp


def parse_ndk_catalog(text: str) -> list[dict[str, Any]]:
    """Parse the official five-line, 80-column Global CMT NDK format."""
    lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]
    if len(lines) % 5:
        raise ValueError(f"NDK record count is not divisible by five: {len(lines)}")

    parsed: list[dict[str, Any]] = []
    for offset in range(0, len(lines), 5):
        line1, line2, line3, line4, line5 = lines[offset:offset + 5]
        try:
            origin = line1.split()
            centroid = line3.split()
            if len(origin) < 8 or len(centroid) < 10:
                continue
            if centroid[0].rstrip(":").upper() != "CENTROID":
                continue

            origin_ms = _parse_origin(origin[1], origin[2])
            analysis_ms, analysis_stamp = _parse_analysis_time(line3)
            if analysis_ms is None:
                continue

            # NDK columns are one-based: exponent [1:2], scalar moment [50:56],
            # and both nodal planes [58:80].
            exponent = int(line4[:2].strip())
            scalar_field = line5[49:56].strip()
            planes = [float(v) for v in line5[57:80].split()]
            if not scalar_field or len(planes) != 6:
                continue
            scalar_moment_dyne_cm = float(scalar_field) * (10.0 ** exponent)
            if not math.isfinite(scalar_moment_dyne_cm) or scalar_moment_dyne_cm <= 0:
                continue
            strike1, dip1, rake1, strike2, dip2, rake2 = planes
            if not (
                0 <= strike1 < 360 and 0 < dip1 <= 90 and abs(rake1) <= 180
                and 0 <= strike2 < 360 and 0 < dip2 <= 90 and abs(rake2) <= 180
            ):
                continue

            parsed.append({
                "event_name": line2[:16].strip(),
                "origin_time_ms": origin_ms,
                "origin_latitude": float(origin[3]),
                "origin_longitude": float(origin[4]),
                "origin_depth_km": float(origin[5]),
                "centroid_latitude": float(centroid[3]),
                "centroid_longitude": float(centroid[5]),
                "centroid_depth_km": float(centroid[7]),
                "solution_update_ms": analysis_ms,
                "solution_stamp": analysis_stamp,
                "scalar_moment_nm": scalar_moment_dyne_cm * 1e-7,
                "magnitude_mw": (2.0 / 3.0) * (
                    math.log10(scalar_moment_dyne_cm) - 16.1
                ),
                "strike": strike1, "dip": dip1, "rake": rake1,
                "strike2": strike2, "dip2": dip2, "rake2": rake2,
                "catalog": "Global CMT",
            })
        except (ValueError, IndexError, OverflowError):
            continue
    return parsed


def download_gcmt_catalog(destination: Path | str) -> tuple[list[dict[str, Any]], str]:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        GCMT_NDK_URL, timeout=(30, 300),
        headers={"User-Agent": "Seismic-Watch-research/0.2"},
    )
    response.raise_for_status()
    compressed = response.content
    raw = gzip.decompress(compressed)
    path.write_bytes(compressed)
    digest = hashlib.sha256(compressed).hexdigest()
    events = parse_ndk_catalog(raw.decode("ascii", errors="replace"))
    if not events:
        raise RuntimeError("Global CMT NDK archive contained no parseable timestamped solutions")
    return events, digest


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def match_gcmt_solutions(
    catalog: list[dict[str, Any]],
    gcmt_events: list[dict[str, Any]],
    max_time_difference_seconds: float = 900.0,
    max_distance_km: float = 250.0,
) -> dict[str, dict[str, Any]]:
    """Match timestamped GCMT solutions to ComCat events; keep earliest solution.

    Earliest Q-/S- solution time is used so the forecast cutoff can be placed
    after a defensible source-mechanism analysis time without using later CMT
    revisions that may have become available only after the historical cutoff.
    """
    indexed = []
    for feature in catalog:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2 or props.get("time") is None:
            continue
        indexed.append((
            int(props["time"]), str(feature.get("id") or ""),
            float(coords[1]), float(coords[0]),
        ))
    indexed.sort(key=lambda value: value[0])
    times = [value[0] for value in indexed]
    candidate_matches: dict[str, list[tuple[float, int, dict[str, Any]]]] = {}
    window_ms = int(max_time_difference_seconds * 1000)

    for solution in gcmt_events:
        origin_ms = solution.get("origin_time_ms")
        update_ms = solution.get("solution_update_ms")
        if origin_ms is None or update_ms is None or int(update_ms) < int(origin_ms):
            continue
        left = bisect_left(times, int(origin_ms) - window_ms)
        right = bisect_left(times, int(origin_ms) + window_ms + 1)
        best: tuple[float, str] | None = None
        for idx in range(left, right):
            event_time, event_id, lat, lon = indexed[idx]
            time_delta = abs(event_time - int(origin_ms)) / 1000.0
            distance = _distance_km(
                lat, lon, float(solution["origin_latitude"]),
                float(solution["origin_longitude"]),
            )
            if distance > max_distance_km:
                continue
            score = time_delta / max_time_difference_seconds + distance / max_distance_km
            if best is None or score < best[0]:
                best = (score, event_id)
        if best and best[1]:
            candidate_matches.setdefault(best[1], []).append(
                (best[0], int(update_ms), solution)
            )

    output: dict[str, dict[str, Any]] = {}
    for event_id, candidates in candidate_matches.items():
        # Deterministic: closest origin/location match, then earliest analysis.
        candidates.sort(key=lambda item: (item[0], item[1]))
        output[event_id] = candidates[0][2]
    return output


def attach_gcmt_solution(
    feature: dict[str, Any],
    solution: dict[str, Any],
    as_of_ms: int,
) -> dict[str, Any]:
    """Attach only time-valid ComCat products plus the timestamped GCMT solution."""
    if int(solution["solution_update_ms"]) > int(as_of_ms):
        raise ValueError("GCMT solution timestamp is later than the forecast cutoff")
    merged = copy.deepcopy(feature)
    props = merged.setdefault("properties", {})
    products = props.setdefault("products", {})
    for product_type, product_list in list(products.items()):
        valid = [
            item for item in (product_list or [])
            if item.get("updateTime") is not None
            and int(item["updateTime"]) <= int(as_of_ms)
        ]
        if valid:
            products[product_type] = valid
        else:
            del products[product_type]

    gcmt_product = {
        "source": "gcmt",
        "updateTime": int(solution["solution_update_ms"]),
        "properties": {
            "nodal-plane-1-strike": str(solution["strike"]),
            "nodal-plane-1-dip": str(solution["dip"]),
            "nodal-plane-1-rake": str(solution["rake"]),
            "nodal-plane-2-strike": str(solution["strike2"]),
            "nodal-plane-2-dip": str(solution["dip2"]),
            "nodal-plane-2-rake": str(solution["rake2"]),
            "scalar-moment": str(solution["scalar_moment_nm"]),
        },
    }
    products.setdefault("moment-tensor", []).append(gcmt_product)
    props["products"] = products
    props["gcmt_event_name"] = solution.get("event_name")
    props["gcmt_analysis_timestamp"] = solution.get("solution_stamp")
    return merged
