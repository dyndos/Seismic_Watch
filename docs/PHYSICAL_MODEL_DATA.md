# Physical model inputs and data strategy

## Decision on whole-plate mass

Do **not** use the total mass of a tectonic plate as a direct predictor in the first model.

At plate-tectonic timescales, plate inertia is treated as negligible relative to the forces and torques acting on the lithosphere; plate motion is commonly analysed as a dynamic-equilibrium problem. Important driving/resisting mechanisms include slab pull, ridge push, trench/slab suction, and mantle/lithosphere coupling. A plate-wide mass scalar does not describe the local stress state or tell us which nearby fault is closer to failure.

A more physically meaningful long-term quantity, where defensible data exist, is the negative buoyancy / gravitational pull of a subducting slab. That requires information such as slab geometry, thickness, density/thermal structure and the attached plate configuration. It is not equivalent to multiplying plate area by an assumed average density. Treat slab-pull-related fields as an advanced research feature, not a required input for the first hindcast.

We may retain plate area, crust/lithosphere thickness, density and estimated mass only as documented exploratory metadata. They enter a model only if an ablation test demonstrates out-of-sample improvement beyond simpler kinematic and geodetic predictors.

## Physical reasoning: distinguish three processes

1. **Long-term tectonic loading:** relative plate motion, convergence/divergence/transform motion, locking and slip deficit gradually load faults.
2. **Coseismic stress transfer:** a particular earthquake releases slip over a finite fault surface and changes the stress field on other faults.
3. **Postseismic and transient processes:** afterslip, viscoelastic relaxation, fluid/pore-pressure changes and dynamic stresses can change stress after the main rupture.

These processes have different timescales and data needs. Do not combine them into a single unexplained "plate energy" or "stress" score.

## Input hierarchy

### Tier 1 — Plate kinematics (practical first physical feature set)

At each event epicenter and candidate forecast cell, identify the plates on both sides of the relevant boundary and calculate:

- absolute velocity vectors for each plate, in mm/year;
- relative velocity vector between the two plates;
- relative speed;
- velocity component normal to the boundary (convergence or divergence);
- velocity component parallel to the boundary (transcurrent motion);
- azimuth/direction of motion, reference frame, model epoch and uncertainty;
- boundary type and local boundary azimuth.

Do not use one global "plate direction" as if all points on a plate boundary have identical local motion components. Calculate the local relative vector and decompose it against the local boundary orientation. State whether the direction is relative to the other plate, a hotspot/mantle frame, or a geodetic reference frame.

Candidate sources:
- MORVEL angular velocities and covariance provide a well-established global geological plate-motion reference. It is a long-term kinematic model, not a live measurement of current strain.
- GPlates/EarthByte rotation models and plate geometries support explicit, versioned plate reconstructions and historical plate assignment. Pin the exact model and version; never rely on an unpinned default that may change.
- GNSS/GPS station velocities and regional geodetic solutions can estimate present-day crustal motion and local strain more directly. Track observation interval, reference frame, solution release date and uncertainty.

For a historical hindcast at t0, use only a kinematic/geodetic product that would have been available by t0 if claiming a strict historical replay. Otherwise label it as a retrospective model using modern geophysical reconstructions.

### Tier 2 — Interseismic coupling and strain accumulation (high value, uneven coverage)

