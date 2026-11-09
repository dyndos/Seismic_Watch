"""Normalize ISC-GEM and ComCat into a versioned global Mw catalogue audit."""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import requests

COMCAT_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MW_TYPES = {"mw", "mww", "mwc", "mwb", "mwr"}
THRESHOLDS = (5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0)
MAX_SHALLOW_KM = 70.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def number(value: Any) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def read_isc_csv(path: Path, supplementary: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if line.strip()]
    header_at = None
    for i, line in enumerate(lines):
        candidate = line.lstrip("#").strip()
        try:
            fields = [x.strip().lower() for x in next(csv.reader([candidate], skipinitialspace=True))]
        except (csv.Error, StopIteration):
            continue
        if len(fields) >= 14 and fields[0] == "date" and "lat" in fields and "lon" in fields and "mw" in fields:
            header_at = i
            break
    start = header_at + 1 if header_at is not None else 0
    # ISC-GEM CSV uses repeated q/unc labels; their positions are defined by
    # the official fixed schema, so parse the known columns by position.
    records, skipped = [], 0
    for line in lines[start:]:
        if line.lstrip().startswith("#"):
            continue
        try:
            row = [x.strip() for x in next(csv.reader([line], skipinitialspace=True))]
            if len(row) < 14:
                skipped += 1
                continue
            origin = parse_time(row[0])
            lat, lon, depth = number(row[1]), number(row[2]), number(row[7])
            mw = number(row[10])
            if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                skipped += 1
                continue
            event_id = row[-1] if row else ""
            record = {
                "event_id": f"iscgem:{event_id or hashlib.sha1(line.encode()).hexdigest()[:16]}",
                "source": "ISC-GEM-supplementary" if supplementary else "ISC-GEM-main",
                "origin_time": origin.isoformat().replace("+00:00", "Z"),
                "latitude": lat, "longitude": lon, "depth_km": depth,
                "mw": None if supplementary else mw,
                "mw_unc": number(row[11]),
                "mw_quality": row[12] or None,
                "mw_source": row[13] or None,
                "magnitude_type": "Mw",
                "mw_eligible": bool(mw is not None and not supplementary),
                "source_record_id": event_id,
            }
            records.append(record)
        except (ValueError, IndexError, csv.Error):
            skipped += 1
    return records, {
        "path": str(path), "sha256": sha256_file(path),
        "header_found": header_at is not None,
        "parsed_records": len(records), "skipped_records": skipped,
        "role": "supplement_only_not_used_for_rate_fit" if supplementary else "main_catalogue",
    }


