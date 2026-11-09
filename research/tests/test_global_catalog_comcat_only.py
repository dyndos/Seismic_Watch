import json
from datetime import datetime, timezone

from research import global_catalog


def test_comcat_only_audit_writes_snapshot_and_marks_it_as_modern(monkeypatch, tmp_path):
    timestamp = int(datetime(2020, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "event-mww",
                "properties": {
                    "mag": 6.6,
                    "magType": "mww",
                    "type": "earthquake",
                    "time": timestamp,
                    "reviewstatus": "reviewed",
                    "net": "us",
                },
                "geometry": {"type": "Point", "coordinates": [140.0, 35.0, 18.0]},
            },
            {
                "type": "Feature",
                "id": "event-mb",
                "properties": {
                    "mag": 6.8,
                    "magType": "mb",
                    "type": "earthquake",
                    "time": timestamp + 1000,
                    "reviewstatus": "reviewed",
                    "net": "us",
                },
                "geometry": {"type": "Point", "coordinates": [141.0, 36.0, 12.0]},
            },
        ],
    }

    def fake_fetch(start_date, end_date, min_mag):
        assert start_date == "1976-01-01"
        assert min_mag == 5.0
        return payload, {"source": "fake ComCat", "unique_count": 2}

    monkeypatch.setattr(global_catalog, "fetch_comcat", fake_fetch)
    result = global_catalog.run_comcat_only(tmp_path, "1976-01-01", 5.0)

    assert result["catalogue_mode"] == "modern_comcat_only_diagnostic"
    assert result["counts"]["comcat_records"] == 2
    assert result["counts"]["mw_eligible"] == 1
    assert (tmp_path / "comcat_current_snapshot.geojson").is_file()
    assert (tmp_path / "global_catalogue_normalized.csv").is_file()
    assert (tmp_path / "annual_global_counts.csv").is_file()
    assert (tmp_path / "spatial_counts_5deg.csv").is_file()
    report = (tmp_path / "catalog_audit.md").read_text(encoding="utf-8")
    assert "current ComCat snapshot" in report
    assert "\\n".join(["## Safeguards", ""]) in report
    manifest = json.loads((tmp_path / "catalog_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["mw_excluded_by_type"] == 1
