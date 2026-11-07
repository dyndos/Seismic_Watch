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


def test_plate_velocity_is_in_mm_per_year():
    plates = load_morvel()
    v = plate_velocity_mm_yr(0.0, 0.0, "AU", plates)
    assert v is not None
    assert v.shape == (2,)
    assert 0.01 < float(np.linalg.norm(v)) < 200.0


def test_relative_motion_has_finite_speed_and_components():
    plates = load_morvel()
    segment = {
        "name": "synthetic boundary", "plate_a": "PA", "plate_b": "AU",
        "boundary_type": "subduction", "lon1": -1.0, "lat1": 0.0,
        "lon2": 1.0, "lat2": 0.0,
    }
    result = kinematic_features(0.0, 0.0, plates, [segment])
    assert result["relative_speed_mm_yr"] > 0
    assert math.isfinite(result["normal_velocity_mm_yr"])
    assert math.isfinite(result["parallel_velocity_mm_yr"])


def test_pb2002_codes_are_loaded_and_annotatable():
    segments = load_boundary_segments()
    assert len(segments) > 100
    result = kinematic_features(-20.0, 170.0, load_morvel(), segments)
    assert result["boundary_distance_km"] is not None
    assert result["boundary_name"] is not None
