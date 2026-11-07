import numpy as np

from research.modeling import (
    fit_spatial_rate_models, forecast_k3, forecast_k4, probabilities_from_rate,
)


def _cells():
    return [
        {"relative_speed_mm_yr": 20.0, "normal_velocity_mm_yr": 10.0,
         "parallel_velocity_mm_yr": 17.0, "boundary_distance_km": 10.0,
         "motion_azimuth_deg": 60.0},
        {"relative_speed_mm_yr": 5.0, "normal_velocity_mm_yr": 1.0,
         "parallel_velocity_mm_yr": 4.9, "boundary_distance_km": 80.0,
         "motion_azimuth_deg": 10.0},
        {"relative_speed_mm_yr": None, "normal_velocity_mm_yr": None,
         "parallel_velocity_mm_yr": None, "boundary_distance_km": None,
         "motion_azimuth_deg": None},
    ]


def test_poisson_probability_is_monotonic_with_rate_and_time():
    p1 = probabilities_from_rate(np.array([0.01]), 1)
    p7 = probabilities_from_rate(np.array([0.01]), 7)
    p_fast = probabilities_from_rate(np.array([0.02]), 7)
    assert 0 <= p1[0] < p7[0] < p_fast[0] < 1


def test_k0_and_k1_return_nonnegative_spatial_rates():
    result = fit_spatial_rate_models(
        _cells(), np.array([2.0, 1.0, 0.0]), 20.0,
        {"coupling_fraction": np.array([np.nan, np.nan, np.nan]),
         "slip_deficit_mm_yr": np.array([np.nan, np.nan, np.nan]),
         "model_count": np.zeros(3)},
    )
    assert np.all(result["K0"] >= 0)
    assert np.all(result["K1"] >= 0)
    assert result["status"]["K0"] == "ok"


def test_k3_k4_interval_probabilities_are_bounded():
    rate = np.array([0.01, 0.02])
    cfs = np.array([0.1, -0.1])
    k3 = forecast_k3(rate, cfs, 7.0)
    k4 = forecast_k4(rate, cfs, 7.0, 14.0)
    assert np.all((k3["probability"] >= 0) & (k3["probability"] <= 1))
    assert np.all((k4["probability"] >= 0) & (k4["probability"] <= 1))
    assert k3["probability"][0] > k3["probability"][1]
    assert k4["probability"][0] > k4["probability"][1]
