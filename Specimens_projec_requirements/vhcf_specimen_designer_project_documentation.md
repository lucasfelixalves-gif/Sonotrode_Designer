# VHCF Specimen Designer: Project Documentation

## 1. Project Background and Objective

The existing `Sonotrode_Designer` repository (built on CalculiX, Gmsh, and Python) was originally designed to optimize ultrasonic horns by filtering for longitudinal resonance and maximizing tip displacement.

The goal of this project is to evolve this architecture into a comprehensive **Very High Cycle Fatigue (VHCF) Specimen Designer**. This new software will design and analyze specialized specimens (e.g., disc specimens for biaxial bending, flat thin-walled specimens for pure bending) operating in specific, non-longitudinal vibration modes. The core objective shifts from displacement maximization (an acoustics problem) to the coupled acoustics and precise extraction, processing, and visualization of localized stress within a defined gauge volume.

## 2. Core Project Requirements

### 2.1. Modulated Mode Filtering by Specimen Type

"Resonance" and "mode purity" possess completely different mathematical and kinematic definitions depending on the specimen geometry. The software must dynamically adjust its mode-filtering logic based on the user's selected specimen class.

* **GUI Integration (Setup Tab):** A new "Specimen Type" dropdown menu must be added with options for `Longitudinal Specimen`, `Disc Specimen (Biaxial)`, and `Flat/Thin-Walled Specimen`. This selection dictates the active mathematical mode-filtering logic applied by the parser.

* **Disc Specimens:** The algorithm must search for a biaxial bending mode, characterized by a circular vibration node ring and maximum out-of-plane displacement at the center. Mode purity is validated by confirming that the radial and circumferential stresses at the center of the lower face are equi-biaxial.

* **Flat/Thin-Walled Specimens:** The algorithm must isolate the primary bending mode while strictly penalizing parasitic, coupled torsional or lateral modes that would corrupt the intended stress state at the gauge section.

* **Longitudinal Specimens:** The algorithm can use the same filtering function already implemented.

### 2.2. Stress Gain ($C_s$) Calculation & Yield Criteria Validation

VHCF failure is driven by localized stress, whereas the ultrasonic booster outputs a nominal displacement amplitude. The software must bridge this gap by calculating the "Stress Gain" and ensuring the specimen remains in the macroscopic linear elastic regime.

* **Stress Gain (**$C_s$**):** The FEA pre-processor calculates the relative stress field pertaining to a free-free nodal analysis (the same type of step used for modal shape and displacement calculation). Because the calculated stresses are not physical (having only relative validity inside the simulation domain), they should be scaled based on a user input displacement at the booster connection. By extracting the average displacement at the booster connection and the corresponding stress values at the specified cross section, having the actual nominal booster displacement, the scaled stress values can be computed. The gain should be computed based on an average stress value, never based just on one node. Defining how to compute this average in each specimen type is crucial for valid analysis.

* **Yield Validation:** The post-processor calculates the theoretical maximum stress ($\sigma_{max}$), and evaluates this against the material's yield strength. If the stress exceeds the yield limit (e.g., plastic deformation occurs at the gauge center or connection threads), the linear scaling becomes invalid, resonance frequency shifts, and the software must flag the design as invalid.

* **GUI Integration:**

  * **Setup Tab:** Add a numerical input field for "Material Yield Strength ($\sigma_{yield}$ \[MPa\])" alongside the input amplitude.

  * **Analytics Tab:** The summary table must dynamically generate new columns based on the specimen type, including `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, and a visual `Yield_Status` (Green "Pass" / Red "Fail"). And alsp ditch columns not required by the specific node.

### 2.3. Interactive Stress Visualization

A single scalar value for maximum stress is insufficient for proper specimen validation. The designer must be able to visually verify that the stress peak is perfectly isolated within the intended gauge volume and that parasitic stress concentrations (e.g., at transition radii or mounting grips) are safely controlled.

* **3D Colormaps:** Utilizing visualization libraries (e.g., PyVista), the software will render the 3D deformed mesh overlaid with a continuous scalar stress colormap.

  * **GUI Integration (3D Results Tab):** A new dropdown menu must be added above the viewer to toggle the active scalar field between `Displacement Magnitude (U)`, `Displacement Y (U2)`, `Von Mises Stress`, and `Max Principal Stress`.

### 2.4. Interactive Path and Cross-Section Definition

To rigorously verify stress uniformity and locate stress concentrations, the designer must be able to probe the 3D mesh interactively. This is implemented via a **Right-Click Context Menu** directly within the 3D render window (Results Tab), presenting the user with two primary extraction tools: **Path** or **Plane**.

* **Define Stress Path (Line):**

  * **Interaction:** The viewer enters a "Point Picking" mode. The user left-clicks two points on the mesh (e.g., along the center axis or across a fillet) to define a line vector.

  * **Floating Plot:** A floating window (Matplotlib/PyQtGraph) spawns, displaying a 2D line plot of the sampled stress data (Y-axis: Stress \[MPa\] vs. X-axis: Distance along path \[mm\]).

* **Define Cross-Section (Plane):**

  * **Interaction:** Upon selecting this tool, the user is prompted to choose a Cartesian plane (`xOy`, `xOz`, or `yOz`). A visual plane representation appears in the 3D viewer. The user can then interactively drag or slide this plane along its normal axis using the cursor to intersect the specimen at the exact desired location (e.g., cutting through the narrowest point of the gauge section).

  * **Floating Plot:** A floating window spawns displaying a 2D cut view of the intersected cross-section. This acts as a contour map colored by the active stress field. To keep the visualization clean and focused purely on the stress distribution across the geometry, coordinate axes are hidden in this view.

* **Real-Time Updates:** For both the Path and Plane tools, the spawned floating windows are fully interactive and responsive. As the user scrubs the input amplitude slider or switches between vibration modes, the plots and cross-sectional colormaps update in real-time without requiring the user to close the 3D view or re-define the tool.

## 3. Expected Implementation Challenges & Required Architectural Shifts

### 3.1. From Displacement Output to Localized Stress Control

Designing a sonotrode requires maximizing tip displacement. Designing a VHCF specimen requires matching the displacement at the input ends while manipulating the geometry to achieve a localized, specific peak stress exactly in the center of the gauge section. The internal evaluation logic must be completely re-thought to prioritize spatial stress distribution over simple displacement amplitude.

### 3.2. Mesh Sensitivity and Stress Concentrations

Displacement fields are generally forgiving of coarse FEA meshes. Stress fields, however, are highly mesh-sensitive spatial derivatives of displacement. It’s important that the user performs comprehensive mesh convergence studies to ensure the harvested peak stresses are physical and not artificial singularities.

### 3.3. Extracting Targeted Element/Node Sets

The FEA solver (CalculiX) computes stress for the entire mesh, but the user only cares about specific regions (e.g., the center of a disc) to compute the true Stress Gain.

* **Challenge:** The software must include a spatial selection tool that allows the user to define a bounding box or slicing plane. The Python pre-processor must translate this into specific `ELSET` or `NSET` definitions in the solver's input deck, ensuring that the parsing module exclusively extracts and evaluates stress tensors from the intended areas, ignoring irrelevant edge artifacts.

* **GUI Solution (Setup Tab):** The semantic role assignment must be upgraded. Add a `Gauge Section (Stress Harvesting)` role. To select internal elements, introduce a Bounding Box or Slice Widget in the PyVista viewer. The user will drag the boundaries to envelope the narrowest part of the specimen, which the controller will then map to a dedicated `GAUGE_VOL` node/element set for the solver.