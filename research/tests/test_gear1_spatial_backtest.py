import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import xml.etree.ElementTree as ET

from research.gear1_spatial_backtest import (
    coordinate_to_grid_index,
    grid_index_from_xml_center,
    load_observations,
    parse_cell_values,
    poisson_log_likelihood,
    uniform_area_fraction_by_row,
)


def test_global_coordinate_mapping_edges_and_centres():
    assert coordinate_to_grid_index(-180.0, -90.0) == (0, 0)
    assert coordinate_to_grid_index(179.95, 89.95) == (1799, 3599)
    assert coordinate_to_grid_index(180.0, 90.0) == (1799, 3599)
    assert grid_index_from_xml_center(-179.95, -89.95) == (0, 0)
    assert grid_index_from_xml_center(179.95, 89.95) == (1799, 3599)


def test_cell_values_support_csep_text_and_child_bin_encodings():
    text_cell = ET.fromstring('<cell lon="0" lat="0">1e-3 2e-3 3e-3</cell>')
    values, labels = parse_cell_values(text_cell)
    assert values == [1e-3, 2e-3, 3e-3]
    assert labels == [None, None, None]

    child_cell = ET.fromstring('<cell lon="0" lat="0"><bin m="5.95">0.1</bin><bin m="6.05">0.2</bin></cell>')
    values, labels = parse_cell_values(child_cell)
    assert values == [0.1, 0.2]
    assert labels == [5.95, 6.05]


def test_catalogue_filters_source_depth_and_magnitude_and_separates_post_issue(tmp_path):
    path = tmp_path / "catalogue.csv"
    fields = ["source", "origin_time", "latitude", "longitude", "depth_km", "mw", "mw_eligible"]
    rows = [
        ["ISC-GEM-main", "2014-01-02T00:00:00Z", "10", "20", "15", "6.1", "True"],
        ["ISC-GEM-main", "2014-06-05T00:00:00Z", "11", "21", "20", "6.6", "True"],
        ["ISC-GEM-main", "2014-06-06T00:00:00Z", "12", "22", "80", "6.8", "True"],
        ["ISC-GEM-main", "2014-06-07T00:00:00Z", "13", "23", "10", "6.9", "False"],
        ["ComCat", "2014-06-08T00:00:00Z", "14", "24", "10", "7.0", "True"],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)

    start = datetime(2014, 1, 1, tzinfo=timezone.utc)
    issue = datetime(2014, 6, 4, 23, 59, 59, tzinfo=timezone.utc)
    end = datetime(2015, 1, 1, tzinfo=timezone.utc)
    windows, stats = load_observations(path, (5.95, 6.45), start, end, issue)

    assert sum(windows["full_period_hindcast"][0].values()) == 2
    assert sum(windows["full_period_hindcast"][1].values()) == 1
    assert sum(windows["post_issue_period"][0].values()) == 1
    assert sum(windows["post_issue_period"][1].values()) == 1
    assert stats["excluded_source"] == 1
    assert stats["excluded_not_mw_eligible"] == 1
    assert stats["excluded_not_shallow_0_70_km"] == 1


def test_poisson_log_likelihood_includes_empty_cell_penalty():
    value = poisson_log_likelihood(2.0, Counter({123: 2}), {123: 0.5})
    expected = -2.0 + 2 * math.log(0.5) - math.lgamma(3)
    assert math.isclose(value, expected, rel_tol=1e-12)


def test_area_weights_sum_to_spherical_global_weight():
    values = uniform_area_fraction_by_row()
    assert math.isclose(sum(values), 2.0, rel_tol=1e-12)
    assert values[0] < values[900]  # polar rows cover less surface area