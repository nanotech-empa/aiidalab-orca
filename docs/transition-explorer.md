# Linked Dyson transitions, many-electron states and spectrum

After computing Dyson transitions, the spectrum includes an optional connected
state diagram. The same selection links the spectrum, exact state endpoints,
transition readout and any already retrieved individual-orbital preview.
Selection does not submit a calculation.
The source charge/spin sectors follow the selected Dyson result's original
state-node UUIDs, even when newer CASCI calculations exist for those sectors.

## Reading the diagram

The initial many-electron state is marked in gold at zero energy. Every other
state uses its stored total energy relative to that initial state. Removal
sectors are placed on the left, with charge q_initial+1 and N−1 electrons;
addition sectors appear on the right, with charge q_initial−1 and N+1
electrons. M in the footer denotes spin multiplicity, not spin projection.

Every bar stays at its **actual energy**. When roots are too close to resolve
vertically, they occupy separate horizontal slots within their charge/spin
sector. The display never averages the endpoints of a Dyson connection. The
original CASCI overview remains available above, where an averaged bar can
still summarize visually overlapping states.

The signed spectral poles are checked against the stored initial/final energies:

- Removal: `pole = E_initial − E_final`.
- Addition: `pole = E_final − E_initial`.

The spectrum's energy offset shifts the plotted poles, without changing the
many-electron state energies or the transition's energy difference. The selected
transition readout lists both quantities explicitly. The diagram draws only
transitions computed for the selected Dyson result; other calculated states
remain visible as context.

## Connections and spin weights

Initially, only the selected transition is connected. **All in spectrum** shows
the computed connections matching the displayed spectral range and branch;
**No connections** leaves the state diagram visible. A minimum-weight filter
reduces clutter in the All mode. Selected transitions remain visible even if
they lie below that threshold.

Connector colour varies linearly from **opaque black at zero Dyson weight** to
blue at the maximum weight in the full computed transition table. The legend
records that maximum. Selecting or filtering transitions does not rescale the
colours. Gold outlines indicate selection independently of the weight colour.
The colour represents a transition's pole weight, rather than the combined
height of an overlapping broadened peak.

The selected-transition readout shows the raw highest-M_S component weight Z,
the unpolarized Clebsch–Gordan-derived spin-multiplet factor F, and the weight W
used by the chosen convention:

- Unpolarized: `W = Z × F`.
- Highest-M_S component: `W = Z`.

F is a multiplet conversion factor derived from squared CG coefficients and
the projection sums/average, **not an individual signed CG amplitude**. Existing
backend conventions are reused without changing the electronic states or
applying the spin factor a second time.

## Selecting transitions

- Click a connector or final-state bar to select its transition.
- Click a spectral peak region to select its nearby computed poles. An
  unresolved region can select several roots, including a zero-weight pole;
  their exact energies and individual weights remain in the readout.
- Drag across the spectrum to set an energy window and select poles within it.
  Bounds round outwards to the editable 0.01 eV grid, preserving the region
  covered by a narrow drag. The same window is used by the existing blend
  controls.
- Use the selection list to inspect one member of an unresolved peak.
- **Use selection for cubes / maps** transfers the selected transition IDs to
  the existing property controls. Missing amplitude cubes are reported; they
  are generated only through the normal reviewed CalcJob submission.

If one selected transition has a retrieved amplitude cube, that preview is
selected automatically. Otherwise the app explicitly reports that it is
unavailable; no remote computation starts. Multiple selected transitions can
be used for an incoherent intensity blend. The spectral JSON download records
the selected IDs along with the existing numerical spectrum settings.

Charts can be shown side by side or stacked and wrap on narrow screens. The
interactive SVGs use anywidget inside ipywidgets, with packaged JavaScript,
keyboard-selectable targets and no external JavaScript/CDN dependency.

## Validation

Focused regressions cover state UUID/root identity, energy-sign checks,
unresolved peak picking, exact nearby state energies, black/clickable dark
connectors, stable weight colours across filters, raw versus unpolarized
readouts, and propagation of a rounded energy-window selection without
submitting jobs. Real browser tests exercise clicks in both directions,
selection of dark/overlapping transitions, drag selection, cached orbital
previews and transfer to the map/cube controls using the saved NO example.
