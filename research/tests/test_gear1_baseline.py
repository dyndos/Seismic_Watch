import numpy as np
import pytest

from research.gear1_baseline import (
    cell_expected_count,
    combine_parent_rates,
    poisson_probability_at_least_one,
    regional_probability_at_least_one,
)


def test_gear1_loglinear_mix_uses_published_exponent_and_normalizes_global_rate():
    seismicity = np.array([1.0, 2.0, 4.0])
    tectonic = np.array([4.0, 2.0, 1.0])
    areas = np.array([10.0, 20.0, 30.0])
    combined, meta = combine_parent_rates(
        seismicity, tectonic, areas, target_global_rate_per_year=180.0
    )
    assert np.all(combined > 0)
    assert meta["seismicity_exponent"] == 0.6
    assert meta["tectonic_exponent"] == 0.4
    assert np.isclose(np.sum(combined * areas), 180.0, rtol=1e-9)


def test_gear1_parent_arrays_must_not_be_median_imputed():
    with pytest.raises(ValueError, match="complete"):
        combine_parent_rates(
            np.array([1.0, np.nan]), np.array([2.0, 3.0]),
            np.array([1.0, 1.0]), target_global_rate_per_year=5.0,
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
