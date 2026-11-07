# Historical hindcast test plan

## Purpose

Build a reproducible, offline-first hindcast experiment that asks whether information available at a fixed historical cutoff improves forecasts of subsequent earthquakes. This is an experimental evaluation, not an operational earthquake-warning system.

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

Each forecast record must store a separate probability for every horizon. A hit in the first 24 hours is a hit for 1d, 3d, 7d, etc., but it must not be counted as eight independent earthquakes. Report both horizon-level binary outcomes and the actual event list with event IDs and elapsed time from the cutoff.

## Fixed-cutoff protocol

For every historical cutoff t0:

1. Define the event catalog snapshot and the exact information cutoff. Ideally use a snapshot captured at t0. If only today's USGS ComCat is available, filter by occurrence time and label the result as an occurrence-time hindcast, not a strict historical-information replay: later catalog additions and revisions may still leak information.
2. Train or calibrate every model using events strictly before t0. For any historical analogue used to estimate a horizon-specific outcome rate, require its complete follow-up window to end before t0. This rule applies separately to each horizon.
3. Generate all horizon probabilities using only the permitted pre-t0 data.
4. Persist the forecast before reading the outcome window: t0, model/version, catalog snapshot identifier/hash, data cutoff, spatial cells/regions, magnitude threshold, distance/system criteria, horizon, probability, and configuration.
5. Evaluate outcomes in (t0, t0 + horizon]. A horizon is pending until its entire observation interval is covered by the catalog.
6. Never use post-t0 events to calculate the forecast probability. Post-t0 events are only for outcome scoring.

## Event definitions must be frozen before testing

Pre-register at least:
- magnitude threshold(s), for example M>=6.0 and M>=6.5 as separate targets;
- geographic unit (predefined grid cells or named tectonic regions);
- whether the target is any event, a remote event, or an event on a different boundary segment;
- minimum distance, if the target is remote activation;
- treatment of aftershocks and dependent sequences;
- catalog completeness and magnitude-type harmonization rules.

Do not tune these definitions after inspecting the test outcomes.

## Model tracks

Compare models on identical cutoffs, targets, and horizons:

- A: historical regional frequency baseline (Poisson / Gutenberg-Richter, as appropriate).
- B: A plus plate/boundary association.
- C: B plus focal-mechanism and fault-geometry features, only where data coverage is adequate.
- D: C plus a separately validated physical stress-transfer model (for example Coulomb stress change). Do not describe plate proximity or slip azimuth alone as Coulomb stress modelling.

Also report simple reference forecasts. A complex model is useful only if it improves on these baselines out of sample.

## Scoring

For each horizon and target report:
- Brier score and log loss from probabilities;
- calibration (predicted probability versus observed frequency);
- precision, recall, hit rate, false-alarm rate, and miss rate at any declared decision threshold;
- skill score against the baseline;
- number of eligible cutoffs, positive cases, negative cases, and pending/incomplete cases.

Do not use only a list of famous large earthquakes. Include regularly sampled negative/control cutoffs and use rolling-origin evaluation across many dates. Account for overlapping horizons and clustered/aftershock events when estimating uncertainty.

## First implementation boundary

The first implementation should be a dry-run/backtest tool on a feature branch. It must not change production behavior or imply deterministic prediction of an earthquake's exact time and place. First make temporal data separation testable; then add the horizon scoring and model comparisons.
