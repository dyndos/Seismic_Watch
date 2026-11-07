# Historical hindcast test plan

## Purpose

Build a reproducible, offline-first hindcast experiment that asks whether information available at a fixed historical cutoff improves forecasts of subsequent earthquakes. This is an experimental evaluation, not an operational earthquake-warning system.

A forecast must answer three separate questions:
1. **When?** What is the probability over each forecast horizon?
2. **Where?** Which geographic areas have elevated probability, and how is that probability distributed?
3. **How strong?** What magnitude threshold or magnitude range is being forecast?

Do not collapse these into one vague statement such as “increased seismic risk somewhere in the next year”.

## Forecast horizons

Do not impose a three-month minimum. Evaluate short and long horizons independently:

| Horizon ID | Duration |
| --- | ---: |
| 1d | 1 day |
| 3d | 3 days |
| 7d | 7 days |
| 14d | 14 days |
| 30d | 30 days |
| 90d | 90 days |
| 180d | 180 days |
| 365d | 365 days |

Each forecast record must store a separate probability for every horizon. A hit in the first 24 hours is a hit for 1d, 3d, 7d, etc., but it must not be counted as eight independent earthquakes. Report both horizon-level outcomes and the actual event list with event IDs and elapsed time from the cutoff.

In addition to cumulative horizons, report non-overlapping intervals (0–1d, 1–3d, 3–7d, 7–14d, 14–30d, 30–90d, 90–180d, 180–365d). Derive interval probabilities consistently from a calibrated time-to-event model or report them as independently estimated interval risks. Do not simply subtract unrelated estimates without checking coherence.

## Spatial forecast: where is the risk?

The model must produce a spatial risk surface for every horizon, not just one probability for the whole planet or plate system.

### Spatial output

For each cutoff, magnitude target, and horizon, persist:
- a fixed grid or a set of non-overlapping geographic/tectonic regions;
- a probability for each cell/region that at least one qualifying event will occur there during the horizon;
- expected event count per cell/region, where the model supports it;
- the highest-risk areas (ranked, with coordinates or polygon IDs and readable names);
- the grid resolution/region definition and the share of the Earth's/catalog-covered area evaluated.

Cell probabilities do **not** have to sum to 100%: several earthquakes can occur in different cells during the same horizon. If the model also produces a normalized location distribution for the next event, label that separately from the probability of one or more events in each cell.

Prefer a reproducible equal-area grid for global comparisons, with a second tectonic-region view for interpretation. Freeze the grid/region boundaries before evaluating test outcomes. Test more than one predeclared spatial resolution as a sensitivity analysis; do not choose the resolution that makes historical examples look best.

### Spatial evaluation

For each horizon and magnitude target, score both the timing and location:
- **Spatial Brier score / log score:** compare per-cell probabilities with the observed presence/absence of qualifying events in each cell.
- **Calibration by area:** among cells assigned similar risk, check whether the observed event frequency matches the forecast probability; account for very different cell areas and catalog coverage.
- **Area-based capture:** sort cells by forecast risk and measure what fraction of actual events fell within the top 5%, 10%, and 20% of forecasted area. These percentages must be set before testing.
- **Localization error:** distance from each observed epicenter to the nearest forecasted high-risk area, and distance to the highest-risk cell. Report distributions, not only an average.
- **Regional hit / false-alarm rates:** assess predefined tectonic regions independently, including regions forecast as low risk.
- **Spatial skill versus baseline:** compare against the same region's long-term event rate and other simple spatial baselines.

A forecast that names a very large area will capture more events by chance. Therefore report the area covered alongside every spatial hit rate. Do not award a precise-location hit merely because an event occurred somewhere on a whole plate or a broad 1,000-km radius.

Record actual event epicenters and event IDs; do not let one event count as many independent successes because it falls into overlapping regions or several nested cells. Use one primary non-overlapping spatial partition for scoring; tectonic boundaries can be an additional interpretation layer.

## Fixed-cutoff protocol

For every historical cutoff t0:

1. Define the event catalog snapshot and the exact information cutoff. Ideally use a snapshot captured at t0. If only today's USGS ComCat is available, filter by occurrence time and label the result as an occurrence-time hindcast, not a strict historical-information replay: later catalog additions and revisions may still leak information.
2. Train or calibrate every model using events strictly before t0. For any historical analogue used to estimate a horizon-specific outcome rate, require its complete follow-up window to end before t0. This rule applies separately for each horizon.
3. Generate temporal and spatial forecasts using only the permitted pre-t0 data.
4. Persist the forecast before reading the outcome window: t0, model/version, catalog snapshot identifier/hash, data cutoff, grid/region version, cell probabilities, magnitude threshold, distance/system criteria, horizon, and configuration.
5. Evaluate outcomes in (t0, t0 + horizon]. A horizon is pending until its entire observation interval is covered by the catalog.
6. Never use post-t0 events to calculate the forecast probability or rank regions. Post-t0 events are only for outcome scoring.

