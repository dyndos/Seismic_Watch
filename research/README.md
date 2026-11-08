# Seismic Watch research hindcast

This is a separate Python research runner. It does not change or run inside the Next.js application.

## What is implemented

- **K0:** smoothed historical per-cell Poisson-rate baseline.
- **K1:** K0 plus NNR-MORVEL56 relative plate-motion velocity, resolved into local boundary-normal and boundary-parallel components using the PB2002 geometry in the application.
- **K2:** K1 plus Coupling Cloud coupling and slip-deficit grids. Rectilinear and 2D curvilinear NetCDF grids are sampled geodesically. Sparse physical coverage is retained as an explicitly labelled partial-coverage hybrid rather than discarded.
- **K3:** CUTDE elastic half-space coseismic stress transfer from time-valid USGS finite-fault products or a Global CMT moment-tensor source proxy. Slab2 provides receiver-interface strike, dip and depth where available; PB2002 boundary scenarios are the documented fallback.
- **K4:** Dieterich rate-and-state response to the coseismic ΔCFS step. The interval model accounts for elapsed time since the triggering event. It does not yet ingest measured afterslip or viscoelastic stress histories.

K3/K4 use fixed material/receiver assumptions and scenario ensembles. They are research approximations, not calibrated operational forecasts.

## Environment

Python 3.12 is recommended. Install from the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r research/requirements.txt
```

CUTDE wheels are published for common platforms. On platforms without a compatible wheel, installing CUTDE from source may require a C++ compiler.

## Run the tests

```bash
python -m compileall -q research
pytest -q research/tests
```

The test suite checks plate velocity calculations and PB2002 code handling, as-of filtering of moment-tensor and finite-fault products, the Coulomb sign convention, the Dieterich zero-stress identity and rate response, K0-K4 probability bounds, and a small CUTDE half-space stress smoke test.

## Run the historical hindcast

Default settings:
- training catalogue: 2000-01-01 through 2024-12-31, M>=6.5;
- training catalogue: 2000-01-01 through 2025-12-31, M>=6.5;
- cutoffs: all M>=6.5 events in 2010–2024 with a matched, timestamped Global CMT mechanism and a complete 365-day outcome window (no subsampling by default);
- controls: first day of every month in 2010–2024;
- trigger cutoff: the later of origin time + 7 days or the Global CMT Q-/S- analysis timestamp;
- horizons: 1, 3, 7, 14, 30, 90, 180 and 365 days;
- primary grid: approximately 500-km equal-area cells (EPSG:6933);
- magnitude target: M>=6.5.

Run:

```bash
python -m research.run_blind_test --start-year 2010 --end-year 2024 --max-triggers 0 --download-coupling --download-slab2
```

To first make a smaller, quicker trial:

```bash
python -m research.run_blind_test --start-year 2022 --end-year 2022 --max-triggers 4 --no-controls
```

The Coupling Cloud archive is downloaded from its public all-models endpoint only when `--download-coupling` is passed. USGS Slab2 grids are downloaded only when `--download-slab2` is passed. Neither physical archive is committed to Git; local data are ignored under `research/data/`. The Global CMT NDK catalog is downloaded automatically and archived with the run.

## Output files

The default output directory is `research/outputs/blind-test/`:

- `catalog_snapshot.geojson.gz` — compressed queried USGS ComCat snapshot;
- `catalog_manifest.json` — query parameters and snapshot hashes;
- `gcmt_catalog.ndk.gz`, `gcmt_manifest.json` — Global CMT source-mechanism snapshot and matching provenance;
- `slab2_manifest.json` — Slab2 geometry coverage and the grid files used;
- `grid.json` — fixed cell centres and K1 features;
- `blind_test_manifest.json` — selected historical cutoffs and frozen-forecast hashes;
- `forecast_snapshots/*.npz` — cumulative and non-overlapping interval probability surfaces plus training counts;
- `forecast_snapshots/*.json` — per-cutoff metadata, model status and hashes;
- `forecast_snapshots/*.source.geojson.gz` — source-event detail/products used for K3/K4;
- `scores.csv`, `scores.json` — per-cutoff outcomes and spatial skill scores;
- `aggregate_scores.csv`, `aggregate_scores.json` — model/horizon summary, including the paired `common_k0_k4` group;
- `common_sample_manifest.json` — exact common trigger IDs used by all five models for each forecast horizon.

The forecasting phase writes every probability snapshot before the scoring phase reads any post-cutoff outcome window. The score table reports cumulative and interval spatial Brier/log-loss metrics, event capture in the top 5/10/20% of forecasted area, localization distance to the top 10% risk area and paired Brier skill versus K0.

## Important limitations

This is a **blind-style occurrence-time hindcast**, not a strict historical as-of replay. Today's USGS ComCat response can contain events added or revised after the historical cutoff. The runner filters training events by origin time and filters source products by their current product updateTime when that timestamp is available, but it cannot reconstruct older catalog/product versions that are no longer served. The raw catalog and event details are archived for reproducibility of this run.

Current Coupling Cloud and Slab2 data are modern geophysical products and were not necessarily available at historical cutoffs. Global CMT Q-/S- analysis timestamps are not exact public-release timestamps. K2-K4 are therefore separately labelled `retrospective_modern_geophysics`; do not compare them as if they were strict historical-information forecasts. K0/K1 are labelled `occurrence_time_hindcast`, which still carries the ComCat revision limitation.

K2 uses partial-coverage status whenever Coupling Cloud observations cover less than 80% of the global grid. Outside the observed footprint, missing physical values are imputed by the regularized feature pipeline; K2 is therefore a hybrid model and must not be described as globally observed coupling. K3/K4 use a time-valid USGS product or a Global CMT Q-/S- analysis timestamp no later than the cutoff. That timestamp is an analysis-time proxy, not a guaranteed public-release timestamp. Slab2 receiver geometry is static modern data; PB2002 scenarios are used where Slab2 does not cover a cell. Missing source mechanisms or insufficient stress-field coverage are not silently replaced with zero stress.

The grid-based baseline is deliberately simple. A complex model should be judged only by repeatable improvement over K0 across multiple cutoffs and regions. Overlapping time windows and triggered sequences are dependent; the aggregate means are descriptive and do not yet constitute formal confidence intervals or a prospective validation.

No earthquake's exact time and place can currently be predicted reliably by this tool. The experiment evaluates whether specified probability surfaces and intervals add skill over baselines, not deterministic prediction or public safety warning.
