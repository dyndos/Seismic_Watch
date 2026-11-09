import json
from pathlib import Path

from research.global_catalog import (
    parse_comcat,
    read_isc_csv,
    run,
)


HEADER = (
    "# date , lat , lon, smajax, sminax, strike, q, depth, unc, q, "
    "mw, unc, q, s, mo, fac, mo_auth, mpp, mpr, mrr, mrt, mtp, mtt, eventid"
)


def _isc_row(date, lat, lon, depth, mw, event_id, quality="A"):
    return (
        f"{date}, {lat}, {lon}, 4.0, 3.0, 45.0, A, {depth}, 2.0, A, "
        f"{mw}, 0.10, {quality}, d, 1.2, 19, gcmt, 0, 0, 0, 0, 0, 0, {event_id}"
    )


def test_isc_gem_duplicate_quality_columns_are_parsed_positionally(tmp_path):
    path = tmp_path / "iscgem_main.csv"
    path.write_text(
        HEADER + "\n"
        + _isc_row("2001-02-03 04:05:06.70", 12.5, 130.1, 18.0, 6.7, 101)
        + "\n",
        encoding="utf-8",
    )
    rows, manifest = read_isc_csv(path)
    assert manifest["header_found"] is True
    assert len(rows) == 1
    assert rows[0]["mw"] == 6.7
    assert rows[0]["mw_unc"] == 0.1
    assert rows[0]["mw_quality"] == "A"
    assert rows[0]["source_record_id"] == "101"


def test_supplementary_events_are_not_mw_eligible(tmp_path):
    path = tmp_path / "iscgem_supplement.csv"
    path.write_text(
        HEADER + "\n"
        + _isc_row("2005-01-01 00:00:00", -5.0, 105.0, 20.0, 6.5, 202, quality="D")
        + "\n",
        encoding="utf-8",
    )
    rows, manifest = read_isc_csv(path, supplementary=True)
    assert manifest["role"] == "supplement_only_not_used_for_rate_fit"
    assert rows[0]["mw"] is None
    assert rows[0]["mw_eligible"] is False


def test_comcat_only_explicit_mw_types_enter_mw_counts(tmp_path):
    path = tmp_path / "comcat.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "mw-event",
                "properties": {
                    "mag": 6.6, "magType": "mww", "type": "earthquake",
                    "time": 1_700_000_000_000,
                },
                "geometry": {"type": "Point", "coordinates": [140.0, 35.0, 20.0]},
            },
            {
                "type": "Feature",
                "id": "mb-event",
                "properties": {
                    "mag": 6.8, "magType": "mb", "type": "earthquake",
                    "time": 1_700_000_010_000,
                },
                "geometry": {"type": "Point", "coordinates": [141.0, 36.0, 20.0]},
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    rows, meta = parse_comcat(path, min_mag=5.0)
    assert len(rows) == 2
    assert meta["excluded_non_mw_types"] == {"mb": 1}
    assert rows[0]["mw_eligible"] is True
    assert rows[1]["mw_eligible"] is False
    assert rows[1]["mw"] is None


def test_global_catalogue_audit_keeps_unknown_depth_out_of_shallow_counts(tmp_path):
    main = tmp_path / "main.csv"
    main.write_text(
        HEADER + "\n"
        + _isc_row("2000-01-01 00:00:00", 10.0, 20.0, 25.0, 6.5, 1) + "\n"
        + _isc_row("2000-02-01 00:00:00", 11.0, 21.0, 80.0, 7.0, 2) + "\n"
        + _isc_row("2001-01-01 00:00:00", 12.0, 22.0, 15.0, 7.5, 3) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    manifest = run(main, output)
    assert manifest["counts"]["combined"] == 3
    assert manifest["counts"]["mw_eligible"] == 3
    assert (output / "global_catalogue_normalized.csv").is_file()
    assert (output / "annual_global_counts.csv").is_file()
    assert (output / "spatial_counts_5deg.csv").is_file()
    assert (output / "catalog_audit.md").is_file()
    annual = (output / "annual_global_counts.csv").read_text(encoding="utf-8-sig")
    assert "2000" in annual and "2001" in annual
