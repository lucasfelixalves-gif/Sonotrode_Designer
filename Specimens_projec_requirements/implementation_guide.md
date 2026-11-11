# VHCF Specimen Designer: Implementation Guide

This document serves as the master blueprint for upgrading the `Sonotrode_Designer` into the **VHCF Specimen Designer**.

> **⚠️ CRITICAL AI DIRECTIVE: STRICT PRESERVATION OF INDEPENDENT BEHAVIORS**
> Do not alter any behavior, function, or script that is not strictly related to the changes requested in this document. Existing pipelines—especially the SolidWorks STEP export, the general meshing pipeline, and the logic that merges geometrical parameters into the final pandas DataFrame—must remain untouched to preserve application stability. Only modify what is strictly necessary to implement the new specimen types and their evaluations.

**Agent Instructions:** Execute these phases sequentially. Do not proceed to the next phase until the current phase is fully implemented, debugged, and verified. Follow the existing MVC architecture. If a new UI component is needed, update `MainWindow.ui` first, then bind it in the respective controller.

## Phase 1: State Management & Basic Setup UI

**Goal:** Expand the UI to capture new project constraints (Specimen Type, Yield Strength) and persist them in the application state.

### 1.1. Update the Model/State (`scripts/app/state/project_session.py`)

* **Action:** Add properties to `ProjectSession` to store:
  * `specimen_type` (String: default `'Longitudinal'`)
  * `yield_strength` (Float: default `300.0` MPa)
* **Verification:** Ensure these variables reset properly when a new project is loaded.

### 1.2. Update the View (`scripts/MainWindow.ui`)

* **Action:** Open Qt Designer and add the following to the Setup Tab:
  * A `QComboBox` named `combo_specimen_type` with items: `Longitudinal Specimen`, `Disc Specimen (Biaxial)`, `Flat/Thin-Walled Specimen`.
  * A `QDoubleSpinBox` named `spin_yield_strength` (Range: 0-2000, Suffix: " MPa").
* **Action:** Add a dropdown to the 3D Results Tab:
  * A `QComboBox` named `combo_active_scalar` with items: `Displacement Magnitude (U)`, `Displacement Y (U2)`, `Von Mises Stress`, `Max Principal Stress`.

### 1.3. Update the Controller (`scripts/app/controllers/setup_controller.py`)

* **Action:** In `__init__`, bind the signals from `combo_specimen_type` and `spin_yield_strength` to update their respective variables in `self.session`.
* **Debug/Check:** Add a print statement or logging to terminal when these values change to verify the UI is successfully updating the state.

## Phase 2: Spatial Selection & Gauge Volume Definition

**Goal:** Allow the user to define the stress-harvesting area using a Bounding Box in PyVista, and pass this selection to the meshing engine.

### 2.1. Update Semantic Roles (`scripts/app/controllers/setup_controller.py`)

* **Action:** Add `"Gauge Section (Stress Harvesting)"` to the existing semantic role dropdown.

### 2.2. Implement Bounding Box Widget (`scripts/modal_inspection_service.py` or new 3D utility)

* **Action:** When the user selects the "Gauge Section" role, activate PyVista's `add_box_widget()` on the setup mesh.
* **Action:** Create a callback function that fires when the user confirms the box. This function must:
  1. Extract the spatial bounds `[xmin, xmax, ymin, ymax, zmin, zmax]`.
  2. Save these bounds to `self.session.gauge_bounds`.
* **Debug/Check:** Render a translucent geometric box representing the extracted bounds over the mesh to visually confirm the coordinates are correct.

### 2.3. Update Solver Input Generation (`scripts/meshing.py` & `scripts/ccx_solver.py`)

* **Action:** Modify the `meshing.py` script. If `gauge_bounds` exist in the session, extract all elements whose centroids fall within these bounds.
* **Action:** Write these elements into a new `ELSET=GAUGE_VOL` and their corresponding nodes to `NSET=GAUGE_VOL_NODES` inside the `.inp` file.
* **Verification:** Open the generated `.inp` file manually in a text editor and verify the `GAUGE_VOL` block exists and contains elements.

## Phase 3: Analytics Tab & Dynamic Columns

**Goal:** Adapt the results table dynamically based on the selected specimen type and compute scaled stresses.

