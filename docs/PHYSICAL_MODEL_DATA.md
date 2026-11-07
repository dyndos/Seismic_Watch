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

### Tier 1 — Plate kinematics (implemented as K1)

The research runner loads the versioned NNR-MORVEL56 Pacific-fixed angular-velocity table in `research/data/morvel56_pacific_fixed.json` and combines it with the repository's PB2002 boundary segments. It calculates east/north plate velocities, subtracts the two plates' vectors, and resolves the relative vector into local boundary-parallel and boundary-normal components.

PB2002 aliases are explicitly mapped where appropriate (`SO→SM`, `YA→YZ`). The aggregate PB2002 African plate code `AF` is not silently assigned to Nubia or Somalia; motion features for that code remain missing. The Pacific plate is represented by zero rotation in this Pacific-fixed frame. MORVEL is a long-term geological motion model, not a contemporaneous GNSS observation; covariance matrices and GNSS velocity fields are not yet ingested in K1.



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

### Tier 2 — Interseismic coupling and strain accumulation (implemented as K2 where coverage exists)

The runner can download the current Coupling Cloud archive with `--download-coupling`, read compatible NetCDF variables through xarray, and sample coupling/slip-deficit grids at the equal-area forecast-cell centres. Coupling is normalized to a 0–1 fraction; slip-deficit rates are used only when the NetCDF variable advertises a recognized rate unit (mm/yr, cm/yr or m/yr), converted to mm/yr. Missing values are never replaced with zero. The number of contributing models is recorded per cell.

K2 is marked unscored if there is insufficient compatible coupling coverage. The current Coupling Cloud aggregation is modern and post-dates some test cutoffs; K2 results are therefore classified as **retrospective modern-geophysics comparisons**, not strict as-of blind scores. This runner does not yet ingest independent GNSS station velocity/strain solutions or invert new locking models.



Where published geodetic models exist, collect:
- coupling/locking fraction on the plate interface;
- slip-deficit rate (relative convergence multiplied by inferred coupling, with the source model's exact definition retained);
- locking depth and downdip/updip limits;
- strain-rate tensor or principal strain axes;
- uncertainty and spatial resolution.

These features are much closer to fault loading than total plate mass. Coverage and methodology are heterogeneous, so keep model identity and provenance for every region. Do not treat missing coupling data as zero coupling.

Candidate source: Coupling Cloud is a curated, versioned aggregation of published megathrust coupling models, including coupling uncertainty, interface depth and slip-deficit-related variables. It covers selected subduction zones, not all tectonic settings; inspect the underlying publication and original model before use.

### Tier 3 — Source earthquake geometry and slip (implemented as K3 with explicit quality labels)

The runner prefers, in order: (1) a user-supplied source file in `research/data/finite_faults/{event_id}.json`; (2) an as-of USGS ComCat `finite-fault` product with product update time no later than the forecast cutoff, using its model length/width/orientation and uniform average slip derived from scalar moment where available; (3) an as-of moment tensor / focal mechanism converted to a magnitude-scaled rectangular source proxy using Wells–Coppersmith dimensions and scalar moment. The third case is labelled a proxy, not a measured finite fault.

When only a moment tensor is available, both nodal planes are retained as alternative source hypotheses. Their calculated stress fields are treated as an ensemble and are not added together. A full spatial subfault-slip distribution from FSP/Coulomb input files is not yet parsed by the default adapter; the current USGS finite-fault adapter uses model geometry with uniform average slip. The source quality label and product update time are saved with every forecast snapshot.



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

### Tier 5 — Stress-transfer calculation (implemented as K3)

K3 uses CUTDE half-space triangular dislocation elements to calculate a source-induced strain/stress tensor on the global equal-area grid and resolves it onto receiver-fault scenarios. It uses shear modulus 30 GPa, Poisson ratio 0.25, effective friction 0.4, a nominal receiver depth of 10 km, and a 2,500 km maximum source-to-receiver radius. Receiver-fault orientations are currently scenario ensembles inferred from PB2002 boundary orientation/type, not a complete mapped receiver-fault inventory. Positive ΔCFS is defined as promoting failure under the code's tension-positive convention.

The output includes median, 10th and 90th percentile ΔCFS across alternative source-plane and receiver-orientation scenarios. These are scenario spreads, not formal posterior confidence intervals. Sensitivity to elastic properties, receiver geometry, pore pressure, spatial grid resolution, and finite-fault slip distribution remains a research limitation.



Compute the source-induced stress-change tensor over a spatial grid from finite-fault slip, using a stated elastic or viscoelastic Earth model. Resolve that tensor onto candidate receiver-fault planes and calculate Coulomb failure stress change (ΔCFS / ΔCFF) using an explicitly documented sign convention and assumptions for friction and pore pressure.

Output should include:
- ΔCFS distribution per grid cell and receiver-fault scenario;
- positive/negative/near-zero stress regions;
- uncertainty range or ensemble spread;
- source model, receiver model, elastic assumptions and parameter values;
- cells where sign or magnitude is not robust across plausible models.

Static coseismic ΔCFS is not the whole stress history. The current K4 is a Dieterich (1994) rate-and-state response to a static stress step. It evaluates expected counts over forecast intervals using elapsed time since the triggering rupture and an explicit parameter ensemble (Aσ = 0.03, 0.1, 0.3 MPa; characteristic times = 30, 90, 365 days). These are sensitivity scenarios, not calibrated regional constants. K4 does **not** yet ingest measured afterslip, viscoelastic relaxation, fluid-pressure evolution or dynamic triggering. Those must remain separate future model components.

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
- K4 (current implementation): K3 + Dieterich time-dependent rate-and-state response to the coseismic ΔCFS step. Measured postseismic stress histories are not yet ingested.

For each step report both temporal and spatial skill, calibration and uncertainty. Run ablation tests that remove one feature family at a time. A feature is retained only if it yields repeatable out-of-sample improvement across multiple tectonic regions and historical cutoffs. Report coverage separately so a model is not rewarded merely for being evaluated on a small, selected set of well-studied earthquakes.

## References and data entry points

- USGS ComCat documentation: https://www.usgs.gov/programs/earthquake-hazards/anss-comprehensive-earthquake-catalog-comcat-documentation
- USGS data products: https://earthquake.usgs.gov/data/products/
- USGS finite-fault models: https://earthquake.usgs.gov/data/finitefault/
- USGS plate-motion FAQ / GPS explanation: https://www.usgs.gov/faqs/how-fast-do-tectonic-plates-move
- NNR-MORVEL56 reference: Argus et al. (2011), *Geologically current motion of 56 plates relative to the no-net-rotation reference frame*, Table 3, https://doi.org/10.1029/2011GC003751
- GPlates Web Service plate models: https://gwsdoc.gplates.org/models/
- EarthByte/GPlates data: https://www.earthbyte.org/gplates-2-1-software-and-data-sets/
- Coupling Cloud: https://couplingcloud.ucsd.edu/
- Coupling Cloud paper: Oryan et al. (2026), *The Coupling Cloud: A community database of megathrust kinematic coupling models*, https://doi.org/10.26443/seismica.v5i1.2314
- Wells & Coppersmith (1994), *New empirical relationships among magnitude, rupture length, rupture width, rupture area, and surface displacement*, https://doi.org/10.1785/BSSA0840040974
- Dieterich (1994), *A constitutive law for rate of earthquake production and its application to earthquake clustering*, https://doi.org/10.1029/93JB02581
- Coulomb parameter sensitivity: https://doi.org/10.1002/2012JB009860
- Coulomb stress uncertainty propagation: https://doi.org/10.1029/2011JB009121