def parse_comcat(path: Path, min_mag: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("Expected a ComCat GeoJSON FeatureCollection")
    result, excluded, skipped = [], Counter(), 0
    for feature in features:
        props, geom = feature.get("properties") or {}, feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        mag, typ = number(props.get("mag")), str(props.get("magType") or "").lower()
        if len(coords) < 3 or mag is None or mag < min_mag or str(props.get("type") or "earthquake") != "earthquake":
            skipped += 1
            continue
        valid = typ in MW_TYPES
        if not valid:
            excluded[typ or "unknown"] += 1
        try:
            origin = datetime.fromtimestamp(float(props["time"]) / 1000, tz=timezone.utc)
            lat, lon, depth = float(coords[1]), float(coords[0]), number(coords[2])
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("coordinates outside geographic range")
        except (KeyError, TypeError, ValueError, OverflowError):
            skipped += 1
            continue
        event_id = str(feature.get("id") or props.get("code") or "")
        result.append({
            "event_id": f"comcat:{event_id}", "source": "USGS-ComCat",
            "origin_time": origin.isoformat().replace("+00:00", "Z"),
            "latitude": lat, "longitude": lon, "depth_km": depth,
            "mw": mag if valid else None, "mw_unc": None,
            "mw_quality": props.get("reviewstatus"), "mw_source": props.get("net"),
            "magnitude_type": typ, "mw_eligible": valid, "source_record_id": event_id,
        })
    return result, {
        "path": str(path), "sha256": sha256_file(path),
        "feature_count": len(features), "parsed_records": len(result),
        "skipped_records": skipped, "excluded_non_mw_types": dict(excluded),
    }


def _fetch_window(session: requests.Session, start: datetime, end: datetime,
                  min_mag: float, depth: int = 8) -> list[dict[str, Any]]:
    params = {
        "format": "geojson", "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": f"{min_mag:.1f}", "orderby": "time-asc", "limit": "20000",
    }
    response = session.get(COMCAT_URL, params=params, timeout=120,
                           headers={"User-Agent": "Seismic-Watch-research/0.3"})
    response.raise_for_status()
    features = response.json().get("features") or []
    if len(features) < 20000:
        return features
    if depth <= 0 or end - start <= timedelta(days=1):
        raise RuntimeError(f"ComCat limit reached for {start.isoformat()} to {end.isoformat()}")
    midpoint_second = int((start + (end - start) / 2).timestamp())\n    mid = datetime.fromtimestamp(midpoint_second, tz=timezone.utc)\n    if mid < start or mid >= end:\n        raise RuntimeError(f"Unable to split dense ComCat interval {start.isoformat()}..{end.isoformat()}")\n    return (_fetch_window(session, start, mid, min_mag, depth - 1)\n            + _fetch_window(session, mid + timedelta(seconds=1), end, min_mag, depth - 1))\n

def fetch_comcat(start_date: str, end_date: str, min_mag: float) -> tuple[Path, dict[str, Any]]:
    start = parse_time(start_date + "T00:00:00Z")
    end = parse_time(end_date + "T23:59:59Z")
    session, features = requests.Session(), []
    cursor = start
    while cursor <= end:
        year_end = datetime(cursor.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        chunk_end = min(end, year_end)
        if chunk_end < cursor:\n            raise RuntimeError(f"Invalid ComCat year chunk: start {cursor.isoformat()} exceeds end {chunk_end.isoformat()}")\n        features.extend(_fetch_window(session, cursor, chunk_end, min_mag))\n        # FDSN timestamps are queried at one-second precision and endtime is inclusive.\n        cursor = chunk_end + timedelta(seconds=1)\n    unique = {str(x.get("id")): x for x in features if x.get("id")}
    payload = {"type": "FeatureCollection", "metadata": {
        "source": "USGS ComCat", "start": start.isoformat(), "end": end.isoformat(),
        "min_magnitude": min_mag, "retrieved_utc": datetime.now(timezone.utc).isoformat()
    }, "features": list(unique.values())}
    return payload, {"source": "USGS ComCat FDSN Event Web Service", "url": COMCAT_URL,
                     "raw_count": len(features), "unique_count": len(unique),
                     "metadata": payload["metadata"]}


def _shallow(row: dict[str, Any]) -> bool:
    depth = row.get("depth_km")
    return depth is not None and 0 <= float(depth) <= MAX_SHALLOW_KM


def _year(row: dict[str, Any]) -> int:
    return int(row["origin_time"][:4])


def audit_counts(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    years = sorted({_year(x) for x in records})
    annual = []
    if years:
        for year in range(years[0], years[-1] + 1):
            subset = [x for x in records if _year(x) == year and x["mw_eligible"] and _shallow(x)]
            row = {"year": year, "shallow_mw_events": len(subset)}
            for threshold in THRESHOLDS:
                row[f"mw_ge_{threshold:.1f}"] = sum(float(x["mw"]) >= threshold for x in subset)
            annual.append(row)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in annual:
        grouped[(row["year"] // 10) * 10].append(row)
    decadal = []
    for decade, values in sorted(grouped.items()):
        out = {"period": f"{values[0]['year']}-{values[-1]['year']}", "years": len(values)}
        for threshold in THRESHOLDS:
            key = f"mw_ge_{threshold:.1f}"
            out[key] = round(sum(x[key] for x in values) / len(values), 3)
        decadal.append(out)
    return annual, decadal


def spatial_counts(records: list[dict[str, Any]], cell_deg: float = 5.0) -> list[dict[str, Any]]:
    counts: dict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    for x in records:
        if not x["mw_eligible"] or not _shallow(x):
            continue
        i = min(int((x["latitude"] + 90) // cell_deg), int(180 / cell_deg) - 1)
        j = min(int((x["longitude"] + 180) // cell_deg), int(360 / cell_deg) - 1)
        counts[(i, j)]["events"] += 1
        for t in THRESHOLDS:
            if float(x["mw"]) >= t:
                counts[(i, j)][f"mw_ge_{t:.1f}"] += 1
    return [{
        "lat_min": -90 + i * cell_deg, "lat_max": -90 + (i + 1) * cell_deg,
        "lon_min": -180 + j * cell_deg, "lon_max": -180 + (j + 1) * cell_deg,
        **dict(c),
    } for (i, j), c in sorted(counts.items())]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(isc_main: Path, output: Path, isc_supplement: Path | None = None,
        comcat_geojson: Path | None = None, fetch: bool = False,
        comcat_start: str = "2023-01-01", min_mag: float = 5.0) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    records, isc_meta = read_isc_csv(isc_main)
    if not records:
        raise RuntimeError("No ISC-GEM main catalogue rows parsed; check that this is the official CSV")
    supplement, supplement_meta = ([], None)
    if isc_supplement:
        supplement, supplement_meta = read_isc_csv(isc_supplement, supplementary=True)
    comcat_rows, comcat_meta, comcat_snapshot = [], None, None
    latest_isc = max(x["origin_time"][:10] for x in records)
    if fetch:
        start = max(comcat_start, (parse_time(latest_isc + "T00:00:00Z").date() + timedelta(days=1)).isoformat())
        end = datetime.now(timezone.utc).date().isoformat()
        if start <= end:
            payload, comcat_meta = fetch_comcat(start, end, min_mag)
            comcat_snapshot = output / "comcat_extension.geojson"
            comcat_snapshot.write_text(json.dumps(payload), encoding="utf-8")
            comcat_rows, parse_meta = parse_comcat(comcat_snapshot, min_mag)
            comcat_meta.update(parse_meta)
    elif comcat_geojson:
        comcat_rows, comcat_meta = parse_comcat(comcat_geojson, min_mag)
        comcat_rows = [x for x in comcat_rows if x["origin_time"][:10] > latest_isc]
    rows = sorted(records + comcat_rows, key=lambda x: (x["origin_time"], x["event_id"]))
    ids = [x["event_id"] for x in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate normalized event IDs detected")
    annual, decadal = audit_counts(rows)
    spatial = spatial_counts(rows)
    write_csv(output / "global_catalogue_normalized.csv", rows)
    write_csv(output / "annual_global_counts.csv", annual)
    write_csv(output / "spatial_counts_5deg.csv", spatial)
    mw_count = sum(bool(x["mw_eligible"]) for x in rows)
    manifest = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "isc_gem_release": "Version 13.0, 2026-10-21",
        "isc_main": isc_meta, "isc_supplement": supplement_meta,
        "comcat_extension": comcat_meta,
        "comcat_snapshot_sha256": sha256_file(comcat_snapshot) if comcat_snapshot else None,
        "counts": {"isc_main": len(records), "comcat_extension": len(comcat_rows),
                   "supplementary_uncertain": len(supplement), "combined": len(rows),
                   "mw_eligible": mw_count},
        "year_range": [min(_year(x) for x in rows), max(_year(x) for x in rows)],
        "thresholds": list(THRESHOLDS), "shallow_depth_km": [0, MAX_SHALLOW_KM],
        "rules": {
            "supplementary_catalogue": "separate only; excluded from main rate fit",
            "ComCat": "only events after the latest ISC-GEM main-catalogue date; only Mw/mww/mwc/mwb/mwr count as Mw",
            "unknown_depth": "not assumed shallow",
            "missing_magnitude": "not imputed",
        },
        "limitations": [
            "ISC-GEM v13 was released in 2026 and is not information available at earlier forecast cutoffs.",
            "Annual global counts are diagnostics, not a formal spatially varying magnitude-of-completeness estimate.",
            "A global count curve does not establish local completeness.",
            "Non-Mw ComCat magnitudes are retained with mw_eligible=false and not converted.",
            "This pipeline prepares catalogue inputs; it does not yet generate calibrated earthquake probabilities.",
        ],
        "files": ["global_catalogue_normalized.csv", "annual_global_counts.csv",
                  "spatial_counts_5deg.csv", "catalog_audit.md"],
    }
    (output / "catalog_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    lines = [
        "# Global earthquake catalogue audit", "",
        f"ISC-GEM main records: {len(records):,}",
        f"ComCat extension records: {len(comcat_rows):,}",
        f"Supplementary uncertain records: {len(supplement):,}",
        f"Combined records: {len(rows):,}; Mw-eligible: {mw_count:,}",
        f"Period: {manifest['year_range'][0]}–{manifest['year_range'][1]}", "",
        "Counts below are shallow (depth ≤70 km) and use only Mw-eligible records.",
        "They are completeness diagnostics, not a formal completeness estimate.", "",
        "| Period | " + " | ".join(f"Mw≥{x:.1f}" for x in THRESHOLDS) + " |",
        "|---|" + "---:|" * len(THRESHOLDS),
    ]
    for x in decadal:
        lines.append("| " + x["period"] + " | " + " | ".join(str(x[f"mw_ge_{t:.1f}"]) for t in THRESHOLDS) + " |")
    lines += [
        "", "## Interpretation safeguards", "",
        "- Do not infer one global completeness magnitude from global counts alone.",
        "- Compare counts by region and time because network density and catalog practices vary.",
        "- Keep the ISC-GEM supplementary list outside the quantitative main fit.",
        "- Do not convert non-Mw ComCat magnitude types without a documented conversion model.",
        "- GEAR1 is a static long-term model for shallow seismicity; this audit is not a short-term forecast.",
        "- For historical blind tests, the 2026 ISC-GEM release is a modern retrospective catalogue, not an as-of snapshot.", "",
        "## Provenance", "",
        "ISC-GEM v13.0: https://doi.org/10.31905/D808B825",
        "USGS ComCat: https://earthquake.usgs.gov/fdsnws/event/1/",
        "GEAR1: https://doi.org/10.1785/0120150058",
        f"ISC input SHA-256: {isc_meta['sha256']}", "",
    ]
    (output / "catalog_audit.md").write_text("\n".join(lines), encoding="utf-8")
    return manifest



def run_comcat_only(output: Path, start_date: str = "1976-01-01",
                    min_mag: float = 5.0) -> dict[str, Any]:
    """Create a modern ComCat-only diagnostic snapshot without ISC-GEM input."""
    output.mkdir(parents=True, exist_ok=True)
    end_date = datetime.now(timezone.utc).date().isoformat()
    payload, fetch_meta = fetch_comcat(start_date, end_date, min_mag)
    snapshot = output / "comcat_current_snapshot.geojson"
    snapshot.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    records, parse_meta = parse_comcat(snapshot, min_mag)
    fetch_meta.update(parse_meta)

    annual, decadal = audit_counts(records)
    spatial = spatial_counts(records)
    write_csv(output / "global_catalogue_normalized.csv", records)
    write_csv(output / "annual_global_counts.csv", annual)
    write_csv(output / "spatial_counts_5deg.csv", spatial)

    mw_count = sum(bool(row["mw_eligible"]) for row in records)
    years = sorted({_year(row) for row in records})
    manifest = {
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "catalogue_mode": "modern_comcat_only_diagnostic",
        "comcat": fetch_meta,
        "snapshot": {
            "path": snapshot.name,
            "sha256": sha256_file(snapshot),
            "feature_count": len(payload.get("features") or []),
        },
        "counts": {
            "comcat_records": len(records),
            "mw_eligible": mw_count,
            "mw_excluded_by_type": len(records) - mw_count,
        },
        "year_range": [years[0], years[-1]] if years else None,
        "thresholds": list(THRESHOLDS),
        "shallow_depth_km": [0, MAX_SHALLOW_KM],
        "magnitude_rule": "Only preferred magnitude types mw/mww/mwc/mwb/mwr enter Mw-threshold counts; all other types are retained but excluded from Mw counts.",
        "limitations": [
            "This is a current ComCat snapshot. Preferred magnitudes, event locations and products may be revised after origin time.",
            "The snapshot is not a historical as-of catalogue and must not be used as a strict blind hindcast input.",
            "ComCat magnitude types and completeness vary across time, region and network; this output is an audit diagnostic only.",
            "Annual global totals do not establish spatially varying magnitude completeness.",
            "Unknown depth is not assumed shallow; missing Mw is not imputed.",
            "This pipeline does not yet generate calibrated earthquake probabilities.",
        ],
        "files": [
            "comcat_current_snapshot.geojson",
            "global_catalogue_normalized.csv",
            "annual_global_counts.csv",
            "spatial_counts_5deg.csv",
            "catalog_manifest.json",
            "catalog_audit.md",
        ],
    }
    (output / "catalog_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Global ComCat-only catalogue audit",
        "",
        f"Created: {manifest['created_utc']}",
        f"Period: {manifest['year_range']}",
        f"ComCat records: {len(records):,}; Mw-eligible: {mw_count:,}; excluded non-Mw magnitude types: {len(records) - mw_count:,}",
        "",
        "This is a modern current ComCat snapshot, not a historical as-of catalogue.",
        "Counts are shallow (depth <=70 km) and include only Mw-equivalent preferred magnitude types.",
        "Annual totals are diagnostics, not a formal spatially varying completeness estimate.",
        "",
        "| Period | " + " | ".join(f"Mw>={x:.1f}" for x in THRESHOLDS) + " |",
        "|---|" + "---:|" * len(THRESHOLDS),
    ]
    for row in decadal:
        lines.append(
            "| " + row["period"] + " | "
            + " | ".join(str(row[f"mw_ge_{threshold:.1f}"]) for threshold in THRESHOLDS)
            + " |"
        )
    lines.extend([
        "",
        "## Safeguards",
        "",
        "- Do not infer one global magnitude-of-completeness threshold from global event totals.",
        "- Compare counts by tectonic region and time; network density and reporting practices differ.",
        "- Do not convert mb, Ms or other non-Mw magnitude types without a documented conversion model.",
        "- Do not treat this current ComCat response as a strict historical as-of snapshot.",
        "- GEAR1 is a static long-term model, not a short-term aftershock forecast.",
        "",
        "## Provenance",
        "",
        "USGS ComCat FDSN Event Web Service: https://earthquake.usgs.gov/fdsnws/event/1/",
        "GEAR1: https://doi.org/10.1785/0120150058",
        f"Snapshot SHA-256: {manifest['snapshot']['sha256']}",
        "",
    ])
    (output / "catalog_audit.md").write_text("\n".join(lines), encoding="utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--isc-main", type=Path)
    p.add_argument("--isc-supplement", type=Path)
    p.add_argument("--comcat-geojson", type=Path)
    p.add_argument("--fetch-comcat", action="store_true")
    p.add_argument("--comcat-only", action="store_true",
                   help="Run an explicitly modern ComCat-only diagnostic without ISC-GEM")
    p.add_argument("--comcat-start", default="2023-01-01")
    p.add_argument("--comcat-min-magnitude", type=float, default=5.0)
    p.add_argument("--output", type=Path, default=Path("research/outputs/global-catalogue"))
    a = p.parse_args()
    if a.comcat_only:
        if not a.fetch_comcat:
            p.error("--comcat-only requires --fetch-comcat")
        result = run_comcat_only(a.output, a.comcat_start, a.comcat_min_magnitude)
        print(f"Modern ComCat diagnostic: {result['counts']['comcat_records']} events; {result['counts']['mw_eligible']} Mw-eligible")
    else:
        if a.isc_main is None:
            p.error("--isc-main is required unless --comcat-only is selected")
        result = run(a.isc_main, a.output, a.isc_supplement, a.comcat_geojson,
                     a.fetch_comcat, a.comcat_start, a.comcat_min_magnitude)
        print(f"Catalogue prepared: {result['counts']['combined']} events; {result['counts']['mw_eligible']} Mw-eligible")
    print(a.output / "catalog_audit.md")


if __name__ == "__main__":
    main()