Where published geodetic models exist, collect:
- coupling/locking fraction on the plate interface;
- slip-deficit rate (relative convergence multiplied by inferred coupling, with the source model's exact definition retained);
- locking depth and downdip/updip limits;
- strain-rate tensor or principal strain axes;
- uncertainty and spatial resolution.

These features are much closer to fault loading than total plate mass. Coverage and methodology are heterogeneous, so keep model identity and provenance for every region. Do not treat missing coupling data as zero coupling.

Candidate source: Coupling Cloud is a curated, versioned aggregation of published megathrust coupling models, including coupling uncertainty, interface depth and slip-deficit-related variables. It covers selected subduction zones, not all tectonic settings; inspect the underlying publication and original model before use.

### Tier 3 — Source earthquake geometry and slip (required for a defensible coseismic stress calculation)

For the triggering earthquake, prefer:
- finite-fault rupture surface (length, width, strike, dip, depth);
- spatial slip distribution and rake on subfaults;
- seismic moment and uncertainty;
- moment tensor / focal mechanism and both nodal planes, preserving ambiguity where the actual plane is unknown;
- product publication/update time, not only earthquake origin time.

A point epicenter, magnitude and one derived slip azimuth are not enough to calculate a robust spatial stress-transfer field. Use finite-fault products when available; where only a moment tensor exists, run a clearly labelled simplified source model and propagate the uncertainty over the two nodal planes and plausible dimensions/slip distributions.

Candidate source: USGS ComCat products include moment tensors/focal mechanisms and, for some large events, finite-fault products. Availability is event-dependent. Finite-fault models estimate rupture dimensions and slip distribution, which are the key source terms for stress-change calculation.

### Tier 4 — Receiver faults and subsurface structure

For each candidate receiving area, the physical calculation needs plausible receiver-fault geometries:
- strike, dip, rake / expected slip sense;
- depth and fault-plane extent;
- alternative orientations where the mechanism is ambiguous;
- local fault inventory and its positional/geometry uncertainty.

Relevant material/structural parameters may include elastic moduli (or shear modulus and Poisson's ratio), density, lithosphere/crustal thickness, seismic velocity structure, friction coefficient and pore-pressure assumptions. Their spatial variation and uncertainty matter. Do not fill unknown values with false precision.

### Tier 5 — Stress-transfer calculation (advanced model, not a proxy score)

Compute the source-induced stress-change tensor over a spatial grid from finite-fault slip, using a stated elastic or viscoelastic Earth model. Resolve that tensor onto candidate receiver-fault planes and calculate Coulomb failure stress change (ΔCFS / ΔCFF) using an explicitly documented sign convention and assumptions for friction and pore pressure.

Output should include:
- ΔCFS distribution per grid cell and receiver-fault scenario;
- positive/negative/near-zero stress regions;
- uncertainty range or ensemble spread;
- source model, receiver model, elastic assumptions and parameter values;
- cells where sign or magnitude is not robust across plausible models.

Static coseismic ΔCFS is not the whole stress history. Keep afterslip, viscoelastic relaxation, fluid-pressure evolution and dynamic triggering as separate model components if and when their data are available.

## Why direction of motion at the original event matters

The motion direction is useful when expressed as **relative plate motion at the event location**, resolved into boundary-normal and boundary-parallel components. It helps distinguish convergent, divergent and transform settings, and it can inform long-term loading / slip-deficit estimates.

It does not, by itself, give the direction in which a stress perturbation propagates after an earthquake. Static stress changes are spatially distributed according to the finite source rupture and the receiver-fault geometry; the pattern is not simply an arrow pointing along the plate-motion direction. Use the earthquake's slip distribution and receiving faults for this part.

## Data provenance and anti-leakage rules

Every physical input must carry:
- source name and stable URL/DOI;
- model/dataset version and retrieval date;
- observation period / model epoch;
- reference frame and coordinate convention where relevant;
- spatial resolution;
- uncertainty or an explicit "not provided";
- publication/product creation and update times, where available;
- historical availability status relative to t0.

For the retrospective experiment, distinguish:
- **strict as-of hindcast:** all input products were publicly available by t0;
- **occurrence-time hindcast:** earthquake occurrence data are cut off at t0, but modern versions of static/geophysical models may be used;
- **modern-data retrospective analysis:** uses later products to explain an older sequence and is not counted as a blind forecast test.

Do not silently mix these categories in the same score table.

## Experiments and ablation

Evaluate physical features in controlled steps with identical cutoffs, event definitions, grids and horizons:

- K0: frequency/statistical baseline.
- K1: K0 + plate kinematics (relative speed, convergence/divergence, transform component).
- K2: K1 + geodetic coupling / slip deficit / strain (where coverage permits).
- K3: K2 + earthquake source finite-fault geometry and coseismic stress transfer.
- K4: K3 + available postseismic/transient stress terms.

For each step report both temporal and spatial skill, calibration and uncertainty. Run ablation tests that remove one feature family at a time. A feature is retained only if it yields repeatable out-of-sample improvement across multiple tectonic regions and historical cutoffs. Report coverage separately so a model is not rewarded merely for being evaluated on a small, selected set of well-studied earthquakes.

## References and data entry points

- USGS ComCat documentation: https://www.usgs.gov/programs/earthquake-hazards/anss-comprehensive-earthquake-catalog-comcat-documentation
- USGS data products: https://earthquake.usgs.gov/data/products/
- USGS finite-fault models: https://earthquake.usgs.gov/data/finitefault/
- USGS plate-motion FAQ / GPS explanation: https://www.usgs.gov/faqs/how-fast-do-tectonic-plates-move
- MORVEL reference: DeMets et al. (2010), *Geologically current plate motions*, https://doi.org/10.1111/j.1365-246X.2009.04491.x
- GPlates Web Service plate models: https://gwsdoc.gplates.org/models/
- EarthByte/GPlates data: https://www.earthbyte.org/gplates-2-1-software-and-data-sets/
- Coupling Cloud: https://couplingcloud.ucsd.edu/
- Coupling Cloud paper: https://doi.org/10.26464/epp2025014
- Coulomb parameter sensitivity: https://doi.org/10.1002/2012JB009860
- Coulomb stress uncertainty propagation: https://doi.org/10.1029/2011JB009121
