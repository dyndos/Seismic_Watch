"""Kinematic features from the cited NNR-MORVEL56 Euler-pole table and PB2002 boundaries.

The velocities are geological long-term averages. The sign of the normal component
is relative to the digitised boundary-line orientation, not an automatic
convergence/divergence label; line orientation is not guaranteed to encode which
plate is on which side.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

EARTH_RADIUS_M = 6_371_000.0
MM_PER_M = 1_000.0
SECONDS_PER_YEAR = 365.25 * 24 * 3600
ROOT = Path(__file__).resolve().parents[1]


def load_morvel(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = path or ROOT / "research" / "data" / "morvel56_pacific_fixed.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    return {p["code"].upper(): p for p in payload["plates"]}


PB2002_TO_MORVEL = {"SO": "SM", "YA": "YZ"}


def _plate_omega(code: str, plates: dict[str, dict[str, Any]]) -> np.ndarray | None:
    normalized = PB2002_TO_MORVEL.get(str(code).upper(), str(code).upper())
    item = plates.get(normalized)
    if item is None:
        return None
    lat = math.radians(float(item["pole_latitude_deg"]))
    lon = math.radians(float(item["pole_longitude_deg"]))
    rate = math.radians(float(item["angular_rate_deg_per_Ma"])) / 1_000_000.0
    return rate * np.array([math.cos(lat) * math.cos(lon),
                            math.cos(lat) * math.sin(lon),
                            math.sin(lat)], dtype=float)


def plate_velocity_mm_yr(lat_deg: float, lon_deg: float, code: str,
                         plates: dict[str, dict[str, Any]]) -> np.ndarray | None:
    """Return east/north velocity in mm/yr for a plate in the Pacific-fixed frame."""
    omega = _plate_omega(code, plates)
    if omega is None:
        return None
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    radial = np.array([math.cos(lat) * math.cos(lon),
                       math.cos(lat) * math.sin(lon),
                       math.sin(lat)])
    xyz_m_yr = np.cross(omega, radial) * EARTH_RADIUS_M
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon),
                      -math.sin(lat) * math.sin(lon),
                      math.cos(lat)])
    return np.array([np.dot(xyz_m_yr, east), np.dot(xyz_m_yr, north)]) * MM_PER_M


def _norm_lon_delta(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def load_boundary_segments(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or ROOT / "public" / "data" / "plates.geojson"
    raw = json.loads(source.read_text(encoding="utf-8"))
    segments: list[dict[str, Any]] = []
    for feature in raw.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        kind = geom.get("type")
        coords = geom.get("coordinates") or []
        lines = coords if kind == "MultiLineString" else [coords]
        for line in lines:
            for p1, p2 in zip(line, line[1:]):
                if len(p1) < 2 or len(p2) < 2:
                    continue
                lon1, lat1 = float(p1[0]), float(p1[1])
                lon2, lat2 = float(p2[0]), float(p2[1])
                if lat1 == lat2 and _norm_lon_delta(lon2 - lon1) == 0:
                    continue
                segments.append({
                    "name": props.get("Name") or "Unknown",
                    "plate_a": str(props.get("PlateA") or "").upper(),
                    "plate_b": str(props.get("PlateB") or "").upper(),
                    "boundary_type": str(props.get("Type") or "").lower(),
                    "lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2,
                })
    if not segments:
        raise ValueError(f"No boundary line segments found in {source}")
    return segments


def _nearest_boundary(lat: float, lon: float,
                      segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    cos_lat = max(0.05, abs(math.cos(math.radians(lat))))
    best = None
    best_d2 = float("inf")
    for s in segments:
        midlat = (s["lat1"] + s["lat2"] + lat) / 3.0
        scale = max(0.05, abs(math.cos(math.radians(midlat))))
        ax = _norm_lon_delta(s["lon1"] - lon) * scale
        ay = s["lat1"] - lat
        bx = _norm_lon_delta(s["lon2"] - lon) * scale
        by = s["lat2"] - lat
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        t = 0.0 if denom == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / denom))
        px, py = ax + t * dx, ay + t * dy
        d2 = px * px + py * py
        if d2 < best_d2:
            best_d2 = d2
            # Azimuth clockwise from north; normal is defined by this line's direction.
            tangent_az = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
            best = dict(s, distance_km=math.sqrt(d2) * 111.195,
                        tangent_azimuth_deg=tangent_az)
    return best


def kinematic_features(lat: float, lon: float,
                       plates: dict[str, dict[str, Any]],
                       segments: list[dict[str, Any]],
                       max_boundary_distance_km: float = 500.0) -> dict[str, Any]:
    boundary = _nearest_boundary(lat, lon, segments)
    missing = {
        "relative_speed_mm_yr": None,
        "normal_velocity_mm_yr": None,
        "parallel_velocity_mm_yr": None,
        "motion_azimuth_deg": None,
        "boundary_distance_km": boundary["distance_km"] if boundary else None,
        "plate_a": boundary["plate_a"] if boundary else None,
        "plate_b": boundary["plate_b"] if boundary else None,
        "boundary_name": boundary["name"] if boundary else None,
        "boundary_tangent_azimuth_deg": boundary["tangent_azimuth_deg"] if boundary else None,
        "boundary_type": boundary["boundary_type"] if boundary else None,
    }
    if boundary is None or boundary["distance_km"] > max_boundary_distance_km:
        return missing
    va = plate_velocity_mm_yr(lat, lon, boundary["plate_a"], plates)
    vb = plate_velocity_mm_yr(lat, lon, boundary["plate_b"], plates)
    if va is None or vb is None:
        return missing
    # Both velocities share the Pacific-fixed reference; subtracting cancels it.
    rel = vb - va
    tangent = math.radians(boundary["tangent_azimuth_deg"])
    tangent_vec = np.array([math.sin(tangent), math.cos(tangent)])
    normal_vec = np.array([math.cos(tangent), -math.sin(tangent)])
    speed = float(np.linalg.norm(rel))
    azimuth = (math.degrees(math.atan2(rel[0], rel[1])) + 360.0) % 360.0
    return {
        **missing,
        "relative_speed_mm_yr": speed,
        "normal_velocity_mm_yr": float(np.dot(rel, normal_vec)),
        "parallel_velocity_mm_yr": float(np.dot(rel, tangent_vec)),
        "motion_azimuth_deg": azimuth,
    }


def equal_area_grid(cell_size_km: float = 500.0) -> list[dict[str, Any]]:
    """Global approximately square grid in EPSG:6933 (equal-area projection)."""
    from pyproj import Transformer

    forward = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    inverse = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)
    # EPSG:6933 bounds for the valid geographic area.
    x_min, x_max = -17_367_530.45, 17_367_530.45
    y_min, y_max = -7_324_184.56, 7_324_184.56
    step = cell_size_km * 1000.0
    cells: list[dict[str, Any]] = []
    iy = 0
    y = y_min + step / 2
    while y < y_max:
        ix = 0
        x = x_min + step / 2
        while x < x_max:
            lon, lat = inverse.transform(x, y)
            if math.isfinite(lat) and -85.0 <= lat <= 85.0:
                cells.append({
                    "cell_id": f"ea{int(cell_size_km)}_{ix}_{iy}",
                    "x_m": x, "y_m": y, "longitude": float(lon),
                    "latitude": float(lat), "area_km2": cell_size_km ** 2,
                })
            ix += 1
            x += step
        iy += 1
        y += step
    return cells


def annotate_grid(cells: list[dict[str, Any]], plates: dict[str, dict[str, Any]],
                  segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for cell in cells:
        out.append({**cell, **kinematic_features(
            cell["latitude"], cell["longitude"], plates, segments
        )})
    return out
