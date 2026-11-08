from datetime import datetime, timezone

from research.gcmt import (
    attach_gcmt_solution, match_gcmt_solutions, parse_ndk_catalog,
)


def _ndk_block():
    line1 = "PDE  2020/01/01 00:00:00.0  10.00  20.00  15.0 6.7 0.0 TEST REGION"
    line2 = "C202001010000A   B:  4    4  40 S: 27   33  50 M:  0    0   0 CMT: 1 TRIHD:  0.6"
    line3 = "CENTROID:      0.0 0.1  10.01 0.02   20.02 0.02  16.0  1.0 FREE S-20200102000000"
    line4 = "26  0.838 0.201 -0.005 0.231 -0.833 0.270  1.050 0.121 -0.369 0.161  0.044 0.240"
    line5 = "V10" + " " * 46 + f"{1.312:7.3f}" + " " + "90 45 90 270 45 -90"
    return "\n".join((line1, line2, line3, line4, line5))


def test_parse_ndk_solution_time_and_both_nodal_planes():
    records = parse_ndk_catalog(_ndk_block())
    assert len(records) == 1
    record = records[0]
    assert record["event_name"] == "C202001010000A"
    assert record["solution_stamp"] == "S-20200102000000"
    assert record["strike"] == 90.0
    assert record["dip"] == 45.0
    assert record["rake"] == 90.0
    assert record["strike2"] == 270.0
    assert 6.5 < record["magnitude_mw"] < 7.0


def test_gcmt_matches_comcat_by_origin_time_and_location():
    record = parse_ndk_catalog(_ndk_block())[0]
    event_time = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    feature = {
        "id": "us-test",
        "properties": {"time": event_time + 5_000, "mag": 6.7},
        "geometry": {"type": "Point", "coordinates": [20.05, 10.02, 15.0]},
    }
    matched = match_gcmt_solutions([feature], [record])
    assert "us-test" in matched
    assert matched["us-test"]["solution_stamp"] == "S-20200102000000"


def test_gcmt_product_is_attached_and_future_usgs_products_are_removed():
    record = parse_ndk_catalog(_ndk_block())[0]
    cutoff = record["solution_update_ms"] + 7 * 86_400_000
    feature = {
        "id": "us-test",
        "properties": {
            "mag": 6.7,
            "products": {
                "moment-tensor": [{
                    "source": "usgs-future", "updateTime": cutoff + 1,
                    "properties": {},
                }],
            },
        },
        "geometry": {"type": "Point", "coordinates": [20.0, 10.0, 15.0]},
    }
    merged = attach_gcmt_solution(feature, record, cutoff)
    products = merged["properties"]["products"]
    assert len(products["moment-tensor"]) == 1
    assert products["moment-tensor"][0]["source"] == "gcmt"
    assert products["moment-tensor"][0]["updateTime"] == record["solution_update_ms"]