### 3.1. Dynamic Table Model (`scripts/analytics_table_model.py` & `scripts/ccx_results_parser.py`)

* **Action:** Update the parser and the table model to generate specific output headers depending on the selected `specimen_type`.
* **Critical Note:** The geometrical parameters from the Excel workbook are appended automatically by the existing `df_merged` logic. Do not interfere with that merge operation. Only update the simulation metric headers.
* **Logic:** Define the `SUMMARY_COLUMNS` lists as follows:
  * **Common Base (Always Included):** `Model_name`, `Number_of_nodes`, `Mode_Index`, `Frequency_Hz`
  * **If `Longitudinal Specimen`:**
    * Add: `Base_Disp_µm`, `Tip_Disp_µm`, `Displacement_Ratio`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`
  * **If `Disc Specimen (Biaxial)`:**
    * Add: `Base_Disp_µm`, `Center_Disp_Z_µm`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`
  * **If `Flat/Thin-Walled Specimen`:**
    * Add: `Base_Disp_µm`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`

### 3.2. Data Parsing & Math Logic (`scripts/ccx_results_parser.py`)

* **Action:** Refactor the `select_longitudinal_mode` function into a main router function: `parse_and_select_mode(specimen_type)`.
* **Action:** Implement branching logic (Iterative - start simple, refine later):
  * **Longitudinal:** Keep existing mode filtering. Compute stresses using `GAUGE_VOL`.
  * **Disc:** Filter for modes where out-of-plane displacement (Z) is max at the center. Extract stress from `GAUGE_VOL`.
  * **Flat:** Filter for primary bending (Y-displacement dominant, minimal X/Z twist). Extract stress from `GAUGE_VOL`.
* **Action:** Compute Scaling:
  * Read user input amplitude.
  * $C_s$ = (Average Stress in `GAUGE_VOL`) / (Average Displacement at Booster NSET).
  * Compute scaled `Max_Stress`.
  * Set `Yield_Status` to `"Pass"` if `Max_Stress` < `session.yield_strength`, else `"Fail"`.
* **Debug/Check:** Run a batch solve. Check the Python console for parsing errors. Verify the Pandas dataframe correctly populated the specific new columns (and successfully merged the geometry columns) before it hits the Qt Table.

## Phase 4: Static 3D Interactions & Floating Plots

**Goal:** Implement the Right-Click context menu to extract 1D/2D stress data and pass it to independent, floating PyQt windows.

### 4.1. Context Menu Setup (`scripts/app/controllers/results_controller.py`)

* **Action:** Intercept right-clicks on the PyVista widget. Spawn a `QMenu` with two actions: `Define Stress Path (Line)` and `Define Cross-Section (Plane)`.

### 4.2. Path Extraction Logic (PyVista)

* **Action:** If `Define Stress Path` is clicked, enable PyVista's point-picking (`enable_point_picking`).
* **Action:** Once two points are picked, use PyVista's `pyvista.Line(point_a, point_b, resolution=100)`.
* **Action:** Run `sampled_data = mesh.sample(line)`. Extract the 1D array of the active scalar (e.g., Von Mises) and the distance array.

### 4.3. Plane Extraction Logic (PyVista)

* **Action:** If `Define Cross-Section` is clicked, prompt the user for an axis (X, Y, or Z) and an origin coordinate.
* **Action:** Run `sliced_mesh = mesh.slice(normal=axis, origin=coord)`.
* **Action:** Extract the 2D surface data and its associated scalar array.

### 4.4. Floating Widgets (`scripts/app/widgets/stress_plot_popup.py`)

* **Action:** Create a new Qt Widget class `StressPlotPopup(QWidget)`.
* **UI Components:** A Matplotlib canvas and a `QSlider` at the bottom (for input amplitude).
* **Initialization:** The class must accept the *static* arrays extracted in Steps 4.2 or 4.3.
* **Slider Interactivity:** When the slider moves, it simply multiplies the static stress array by the new scaling factor and triggers a canvas redraw. It does *not* query PyVista.
* **Debug/Check:** Open multiple popups (one path, one plane). Move the sliders independently. Verify that the main UI does not freeze and the 3D window remains fully responsive.