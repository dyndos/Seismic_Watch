import numpy as np
import pytest

from research.gear1_baseline import (
    cell_expected_count,
    combine_parent_rates,
    poisson_probability_at_least_one,
    regional_probability_at_least_one,
)


def test_gear1_uses_source_parent_integral_target_and_exponents():
    seismicity = np.array([1.0, 2.0, 4.0])
    tectonic = np.array([4.0, 2.0, 1.0])
    areas = np.array([10.0, 20.0, 30.0])
    combined, meta = combine_parent_rates(seismicity, tectonic, areas)

    s_total = float(np.sum(seismicity * areas))
    t_total = float(np.sum(tectonic * areas))
    expected_target = s_total**0.6 * t_total**0.4

    assert np.all(combined > 0)
    assert meta["normalization_mode"] == "released_gear1_parent_integral_rule"
    assert meta["seismicity_exponent"] == 0.6
    assert meta["tectonic_exponent"] == 0.4
    assert np.isclose(meta["source_target_global_rate_per_year"], expected_target)
    assert np.isclose(np.sum(combined * areas), expected_target, rtol=1e-9)


def test_gear1_uses_original_floor_and_floor_preserving_correction():
    seismicity = np.array([1.0, 2.0, 4.0])
    tectonic = np.array([4.0, 2.0, 1.0])
    areas = np.array([10.0, 20.0, 30.0])
    combined, meta = combine_parent_rates(seismicity, tectonic, areas)

    d = 0.6
    s_floor = float(np.min(seismicity))
    t_floor = float(np.min(tectonic))
    expected_floor = max(s_floor**d * t_floor**(1.0 - d), min(s_floor, t_floor))
    raw = seismicity**d * tectonic ** (1.0 - d)
    expected_raw_integral = float(np.sum(raw * areas))
    expected_floor_integral = expected_floor * float(np.sum(areas))
    expected_target = meta["source_target_global_rate_per_year"]
    expected_correction = (
        expected_target - expected_floor_integral
    ) / (expected_raw_integral - expected_floor_integral)

    assert np.isclose(meta["hybrid_floor_rate_density_per_km2_year"], expected_floor)
    assert np.isclose(meta["normalization_correction"], expected_correction)
    assert np.all(combined >= expected_floor - 1e-12)


def test_gear1_explicit_global_rate_override_is_labelled_experimental():
    seismicity = np.array([1.0, 2.0, 4.0])
    tectonic = np.array([4.0, 2.0, 1.0])
    areas = np.array([10.0, 20.0, 30.0])
    combined, meta = combine_parent_rates(
        seismicity, tectonic, areas, target_global_rate_override_per_year=180.0
    )
    assert meta["normalization_mode"] == "experimental_global_rate_override"
    assert np.isclose(np.sum(combined * areas), 180.0, rtol=1e-9)


def test_gear1_parent_arrays_must_not_be_median_imputed():
    with pytest.raises(ValueError, match="complete"):
        combine_parent_rates(
            np.array([1.0, np.nan]), np.array([2.0, 3.0]),
            np.array([1.0, 1.0]),
        )


def test_gear1_rejects_target_override_below_the_integrated_floor():
    with pytest.raises(ValueError, match="below the integrated GEAR1 hybrid floor"):
        combine_parent_rates(
            np.array([1.0, 2.0]), np.array([2.0, 1.0]),
            np.array([1.0, 1.0]), target_global_rate_override_per_year=0.5,
        )


def test_gear1_probability_conversion_increases_with_time():
    rate = np.array([1e-7, 2e-7])
    area = np.array([1000.0, 2000.0])
    mu_30 = cell_expected_count(rate, area, 30)
    mu_90 = cell_expected_count(rate, area, 90)
    p_30 = poisson_probability_at_least_one(mu_30)
    p_90 = poisson_probability_at_least_one(mu_90)
    assert np.all(p_90 > p_30)
    aggregate = regional_probability_at_least_one(rate, area, 90)
    assert np.isclose(aggregate, poisson_probability_at_least_one(np.sum(mu_90)))


def test_gear1_probability_is_zero_for_zero_duration():
    mu = cell_expected_count(np.array([1e-7]), np.array([1e6]), 0)
    assert poisson_probability_at_least_one(mu)[0] == 0.0
