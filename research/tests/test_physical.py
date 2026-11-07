import numpy as np

from research.physical import (
    _extract_moment_tensor, _fault_vectors, dieterich_cumulative_count,
    load_coupling_cloud, load_source_fault, rate_state_ensemble,
    resolve_coulomb,
)


def _feature(update_time=1_700_000_000_000):
    return {
        "id": "test-event",
        "properties": {
            "mag": 7.0,
            "time": 1_700_000_000_000,
            "products": {
                "moment-tensor": [{
                    "source": "us",
                    "updateTime": update_time,
                    "properties": {
                        "nodal-plane-1-strike": "90",
                        "nodal-plane-1-dip": "45",
                        "nodal-plane-1-rake": "90",
                        "nodal-plane-2-strike": "270",
                        "nodal-plane-2-dip": "45",
                        "nodal-plane-2-rake": "90",
                        "scalar-moment": "1e19",
                    },
                }]
            },
        },
        "geometry": {"coordinates": [0.0, 0.0, 10.0]},
    }


def test_moment_tensor_product_is_filtered_by_as_of_time():
    event = _feature()
    assert _extract_moment_tensor(event, 1_699_999_999_999) is None
    assert _extract_moment_tensor(event, 1_700_000_000_000)["strike"] == 90.0


def test_source_proxy_uses_moment_tensor_and_marks_its_quality():
    source = load_source_fault(_feature(), 1_700_000_000_000)
    assert source is not None
    assert source["quality"] == "moment_tensor_plus_empirical_rectangle_proxy"
    assert source["length_km"] > 0
    assert source["width_km"] > 0
    assert source["slip_m"] > 0


def test_fault_basis_is_orthonormal():
    strike, dip, slip = _fault_vectors(125.0, 35.0, 90.0)
    assert np.isclose(np.linalg.norm(strike), 1.0)
    assert np.isclose(np.linalg.norm(dip), 1.0)
    assert np.isclose(np.dot(strike, dip), 0.0)
    assert np.isclose(np.linalg.norm(slip), 1.0)


def test_coulomb_shear_changes_sign_when_rake_reverses():
    stress = np.array([0.0, 0.0, 0.0, 2.0e6, 0.0, 0.0])
    forward = resolve_coulomb(stress, 0.0, 90.0, 0.0)
    reverse = resolve_coulomb(stress, 0.0, 90.0, 180.0)
    assert np.isclose(forward, -reverse)


def test_dieterich_zero_stress_reduces_to_background_count():
    rate = np.array([0.01, 0.02])
    observed = dieterich_cumulative_count(rate, 0.0, 100.0, 0.1, 90.0)
    assert np.allclose(observed, rate * 100.0, rtol=1e-10, atol=1e-12)


def test_positive_stress_advances_rate_and_negative_stress_suppresses_it():
    rate = np.array([0.01])
    baseline = dieterich_cumulative_count(rate, 0.0, 30.0, 0.1, 90.0)
    positive = dieterich_cumulative_count(rate, 0.1, 30.0, 0.1, 90.0)
    negative = dieterich_cumulative_count(rate, -0.1, 30.0, 0.1, 90.0)
    assert positive[0] > baseline[0] > negative[0]


def test_rate_state_interval_counts_are_nonnegative_and_time_dependent():
    result = rate_state_ensemble(
        np.array([0.01]), np.array([0.1]), 7.0, 14.0
    )
    assert result["expected_count_median"][0] > 0
    assert result["expected_count_p10"][0] <= result["expected_count_median"][0]
    assert result["expected_count_p90"][0] >= result["expected_count_median"][0]


def test_empty_coupling_directory_does_not_impute_zero_values(tmp_path):
    result = load_coupling_cloud(tmp_path, [{"latitude": 0.0, "longitude": 0.0}])
    assert np.isnan(result["coupling_fraction"][0])
    assert np.isnan(result["slip_deficit_mm_yr"][0])



def test_as_of_usgs_finite_fault_product_is_preferred_over_moment_tensor():
    event = _feature()
    event["properties"]["products"]["finite-fault"] = [{
        "source": "us",
        "updateTime": 1_700_000_000_000,
        "properties": {
            "model-length": "40",
            "model-width": "18",
            "model-strike": "90",
            "model-dip": "30",
            "model-rake": "90",
            "model-top": "2",
            "scalar-moment": "1e19",
        },
    }]
    source = load_source_fault(event, 1_700_000_000_000)
    assert source is not None
    assert source["quality"] == "usgs_finite_fault_geometry_uniform_slip"
    assert source["length_km"] == 40.0
    assert source["width_km"] == 18.0
    assert source["finite_fault_product_update_ms"] == 1_700_000_000_000


def test_finite_fault_product_updated_after_cutoff_is_not_used():
    event = _feature(update_time=1_700_000_000_000)
    event["properties"]["products"]["finite-fault"] = [{
        "source": "us",
        "updateTime": 1_700_000_000_001,
        "properties": {
            "model-length": "40", "model-width": "18", "model-strike": "90",
            "model-dip": "30", "model-rake": "90", "scalar-moment": "1e19",
        },
    }]
    source = load_source_fault(event, 1_700_000_000_000)
    assert source is not None
    assert source["quality"] == "moment_tensor_plus_empirical_rectangle_proxy"
    assert "alternative_plane" in source


def test_cutde_halfspace_coulomb_smoke_with_two_nodal_plane_scenarios():
    import pytest
    pytest.importorskip("cutde")
    from research.physical import calculate_delta_cfs

    cells = [
        {"longitude": 2.0, "latitude": 0.0, "boundary_tangent_azimuth_deg": 90.0,
         "boundary_type": "subduction"},
        {"longitude": -2.0, "latitude": 0.0, "boundary_tangent_azimuth_deg": 90.0,
         "boundary_type": "subduction"},
    ]
    result = calculate_delta_cfs(_feature(), 1_700_000_000_000, cells)
    assert result is not None
    assert result["source_plane_scenarios"] == 2
    assert np.isfinite(result["delta_cfs_mpa"]).all()
    assert np.isfinite(result["delta_cfs_p10_mpa"]).all()
    assert np.isfinite(result["delta_cfs_p90_mpa"]).all()
