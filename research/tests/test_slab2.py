import numpy as np
import xarray as xr

from research.slab2 import load_slab2


def _write_grid(path, values):
    ds = xr.Dataset(
        {"z": (("y", "x"), np.asarray(values, dtype=float))},
        coords={
            "x": ("x", np.array([10.0, 11.0, 12.0])),
            "y": ("y", np.array([0.0, 1.0, 2.0])),
        },
    )
    ds["x"].attrs["units"] = "degrees_east"
    ds["y"].attrs["units"] = "degrees_north"
    ds.to_netcdf(path)


def test_slab2_grids_are_sampled_and_attached_to_cells(tmp_path):
    _write_grid(
        tmp_path / "test_slab2_str_02.24.grd",
        [[88, 89, 90], [89, 90, 91], [90, 91, 92]],
    )
    _write_grid(
        tmp_path / "test_slab2_dip_02.24.grd",
        [[20, 21, 22], [30, 31, 32], [40, 41, 42]],
    )
    _write_grid(
        tmp_path / "test_slab2_dep_02.24.grd",
        [[10, 11, 12], [20, 21, 22], [30, 31, 32]],
    )
    cells = [
        {"latitude": 1.0, "longitude": 11.0},
        {"latitude": 35.0, "longitude": 35.0},
    ]
    output, manifest = load_slab2(tmp_path, cells)
    assert output[0]["slab2_strike_deg"] == 90.0
    assert output[0]["slab2_dip_deg"] == 31.0
    assert output[0]["slab2_depth_km"] == 21.0
    assert output[0]["slab2_model_count"] == 1
    assert output[1]["slab2_strike_deg"] is None
    assert manifest["cells_with_strike_dip"] == 1
    assert manifest["regions_used"] == ["test"]

def _write_gmt_classic_grid(path, values):
    values = np.asarray(values, dtype=float)
    ny, nx = values.shape
    ds = xr.Dataset(
        {
            "x_range": ("side", [10.0, 12.0]),
            "y_range": ("side", [0.0, 2.0]),
            "spacing": ("side", [1.0, 1.0]),
            "dimension": ("side", [nx, ny]),
            # GMT flat grids are scanline-ordered from north to south.
            "z": ("xysize", values.reshape(-1)),
        }
    )
    ds.attrs["node_offset"] = 0
    ds.to_netcdf(path)


def test_slab2_reads_gmt_classic_flat_netcdf_grids(tmp_path):
    _write_gmt_classic_grid(
        tmp_path / "test_slab2_str_02.24.grd",
        [[90, 91, 92], [80, 81, 82], [70, 71, 72]],
    )
    _write_gmt_classic_grid(
        tmp_path / "test_slab2_dip_02.24.grd",
        [[20, 21, 22], [30, 31, 32], [40, 41, 42]],
    )
    _write_gmt_classic_grid(
        tmp_path / "test_slab2_dep_02.24.grd",
        [[10, 11, 12], [20, 21, 22], [30, 31, 32]],
    )
    cells = [
        {"latitude": 2.0, "longitude": 11.0},
        {"latitude": 35.0, "longitude": 35.0},
    ]
    output, manifest = load_slab2(tmp_path, cells)
    assert output[0]["slab2_strike_deg"] == 91.0
    assert output[0]["slab2_dip_deg"] == 21.0
    assert output[0]["slab2_depth_km"] == 11.0
    assert output[1]["slab2_strike_deg"] is None
    assert manifest["cells_with_strike_dip"] == 1
    assert manifest["grid_errors"] == []

