# VHCF Specimen Designer GUI Implementation

## Overview

The Sonotrode Designer GUI was extended toward the VHCF specimen-designer
workflow described in the project requirements. The implementation preserves
the existing STEP export, meshing, solver, geometry/material merge, and
analytics pipelines unless a change was required for the new VHCF data.

The implementation is organized into four functional areas:

1. Project setup and VHCF specimen parameters.
2. Gauge-volume selection and solver-set generation.
3. Stress parsing and analytics output.
4. Interactive result inspection and stress plots.

## Implemented Changes

### Project setup and state

- Added specimen-type selection to the setup UI.
- Added yield-strength input in MPa.
- Added active-scalar selection to the 3D results UI.
- Added `specimen_type`, `yield_strength`, and `gauge_bounds` to
  `ProjectSession`.
- Added signal bindings and state-change logging in the setup controller.
- Reset the new settings when project configuration is reset.

Relevant files:

- `GUI_code/scripts/MainWindow.ui`
- `GUI_code/scripts/app/state/project_session.py`
- `GUI_code/scripts/app/controllers/setup_controller.py`

### Gauge-section selection

- Added the Gauge Section semantic role.
- Added a PyVista bounding-box widget for selecting the stress-harvesting
  volume.
- Stored the selected bounds as
  `[xmin, xmax, ymin, ymax, zmin, zmax]`.
- Added a translucent gauge-volume overlay to the setup view.
- Propagated the bounds through mesh and solver workers.
- Selected mesh elements by centroid and generated:
  - `ELSET=GAUGE_VOL`
  - `NSET=GAUGE_VOL_NODES`

Relevant files:

- `GUI_code/scripts/app/controllers/setup_controller.py`
- `GUI_code/scripts/app/workers/mesh_worker.py`
- `GUI_code/scripts/app/workers/solver_worker.py`
- `GUI_code/scripts/meshing.py`

### Solver output and stress parsing

- Added CalculiX stress output for `GAUGE_VOL`.
- Added parsing of mesh element sets and FRD modal stress records.
- Added von Mises and maximum-principal-stress calculations.
- Added input-amplitude scaling, stress gain, and yield-status calculation.
- Added specimen-specific analytics schemas while preserving the existing
  geometry/material merge behavior.

Relevant files:

- `GUI_code/scripts/ccx_solver.py`
- `GUI_code/scripts/ccx_results_parser.py`
- `GUI_code/scripts/app/controllers/analytics_controller.py`

### 3D result inspection

- Added FRD stress fields to result meshes.
- Added displacement magnitude, displacement-Y, von Mises, and maximum
  principal stress fields.
- Added active-scalar selection for result rendering.
- Added right-click actions for stress paths and cross-sections.
- Added floating stress-plot popups with independent amplitude sliders.
- Added result mesh caching and stress-field mapping to mesh cells.

Relevant files:

- `GUI_code/scripts/modal_inspection_service.py`
- `GUI_code/scripts/app/controllers/results_controller.py`
- `GUI_code/scripts/app/widgets/stress_plot_popup.py`

## Current Specimen-Type Limitation

Filtering and mode-selection logic for the different specimen types has **not
been implemented**.

Although the GUI exposes longitudinal, disc, and flat/thin-walled specimen
options and the analytics schema can display specimen-specific columns, the
current mode-selection implementation uses the existing longitudinal
selection behavior for all specimen types.

Therefore, **only longitudinal specimens can currently be tested and
validated reliably**. Disc and flat/thin-walled specimen workflows are
placeholders for a later implementation phase and must not be interpreted as
having specimen-specific mode filtering.

The relevant result-mesh service currently handles FRD displacement and stress
fields, but it does not provide specimen-specific mode classification:

- `GUI_code/scripts/modal_inspection_service.py`

## Verification Performed

The implementation was checked using the `sonotrode_lab` environment:

- Compiled all project Python files successfully.
- Loaded the Qt application with the new controls.
- Verified specimen type and yield-strength state updates.
- Verified gauge-box initialization and bound persistence.
- Generated and inspected `GAUGE_VOL` and `GAUGE_VOL_NODES`.
- Verified solver stress-output generation.
- Parsed synthetic FRD stress data.
- Verified stress scaling and yield-status output.
- Verified dynamic analytics columns.
- Initialized the results QtInteractor and stress popup.
- Verified stress-popup amplitude scaling.
- Confirmed `git diff --check` passes.

Full production validation still requires a real CalculiX project containing
STEP, INP, DAT, and FRD files. Visible Matplotlib rendering should also be
checked in a normal desktop session because native offscreen rendering is
environment-dependent.

