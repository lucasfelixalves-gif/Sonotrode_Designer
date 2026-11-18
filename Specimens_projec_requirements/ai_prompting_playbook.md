# AI Prompting Playbook: VHCF Specimen Designer

This guide provides step-by-step instructions on how you (the human engineer) should prompt and guide your AI coding agent (e.g., GitHub Copilot) through the implementation phases.

## 🥇 Golden Rules for Guiding the AI

1. **Never dump the whole project:** Do not paste the entire implementation guide or project documentation into the chat at once. The AI will lose focus and hallucinate.
2. **Control the Context (Pinning):** Always explicitly open/pin the files the AI needs to read or edit for a specific prompt. If a file isn't relevant to the current task, close it.
3. **Isolate and Sandbox:** For complex 3D (PyVista) or data logic, have the AI write a standalone test script first. Only ask it to integrate the code into your MVC architecture once you verify the sandbox works.
4. **The "Do Not Touch" Command:** Frequently remind the AI: *"Do not alter any existing data merging logic or solidworks pipelines."*

---

## 🛠️ Phase 1: State Management & Basic Setup UI

**Your Goal:** Get the new UI elements rendered and connected to the session state safely.

* **Step 1: The UI Rendering**
  * **Files to open:** `scripts/MainWindow.ui` (if the AI can read XML/UI files) or just prompt for PyQt6 code to add. *(Note: It's often safer for you to add these manually in Qt Designer, then have the AI write the controller logic).*
* **Step 2: State Update Prompt**
  * **Files to open:** `project_session.py`, `setup_controller.py`
  * **Prompt to use:** *"Add a QComboBox named `combo_specimen_type` and a QDoubleSpinBox named `spin_yield_strength` to my UI. Please update `ProjectSession` in `project_session.py` to store these variables (defaults: 'Longitudinal', 300.0). Then, update `setup_controller.py` to bind these UI elements to update the session state when changed. Add print statements so I can verify."*
* **Verification:** Run `main.py`. Change the dropdown. Look at the terminal to confirm the state updated.

---

## 📦 Phase 2: Spatial Selection (Bounding Box)

**Your Goal:** Implement the PyVista bounding box without breaking the main rendering loop.

* **Step 1: Sandbox Prompt**
  * **Files to open:** None (Blank script).
  * **Prompt to use:** *"Write a standalone PyVista script that loads a dummy 3D mesh and adds a bounding box widget (`add_box_widget`). When the user confirms the box, extract the spatial bounds `[xmin, xmax, ymin, ymax, zmin, zmax]` and print them."*
  * **Verification:** Run the sandbox script. Make sure the box is draggable and prints correct coordinates.
* **Step 2: Integration Prompt**
  * **Files to open:** `setup_controller.py`, `meshing.py`
  * **Prompt to use:** *"Now integrate this bounding box logic into `setup_controller.py` when the 'Gauge Section' semantic role is selected. Save the bounds to `self.session.gauge_bounds`. Then, update `meshing.py` to filter elements within these bounds and write them to an `ELSET=GAUGE_VOL` in the `.inp` file."*

---

## 📊 Phase 3: Analytics Tab & Dynamic Columns

**Your Goal:** Update the Pandas/Qt table headers dynamically without losing the geometrical variables.

* **Step 1: The UI and Logic Prompt**
  * **Files to open:** `analytics_table_model.py`, `ccx_results_parser.py`
  * **Prompt to use:** *"I need to dynamically generate the simulation summary columns based on `session.specimen_type`. CRITICAL: Do not touch or overwrite the logic that merges geometrical columns into the dataframe. Only alter the simulation metric headers. Here is the mapping: [Paste the header mappings from the Implementation Guide for Longitudinal, Disc, and Flat]. Please update `ccx_results_parser.py` to route to different parsing functions based on this type."*
* **Verification:** Run a batch solve. Check the output Excel or table to ensure the new columns appear and the old geometry columns (like `horn_height`) are still safely merged at the end.

---

## 🎯 Phase 4: Static 3D Interactions & Floating Plots

**Your Goal:** Implement the independent popup plots without freezing the PyVista viewer.

* **Step 1: The UI Popup Sandbox Prompt**
  * **Files to open:** None (New file: `stress_plot_popup.py`)
  * **Prompt to use:** *"Write a standalone PySide6 widget class called `StressPlotPopup`. It should contain a Matplotlib canvas and a QSlider at the bottom. The constructor should accept a static 1D numpy array of stress values and a 1D array of distances. When the slider moves, it should multiply the stress array by the slider's value and redraw the plot. Do not include any 3D or PyVista code in this file."*
  * **Verification:** Run this script with dummy `[1, 2, 3]` data and ensure the slider smoothly scales the graph.
* **Step 2: The Extraction Integration Prompt**
  * **Files to open:** `results_controller.py`, `modal_inspection_service.py`
  * **Prompt to use:** *"I want to add a Right-Click context menu to my PyVista widget in `results_controller.py` with two options: 'Path' and 'Plane'. If 'Path' is clicked, enable point picking, draw a line between the two points, run `mesh.sample(line)`, extract the active scalar array, and spawn the `StressPlotPopup` we just made using that static data."*