## Event definitions must be frozen before testing

Pre-register at least:
- magnitude threshold(s), for example M>=6.0 and M>=6.5 as separate targets;
- primary non-overlapping spatial grid/region partition and any secondary tectonic-region layer;
- cell size/resolution and the area-based top-risk cutoffs;
- whether the target is any event, a remote event, or an event on a different boundary segment;
- minimum distance, if the target is remote activation;
- treatment of aftershocks and dependent sequences;
- catalog completeness and magnitude-type harmonization rules.

Do not tune these definitions after inspecting the test outcomes.

## Model tracks

Compare models on identical cutoffs, targets, spatial partitions, and horizons. The physical-model input definitions, source datasets and caveats are documented separately in [PHYSICAL_MODEL_DATA.md](./PHYSICAL_MODEL_DATA.md).

- **K0 — Statistical baseline:** regional/global event-rate models (Poisson / Gutenberg-Richter, and ETAS where appropriate).
- **K1 — Plate kinematics:** K0 plus relative plate-motion vector at the event/candidate cell, decomposed into boundary-normal convergence/divergence and boundary-parallel motion.
- **K2 — Geodetic loading:** K1 plus Coupling Cloud coupling/slip-deficit variables where compatible NetCDF coverage exists. Current Coupling Cloud data are modern and are scored as retrospective geophysics, not as historical as-of information.
- **K3 — Coseismic stress transfer:** K2 (or K1 if coupling coverage is unavailable) plus as-of USGS finite-fault product geometry where available, otherwise a labelled moment-tensor rectangle proxy; CUTDE half-space stress calculation; explicit source nodal-plane and receiver-fault scenarios.
- **K4 — Rate-and-state response:** K3 plus a Dieterich (1994) time-dependent response to the coseismic ΔCFS step. The model accounts for elapsed time since the triggering earthquake, but does not yet ingest measured afterslip or viscoelastic stress histories.

Do not use total plate mass as a direct predictor in the first model. At plate-tectonic timescales inertia is negligible in the force balance; local fault loading and stress transfer are better represented by relative plate motion, coupling/slip deficit, source rupture slip, receiver-fault geometry and material parameters. A plate-wide mass figure does not tell us the local stress or which fault is closer to failure. Slab negative buoyancy / slab pull may be explored later as a separate geodynamic feature where geometry and density/thermal structure are available.

The direction of plate motion at the triggering event is useful only when defined as a relative velocity vector between the plates and resolved into local boundary-normal and boundary-parallel components. It is not, by itself, the direction of subsequent stress transfer. For the latter, use the finite rupture geometry/slip and receiver faults.

Retain a new physical feature family only if an ablation test demonstrates repeatable out-of-sample improvement beyond the simpler model, across multiple regions and cutoffs. Report physical-data coverage and uncertainty separately; do not let a model appear better merely because it is evaluated on a small set of well-studied earthquakes.

## Scoring

For each horizon, magnitude target, and model report:
- Brier score and log loss from temporal probabilities;
- spatial Brier/log score and spatial calibration;
- area-based capture at predeclared risk-area thresholds, with area covered;
- localization-error distributions;
- precision, recall, hit rate, false-alarm rate, and miss rate at declared decision thresholds;
- skill score against temporal and spatial baselines;
- number of eligible cutoffs, positive cases, negative cases, and pending/incomplete cases.

Do not use only a list of famous large earthquakes. Include regularly sampled negative/control cutoffs and use rolling-origin evaluation across many dates. Account for overlapping horizons and clustered/aftershock events when estimating uncertainty.

## First implementation boundary

The first implementation is in `research/` and runs offline after downloading and snapshotting its inputs. It does not change the Next.js production code. The command `python -m research.run_blind_test` builds an equal-area grid, freezes all forecast probability surfaces before scoring outcomes, then produces per-cutoff and aggregate JSON/CSV outputs. It defaults to 2022–2023 M>=6.5 triggers, monthly calendar controls, 500-km equal-area cells, and horizons of 1, 3, 7, 14, 30, 90, 180 and 365 days. It records both cumulative probabilities and non-overlapping interval probabilities.

Important classification: the current USGS ComCat endpoint is not a historical catalog archive. The runner therefore labels its default evaluation an **occurrence-time hindcast**, not a strict replay of what was publicly known at each cutoff: later event additions/revisions can be present in today's query. Current Coupling Cloud products are an additional retrospective-modern-data layer. Do not combine K0/K1 and K2–K4 into one unqualified "blind accuracy" number. Source-event product payloads and the queried catalog are compressed and hashed alongside the frozen forecasts so that this exact run can be inspected later.

It must not change production behavior or imply deterministic prediction of an earthquake's exact time and place. The first validation target is whether K1–K4 improve spatial and temporal skill over K0; any physical feature with insufficient coverage is marked unscored instead of imputed.