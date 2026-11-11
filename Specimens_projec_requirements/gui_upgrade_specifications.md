# GUI Upgrade Specifications: VHCF Specimen Designer

To accommodate the transition from the displacement-focused `Sonotrode_Designer` to the stress-focused **VHCF Specimen Designer**, the graphical user interface (GUI) requires significant functional additions. Based on the MVC architecture of the application, these changes will primarily impact the view (`MainWindow.ui`) and the controllers (`setup_controller.py` and `results_controller.py`).

Below is a detailed breakdown of the required changes, categorized by the main application tabs.

## 1. Setup Tab (Pre-Processing & Configuration)

The Setup tab currently handles project initialization, STEP file loading, and basic face selection for tip/base boundaries. It must be expanded to capture the new physical and analytical constraints of VHCF testing.

### 1.1. Specimen Type Selector

* **UI Addition:** A new dropdown menu (ComboBox) labeled **"Specimen Type"**.

* **Options:** `Longitudinal Specimen`, `Disc Specimen (Biaxial)`, `Flat/Thin-Walled Specimen`.

* **Functionality:** This selection must be saved to the `project_session.py` state. It will dynamically dictate which mathematical mode-filtering logic `ccx_results_parser.py` uses when the solver finishes.

### 1.2. Yield Strength & Amplitude Inputs

* **UI Addition:** Alongside the existing "Assign input amplitude in µm" field, add a new numerical input field (SpinBox) for **"Material Yield Strength (**$\sigma_{yield}$ **\[MPa\])"**.

* **Functionality:** This value will be passed to the analytics controller to validate the scaled stress fields and flag configurations that exceed the elastic limit.

### 1.3. Gauge Section / Stress Volume Selection

* **Current State:** The PyVista viewer allows users to pick boundary faces and assign semantic roles (e.g., `YMAX`, `YMIN`).

* **Required Change:** The user must be able to select the *internal volume* or *specific cross-section* where the average stress will be calculated for the Stress Gain ($C_s$).

* **Implementation Strategy:**

  * Add a new semantic role to the dropdown: `Gauge Section (Stress Harvesting)`.

  * Because internal elements cannot be selected just by clicking the outer surface, the selecting tool must be upgraded to include a **Bounding Box Widget** or **Slice Widget**.

  * The user will visually drag the boundaries of this box over the narrowest part of the specimen. The controller will then extract all mesh nodes/elements within this spatial envelope and assign them to a dedicated `ELSET` or `NSET` (e.g., `GAUGE_VOL`) in the CalculiX `.inp` file.

## 2. Analytics Tab (Summary & Validation)

While the prompt focuses on Setup and Results, the Analytics data table must reflect the new calculations to bridge the two tabs. This is taken care of in the script `ccx_results_parser.py`

The summary columns generated for the Analytics tab changes based on the type of specimen selected. This will need to be considered during implementation because each specimen type has it’s own performance metrics. 

* **New Columns:**

  * `Max_Stress [MPa]` (Scaled based on input amplitude).

  * `Stress_Gain [MPa/µm]`.

  * `Yield_Status` (Visual indicator: Green "Pass" or Red "Fail" if $\sigma_{max} > \sigma_{yield}$).

## 3. 3D Results Tab (Post-Processing & Visualization)

The 3D Results tab currently animates FRD displacement data. It must be fundamentally upgraded to support stress visualization and interactive data extraction.

### 3.1. Stress Colormap Rendering

* **UI Addition:** A dropdown menu above the 3D viewer to select the active scalar field.

* **Options:** `Displacement Magnitude (U)`, `Displacement Y (U2)`, `Von Mises Stress`, `Max Principal Stress`.

* **Functionality:** The `modal_inspection_service.py` must be updated to parse stress tensors from the `.frd` file and pass them to PyVista for mapping onto the deformed mesh.

### 3.2. Interactive Path and Cross-Section Definition

* **UI Addition:** Implement a **Right-Click Context Menu** directly within the PyVista 3D render window.

* **Context Menu Options:**

  * `Define Stress Path (Line)`

  * `Define Cross-Section (Plane)`

* **Implementation Strategy:**

  * When the user selects `Define Stress Path`, the viewer enters a "Point Picking" mode. The user left-clicks two points on the mesh (e.g., Point A to Point B).

  * PyVista will generate a geometric line between these points and sample the interpolated stress values from the mesh elements along that line.

  * When the user selects `Define Cross-Section (Plane)`, the viewer enters a “Plane Mode” where the user must define which of the three cartesian planes he wants to use. After selection, the plane will intersect the specimen and the stress distribution along the intersected cross section will be considered. 

### 3.3. Floating Stress Distribution Plot

* **UI Addition:** A popup/floating Qt Window that is instantiated when a path or plane is defined.

* **Functionality:**

  * This floating window will contain a Matplotlib or PyQtGraph canvas.

  * It will plot the extracted stress data (Y-axis: Stress \[MPa\], X-axis: Distance along path \[mm\]).

  * **Interactivity:** At the bottom of the floating Qt window, there should be a slider for the input amplitude. This should work only for the purposed of this representation without altering the rest of the session's data. As the user moves the slider for the input amplitude, the floating plot must update in real-time, allowing the designer to strictly verify stress uniformity and peak locations without closing the 3D view. If the user wishes to change the path or the plane, he should either add another plane and (consequentely) create another pop-up. These floating windows should be minimizable and should not cause the UI to freeze. 
  