import csv

from research.global_catalog import write_csv


def test_write_csv_keeps_union_of_optional_spatial_threshold_fields(tmp_path):
    path = tmp_path / "spatial.csv"
    rows = [
        {"lat": 10, "lon": 20, "events": 3, "mw_ge_5.0": 3},
        {"lat": 15, "lon": 25, "events": 1, "mw_ge_5.0": 1, "mw_ge_6.0": 1},
    ]
    write_csv(path, rows)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        output = list(csv.DictReader(stream))
    assert len(output) == 2
    assert "mw_ge_6.0" in output[0]
    assert output[0]["mw_ge_6.0"] == ""
    assert output[1]["mw_ge_6.0"] == "1"
