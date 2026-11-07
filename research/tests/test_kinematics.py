import math

import numpy as np

from research.kinematics import (
    _plate_omega, kinematic_features, load_boundary_segments, load_morvel,
    plate_velocity_mm_yr,
)


def test_morvel56_has_56_entries_and_pacific_reference_is_zero():
    plates = load_morvel()
    assert len(plates) == 56
    assert np.allclose(_plate_omega("PA", plates), np.zeros(3))
    assert _plate_omega("SO", plates) is not None
    assert _plate_omega("YA", plates) is not None
    assert _plate_omega("AF", plates) is None


def test_plate_velocity_matches_independent_sydney_reference_mm_per_year():
    """AU Euler pole evaluated inside the Australian plate near Sydney.

    Reference vector is independently evaluated from the Table 3 Euler pole
    (60.08 N, 6.33 E, 1.079 deg/Ma) using v = omega x r and local ENU axes.
    The 0,0 point used in the original test is outside AU; evaluating an Euler
    pole there is mathematically possible but is not a meaningful plate-site
    sanity bound and yields about 104.2 mm/yr.
    """
    plates = load_morvel()
    velocity = plate_velocity_mm_yr(-33.8688, 151.2093, "AU", plates)
    assert velocity is not None
    np.testing.assert_allclose(
        velocity,
        np.array([59.06442475, 34.42860332]),
        rtol=1e-6,
        atol=1e-5,
    )
    assert 60.0 < float(np.linalg.norm(velocity)) < 80.0


def test_relative_motion_has_finite_speed_and_components():
    plates = load_morvel()
    segment = {
        "name": "synthetic boundary", "plate_a": "PA", "plate_b": "AU",
        "boundary_type": "subduction", "lon1": 150.0, "lat1": -34.0,
        "lon2": 152.0, "lat2": -34.0,
    }
    result = kinematic_features(-33.8688, 151.2093, plates, [segment])
    assert result["relative_speed_mm_yr"] > 0
    assert math.isfinite(result["normal_velocity_mm_yr"])
    assert math.isfinite(result["parallel_velocity_mm_yr"])


def test_pb2002_codes_are_loaded_and_annotatable():
    segments = load_boundary_segments()
    assert len(segments) > 100
    result = kinematic_features(-20.0, 170.0, load_morvel(), segments)
    assert result["boundary_distance_km"] is not None
    assert result["boundary_name"] is not None
