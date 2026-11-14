import csv
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from research.gear1_backtest import run_backtest


def test_small_grid_backtest(tmp_path: Path):
    xml = tmp_path / "small.xml"
    catalog = tmp_path / "catalog.csv"
    output = tmp_path / "out"

    ns = "http://www.scec.org/xml-ns/csep/forecast/1.1"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}CSEPForecast")
    forecast_data = ET.SubElement(root, f"{{{ns}}}forecastData")
    for name, value in [
        ("modelName", "GEAR1"),
        ("issueDate", "2014-06-04T23:59:59Z"),
        ("forecastStartDate", "2014-01-01T00:00:00Z"),
        ("forecastEndDate", "2015-01-01T00:00:00Z"),
        ("magnitudeMinValue", "5.95"),
        ("magnitudeBinDimension", "0.1"),
        ("lastMagBinOpen", "1"),
    ]:
        ET.SubElement(forecast_data, f"{{{ns}}}{name}").text = value
    ET.SubElement(
        forecast_data,
        f"{{{ns}}}cellDimension",
        {"latRange": "0.1", "lonRange": "0.1"},
    )
    depth_layer = ET.SubElement(
        forecast_data, f"{{{ns}}}depthLayer", {"min": "0", "max": "70"}
    )
    cells = [
        (-89.95, -179.95, 1.0),
        (-89.95, -179.85, 2.0),
        (-89.85, -179.95, 3.0),
        (-89.85, -179.85, 4.0),
    ]
    for cell_number, (lat, lon, weight) in enumerate(cells):
        cell = ET.SubElement(
            depth_layer, f"{{{ns}}}cell", {"lat": str(lat), "lon": str(lon)}
        )
        values = [weight / (i + 1) for i in range(31)]
        if cell_number == 0:
            for i, value in enumerate(values):
                ET.SubElement(
                    cell, f"{{{ns}}}bin", {"m": str(5.95 + i * 0.1)}
                ).text = str(value)
        else:
            cell.text = "\n" + " ".join(str(value) for value in values) + "\n"
    ET.ElementTree(root).write(xml, encoding="utf-8", xml_declaration=True)

    fields = [
        "event_id", "origin_time", "latitude", "longitude",
        "depth_km", "mw", "mw_eligible",
    ]
    rows = [
        ["e1", "2014-02-01T00:00:00Z", -89.95, -179.95, 10, 6.00, True],
        ["e2", "2014-07-01T00:00:00Z", -89.85, -179.85, 20, 6.20, True],
        ["deep", "2014-08-01T00:00:00Z", -89.85, -179.85, 80, 6.20, True],
        ["pre", "2014-06-01T00:00:00Z", -89.85, -179.85, 20, 6.20, True],
    ]
    with catalog.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)

    report = run_backtest(
        xml,
        catalog,
        output,
        n_lon=2,
        n_lat=2,
        grid_step=0.1,
        summary_degrees=0.2,
    )
    full = report["windows"]["full_hindcast"]["scores_by_magnitude_threshold"][0]
    post = report["windows"]["post_issue"]["scores_by_magnitude_threshold"][0]

    assert report["xml"]["cells_parsed"] == 4
    assert report["catalogue"]["input_rows_eligible_for_scoring"] == 3
    assert full["observed_events"] == 3
    assert post["observed_events"] == 1
    assert full["spatial_information_gain_bits_per_event"] is not None
    assert math.isfinite(full["spatial_information_gain_bits_per_event"])
    assert abs(
        report["windows"]["post_issue"]["forecast_exposure_fraction"] - 210 / 365
    ) < 1e-6

    with (output / "gear1_event_matches.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        matches = {row["event_id"]: row for row in csv.DictReader(stream)}
    assert matches["e1"]["magnitude_bin_lower_edge"] == "5.95"
    assert matches["e2"]["magnitude_bin_lower_edge"] == "6.15"
    assert (output / "gear1_spatial_summary.csv").exists()
    json.loads((output / "gear1_backtest_metrics.json").read_text(encoding="utf-8"))
