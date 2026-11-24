# Phase 4: 3D Stress Colormaps, Static Probing & Floating Stress Plots

> **⚠️ CRITICAL AI DIRECTIVE: STRICT PRESERVATION OF INDEPENDENT BEHAVIORS**
>
> 1. **DO NOT ALTER EXISTING PIPELINES:** Do not modify SolidWorks STEP export, Gmsh meshing, CalculiX solver execution, mode-selection logic (`select_longitudinal_mode`), or the Analytics table / Excel geometry merge logic.
>
> 2. **PRESERVE EXISTING 3D VIEWER CONTROLS:** Existing mode navigation (`< Previous Mode`, `Next Mode >`), the deformation warp slider (`Deformation scale`), and the modal animation loop (`Make it move!`) must continue working seamlessly across all scalar fields.
>
> 3. **STATIC EXTRACTION ARCHITECTURE:** Do **not** bind live 3D plane-dragging events to real-time Matplotlib redraws. All 1D paths and 2D cross-sections are extracted **once** at definition time as static NumPy arrays and passed to standalone, decoupled floating PyQt windows (`StressPlotPopup`).

## 1. Objective & Detailed Intended Behavior

A single scalar metric (`Max_Stress [MPa]`) in the Analytics table is insufficient to validate a VHCF specimen design: the engineer must visually verify that the peak stress is cleanly localized in the center of the gauge section and that parasitic stress concentrations (e.g., at fillets, clamping holes, or threads) remain safely below critical levels.

Phase 4 upgrades the **3D Results Tab** (`modal_inspection_service.py` and `results_controller.py`) and introduces a dedicated floating widget (`scripts/app/widgets/stress_plot_popup.py`) to provide:

1. **Multi-Field 3D Colormap Switching** on the deformed 3D mesh.
2. **Right-Click Context Menu Probing** in the 3D render window (`Define Stress Path (Line)` and `Define Cross-Section (Plane)`).
3. **Independent, Minimizable Floating Stress Plots** with local amplitude sliders that scale static stress arrays in real time without touching the 3D viewer or mutating `ProjectSession` state.

### 1.1. 3D Stress & Displacement Colormap Rendering

1. **Scalar Field Registration (`modal_inspection_service.py`):**
   * When loading a solved model's `.frd` and `.inp` files for a given `mode_index`, attach four named point-data scalar arrays onto the PyVista `UnstructuredGrid` mesh:
     * `"Displacement Magnitude (U)"`: $\|\mathbf{u}_{\text{raw}}\| = \sqrt{u_x^2 + u_y^2 + u_z^2}$ (in $\text{mm}$, or scaled to $\mu\text{m}$ consistently with existing viewer conventions—document and display exact units on the colorbar title).
     * `"Displacement Y (U2)"`: $u_{y,\text{raw}}$.
     * `"Von Mises Stress"`: Physical Von Mises stress $\sigma_{\text{vM}}^{(k)} = \alpha \cdot \sigma_{\text{vM, raw}}^{(k)}$ in **$\text{MPa}$** (using the linear elastic scaling factor $\alpha = A_{\text{input, }\mu\text{m}} / U_{\text{base, }\mu\text{m}}$ from Phase 3; if base displacement is zero or missing, fall back to raw $\text{MPa}$ and label colorbar accordingly).
     * `"Max Principal Stress"`: Physical maximum principal stress $\sigma_1^{(k)} = \alpha \cdot \sigma_{1, \text{raw}}^{(k)}$ in **$\text{MPa}$**.

2. **Interactive Scalar Toggle (`combo_active_scalar`):**
   * Changing `combo_active_scalar` in the 3D Results Tab immediately updates the active scalar array and scalar bar title on the rendered PyVista mesh **without resetting the camera angle** and **without breaking the current deformation warp scale or animation state**.
   * If a model was only `Meshed` (no `.frd` stress data) or lacks stress blocks, selecting a stress scalar logs a clear status message in the terminal and safely falls back to `"Displacement Magnitude (U)"` instead of crashing.

### 1.2. Right-Click Context Menu in the 3D Viewport

1. **Context Menu Trigger:**
   * Right-clicking inside the 3D Results PyVista `QtInteractor` spawns a `QMenu` at the cursor position with two actions:
     * `Define Stress Path (Line)`
     * `Define Cross-Section (Plane)`
   * *(Guard)*: If no solved mesh is currently loaded in the 3D Results viewport, the menu items are either disabled or show a status message `"Load a solved 3D result before probing stress."`
   * *(Animation Guard)*: If `"Make it move!"` modal animation is actively running when the user triggers a probe, pause animation cleanly before picking/slicing so VTK point coordinates remain deterministic.

### 1.3. Tool A: `Define Stress Path (Line)`

1. **Two-Point Picking Interaction:**
   * Selecting `Define Stress Path (Line)` puts the 3D Results viewer into a temporary 2-click point-picking state (updating the status label/terminal with instructions: `"Click Point A on the 3D mesh..."`, then `"Click Point B on the 3D mesh..."`).
   * **Crucial Coordinate Consistency:** Picking must query coordinates on the **undeformed base mesh** (or apply inverse warp) so the sampled `pyvista.Line(point_a, point_b, resolution=100)` intersects the mesh interior cleanly even when the visual warp slider is exaggerated!
   * Visual feedback: Render small spheres at Point A and Point B and a line segment connecting them on the 3D mesh (under a named actor e.g. `"probe_path_overlay"`), then automatically exit point-picking mode after the 2nd click so normal 3D camera rotation resumes immediately.

2. **1D Line Sampling (`mesh.sample`):**
   * Generate `line = pyvista.Line(point_a, point_b, resolution=100)` (101 sample points).
   * Compute Euclidean distance along the path from Point A:
     $$s_i = \|\mathbf{p}_i - \mathbf{p}_A\|_2 \quad [\text{mm}], \quad i = 0, \dots, 100$$
   * Run `sampled = base_mesh.sample(line)` and extract the active stress array (defaulting to `"Von Mises Stress"` in $\text{MPa}$ if a displacement scalar is currently selected, or using the active scalar if it is already a stress field—always ensuring the popup plots physical stress in $\text{MPa}$).
   * Filter out any exterior sample points where `vtkValidPointMask == 0` (if the line passes through a hole or notch) or replace exterior points with `np.nan` so the Matplotlib curve shows a clean physical break across holes rather than artificial zeros.

3. **Spawn Floating Window:**
   * Instantiate and show a new, independent `StressPlotPopup` in `"path"` mode, passing:
     * `distances_mm` (1D `np.ndarray`)
     * `base_stress_mpa` (1D `np.ndarray`, corresponding to nominal session amplitude $A_{\text{nominal}}$)
     * `nominal_amplitude_um` (float, from `Setup` tab)
     * `yield_strength_mpa` (float, from `self.session.yield_strength`, drawn as an optional horizontal dashed reference line if within plot range)
     * `title` (e.g., `"Stress Path — <Model_name> (Mode <N>)"`)

### 1.4. Tool B: `Define Cross-Section (Plane)`

1. **Cartesian Plane & Coordinate Dialog:**
   * Selecting `Define Cross-Section (Plane)` opens a lightweight modal `QDialog` showing the loaded mesh's bounding box `[xmin..xmax]`, `[ymin..ymax]`, `[zmin..zmax]` and prompting the user to select:
     * **Plane Orientation:** `xOy (Normal: Z)`, `xOz (Normal: Y)`, or `yOz (Normal: X)`.
     * **Slice Coordinate [mm]:** A `QDoubleSpinBox` bounded by the mesh's min/max along the chosen normal axis, initialized to the midpoint of that axis (e.g., center of the gauge section).

2. **2D Plane Slicing (`mesh.slice`):**
   * Run `sliced_mesh = base_mesh.slice(normal=normal_vec, origin=origin_coord)`.
   * Verify `sliced_mesh.n_points > 0` and `sliced_mesh.n_cells > 0` (if empty, warn the user that the plane missed the geometry).
   * Render a subtle translucent plane/outline indicator (`name="probe_plane_overlay"`) on the 3D viewer to show where the cut was taken.

3. **2D Contour Map Floating Window:**
   * Project the 3D slice vertices onto the two in-plane Cartesian coordinates $(u, v)$ (e.g., $(x, y)$ for `xOy`, $(x, z)$ for `xOz`, $(y, z)$ for `yOz`) and extract the slice triangle connectivity (`sliced_mesh.triangulate()`) along with the physical stress array ($\text{MPa}$).
   * Instantiate and show a new, independent `StressPlotPopup` in `"plane"` mode:
     * Renders a filled 2D stress contour/tricontour map (`ax.tricontourf` / `ax.tripcolor`) with a colorbar labeled `"Stress [MPa]"`.
     * **Clean Visual Specification:** Per project requirements, **coordinate axes, ticks, and spines are hidden** (`ax.set_axis_off()`) with `ax.set_aspect("equal")` so the designer sees a pure, uncluttered cross-sectional stress map.

### 1.5. Floating Window Behavior (`StressPlotPopup`)

1. **Window Lifecycle & Multi-Window Support:**
   * `StressPlotPopup` inherits from `QWidget` with `Qt.Window` window flags so it floats independently above the main window, has standard **minimize / maximize / close** buttons, and does **not** block interaction with the main 3D window.
   * Store active popup references in a list on `ResultsController` (`self._plot_popups: list[StressPlotPopup]`) with cleanup on `destroyed` signal so Python's garbage collector never prematurely closes an open window, and users can open multiple popups side-by-side (e.g., longitudinal path A–A, transversal path B–B, and cross-section cut) to compare them.

2. **Local Amplitude Slider (Zero Coupling to `ProjectSession`):**
   * At the bottom of `StressPlotPopup`, provide a horizontal `QSlider` (and synchronized numeric readout label) for **Simulated Excitation Amplitude [$\mu\text{m}$]** (e.g., range `1.0 µm` to `100.0 µm`, initialized to `nominal_amplitude_um`).
   * Moving the slider computes:
     $$\sigma_{\text{display}}(A_{\text{slider}}) = \sigma_{\text{base}} \times \left(\frac{A_{\text{slider}}}{A_{\text{nominal}}}\right)$$
   * Redraws **only** the local Matplotlib canvas (`canvas.draw_idle()`). It **never** calls PyVista, **never** re-reads `.frd` files, and **never** mutates `self.session` or the Analytics table.

## 2. Required AI Agent Skills & Domain Knowledge

Before modifying the codebase, the AI agent executing this phase must apply the following technical skills:

* **PyVista Mesh Data & Spatial Filters:**
  * Assigning multiple named point-data arrays (`grid.point_data["Von Mises Stress"] = ...`) and switching `mesh.set_active_scalars(name)` without recreating the VTK actor or resetting the camera.
  * Using `pyvista.Line(p1, p2, resolution=100)` + `mesh.sample(line)` (including checking `vtkValidPointMask`) for 1D probing.
  * Using `mesh.slice(normal=..., origin=...)` + `.triangulate()` to extract 2D triangulated cross-sections from 3D tetrahedral `UnstructuredGrid` meshes.
* **PyVista Point Picking (`enable_point_picking` / `enable_surface_point_picking`):**
  * Implementing a two-click state machine in `QtInteractor` and cleanly calling `plotter.disable_picking()` after the second point is captured so right-click context menus and left-click camera orbit are never permanently hijacked.
* **Matplotlib Embedded in PySide6 (`FigureCanvasQTAgg`):**
  * Building a responsive standalone `QWidget` popup with `FigureCanvasQTAgg`, `ax.tricontourf` for unstructured 2D slices, and fast `canvas.draw_idle()` updates driven by a `QSlider`.
* **Qt Context Menus & Window Memory Management:**
  * Intercepting right-click events on `QtInteractor` (via `customContextMenuRequested` or VTK `RightButtonPressEvent` observer) without interfering with VTK right-button zoom drags (only spawning the menu on short clicks without camera drag).
  * Managing child window lifetimes in PySide6 (`Qt.WA_DeleteOnClose` + signal cleanup in controller list).

## 3. Step-by-Step Implementation Plan

Execute these steps in exact sequential order.

### Step 4.1: Upgrade `scripts/modal_inspection_service.py` for Multi-Field Stress Meshes

* **Target File:** `scripts/modal_inspection_service.py`
* **Action:**
  1. Reuse the `.frd` stress parser and continuum mechanics helpers from `ccx_results_parser.py` (`parse_frd_stress_for_mode`, `compute_von_mises`, `compute_max_principal_stress`).
  2. When building or caching the PyVista `UnstructuredGrid` for a solved model and `mode_index`:
     * Map nodal stress tensors from the `.frd` file onto the exact INP node ordering of the grid.
     * Compute the physical scaling factor $\alpha = A_{\text{input, }\mu\text{m}} / U_{\text{base, }\mu\text{m}}$ (using `YMIN` mean axial displacement from the `.frd` displacement field and the active input amplitude).
     * Populate `grid.point_data` with all four fields:
       * `"Displacement Magnitude (U)"`
       * `"Displacement Y (U2)"`
       * `"Von Mises Stress"` (in $\text{MPa}$)
       * `"Max Principal Stress"` (in $\text{MPa}$)
     * Ensure an undeformed copy (or undeformed `points` array) is retained so 1D/2D spatial probing always samples the true physical geometry rather than an exaggerated visual warp.
  3. Add pure, testable spatial extraction functions to `modal_inspection_service.py`:
     * `sample_stress_along_line(grid: pv.UnstructuredGrid, point_a, point_b, scalar_name: str = "Von Mises Stress", resolution: int = 100) -> tuple[np.ndarray, np.ndarray]` returning `(distances_mm, stress_values_mpa)`.
     * `slice_stress_on_plane(grid: pv.UnstructuredGrid, plane_type: str, origin_coord: float, scalar_name: str = "Von Mises Stress") -> dict` returning `{"u": np.ndarray, "v": np.ndarray, "triangles": np.ndarray, "scalars": np.ndarray, "plane_label": str}`.

### Step 4.2: Create the Floating Plot Widget (`scripts/app/widgets/stress_plot_popup.py`)

* **Target File:** `scripts/app/widgets/stress_plot_popup.py` (New File)
* **Action:**
  1. Create `class StressPlotPopup(QWidget):` with `super().__init__(parent, Qt.Window)` and `self.setAttribute(Qt.WA_DeleteOnClose, True)`.
  2. Support two rendering modes:
     * **Path Mode (`mode="path"`):**
       * Plots `distances_mm` (X-axis: `"Distance along path [mm]"`) vs. `scaled_stress` (Y-axis: `"Stress [MPa]"`).
       * Displays peak stress annotation (`Max: XXX.X MPa`) and an optional dashed horizontal reference line for `yield_strength_mpa`.
     * **Plane Mode (`mode="plane"`):**
       * Uses `tri = matplotlib.tri.Triangulation(u, v, triangles)` and renders `ax.tricontourf(tri, scaled_stress, levels=24, cmap="jet")` (or `"turbo"` / `"viridis"` matching the 3D colormap) with a colorbar (`"Stress [MPa]"`).
       * Calls `ax.set_aspect("equal")` and `ax.set_axis_off()` so coordinate axes are hidden per specification.
  3. Add the bottom control bar:
     * `QLabel("Simulated Amplitude:")`
     * `QSlider(Qt.Horizontal)` (range `1` to `100`, default `int(round(nominal_amplitude_um))`)
     * `QLabel(f"{current_amp:.1f} µm | Peak: {peak_stress:.1f} MPa")`
  4. Connect `slider.valueChanged` to a fast `_on_amplitude_changed(val)` method that rescales `self._base_stress * (val / self._nominal_amplitude)` and redraws the canvas via `self.canvas.draw_idle()`.

### Step 4.3: Wire Scalar Switching & Right-Click Probing in `scripts/app/controllers/results_controller.py`

* **Target File:** `scripts/app/controllers/results_controller.py`
* **Action:**
  1. **Scalar Dropdown Wiring:**
     * Connect `self.ui.combo_active_scalar.currentTextChanged` to `_on_active_scalar_changed(scalar_name)`.
     * Update the active scalar on the currently displayed PyVista mesh and update the scalar bar title without resetting camera position.
  2. **Right-Click Context Menu:**
     * Install a right-click handler on the PyVista `QtInteractor` (tracking mouse press/release delta `< 5 px` so right-button camera zoom drags do not trigger the popup menu).
     * Show a `QMenu` with:
       * `"Define Stress Path (Line)"` $\rightarrow$ triggers `_start_stress_path_picking()`
       * `"Define Cross-Section (Plane)"` $\rightarrow$ triggers `_open_cross_section_dialog()`
  3. **Two-Point Path Workflow:**
     * `_start_stress_path_picking()` pauses animation if active, clears prior probe markers, and enables point picking for 2 clicks.
     * On click 1: stores `point_a`, places a marker sphere, updates status text.
     * On click 2: stores `point_b`, disables picking immediately (`plotter.disable_picking()`), draws the path line overlay, calls `sample_stress_along_line(...)`, and spawns `StressPlotPopup(mode="path", ...)`.
  4. **Cross-Section Plane Workflow:**
     * `_open_cross_section_dialog()` displays a small dialog with plane selector (`xOy (Normal: Z)`, `xOz (Normal: Y)`, `yOz (Normal: X)`) and coordinate `QDoubleSpinBox` initialized to the bounding-box center along the chosen normal.
     * On OK: calls `slice_stress_on_plane(...)`, draws a translucent slice plane indicator on the 3D mesh, and spawns `StressPlotPopup(mode="plane", ...)`.
  5. **Popup Lifecycle Tracking:**
     * Append every spawned `StressPlotPopup` to `self._plot_popups` and connect `popup.destroyed` to remove it from the list.

## 4. Verification & Automated Tests

Create and execute `tests/test_phase4_3d_probing_popups.py` in the `sonotrode_lab` environment using `pytest`. Phase 4 is complete only when all automated tests pass and the manual visual inspection checklist confirms smooth 3D interaction.

### 4.1. Automated Test Suite (`tests/test_phase4_3d_probing_popups.py`)

```python
import os
import sys
import math
import numpy as np
import pyvista as pv
import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from modal_inspection_service import sample_stress_along_line, slice_stress_on_plane
from app.widgets.stress_plot_popup import StressPlotPopup


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _make_synthetic_specimen_grid() -> pv.UnstructuredGrid:
    """
    Create a 3D tetrahedral UnstructuredGrid spanning x in [-5, 5], y in [0, 40], z in [-2, 2]
    with a known analytical stress distribution:
        Von Mises Stress(x, y, z) = 100.0 + 10.0 * y   (linear ramp from 100 MPa to 500 MPa)
    """
    box = pv.Box(bounds=[-5.0, 5.0, 0.0, 40.0, -2.0, 2.0], level=4)
    grid = box.delaunay_3d()
    y_coords = grid.points[:, 1]
    vm_stress = 100.0 + 10.0 * y_coords
    grid.point_data["Von Mises Stress"] = vm_stress
    grid.point_data["Max Principal Stress"] = vm_stress * 1.05
    grid.point_data["Displacement Magnitude (U)"] = np.abs(y_coords - 20.0) * 1e-3
    grid.point_data["Displacement Y (U2)"] = (y_coords - 20.0) * 1e-3
    return grid


# ---------------------------------------------------------------------------
# 1. PyVista 1D Line Sampling Verification
# ---------------------------------------------------------------------------
def test_sample_stress_along_line_analytical_accuracy():
    """Sample along Y-axis from y=0 to y=40 and verify distance & interpolated stress."""
    grid = _make_synthetic_specimen_grid()
    distances, stresses = sample_stress_along_line(
        grid=grid,
        point_a=(0.0, 0.0, 0.0),
        point_b=(0.0, 40.0, 0.0),
        scalar_name="Von Mises Stress",
        resolution=100,
    )

    assert len(distances) == 101
    assert len(stresses) == 101
    assert math.isclose(distances[0], 0.0, abs_tol=1e-6)
    assert math.isclose(distances[-1], 40.0, rel_tol=1e-5)

    # Expected stress at distance s is 100 + 10 * s
    expected_stress = 100.0 + 10.0 * distances
    assert np.allclose(stresses, expected_stress, atol=1.0)


# ---------------------------------------------------------------------------
# 2. PyVista 2D Cross-Section Slicing Verification
# ---------------------------------------------------------------------------
def test_slice_stress_on_plane_extracts_valid_2d_contour_data():
    """Slice at y=20.0 (xOz plane) where analytical stress is uniform 300.0 MPa."""
    grid = _make_synthetic_specimen_grid()
    slice_data = slice_stress_on_plane(
        grid=grid,
        plane_type="xOz",
        origin_coord=20.0,
        scalar_name="Von Mises Stress",
    )

    assert len(slice_data["u"]) > 0
    assert len(slice_data["v"]) == len(slice_data["u"])
    assert slice_data["triangles"].ndim == 2 and slice_data["triangles"].shape[1] == 3
    assert np.allclose(slice_data["scalars"], 300.0, atol=1.0)


# ---------------------------------------------------------------------------
# 3. Floating Window & Amplitude Slider Independence Verification
# ---------------------------------------------------------------------------
def test_stress_plot_popup_path_and_plane_slider_scaling(qapp):
    """
    Verify StressPlotPopup instantiates in both 'path' and 'plane' modes,
    hides axes in 'plane' mode, and rescales displayed stress linearly via slider.
    """
    # A. Path Mode Popup
    distances = np.linspace(0.0, 40.0, 50)
    base_stress = np.linspace(100.0, 300.0, 50)
    popup_path = StressPlotPopup(
        mode="path",
        distances_mm=distances,
        base_stress_mpa=base_stress,
        nominal_amplitude_um=20.0,
        yield_strength_mpa=350.0,
        title="Test Path Popup",
    )
    assert math.isclose(popup_path.current_peak_stress_mpa, 300.0, rel_tol=1e-6)

    # Move slider from 20 um to 40 um -> peak stress must double to 600 MPa
    popup_path.amplitude_slider.setValue(40)
    assert math.isclose(popup_path.current_peak_stress_mpa, 600.0, rel_tol=1e-6)

    # B. Plane Mode Popup (verify axes are hidden)
    grid = _make_synthetic_specimen_grid()
    slice_data = slice_stress_on_plane(grid, "xOz", 20.0, "Von Mises Stress")
    popup_plane = StressPlotPopup(
        mode="plane",
        slice_data=slice_data,
        nominal_amplitude_um=20.0,
        yield_strength_mpa=350.0,
        title="Test Plane Popup",
    )
    assert not popup_plane.ax.axison, "Coordinate axes must be hidden in cross-section contour view"

    popup_plane.amplitude_slider.setValue(10)
    assert math.isclose(popup_plane.current_peak_stress_mpa, 150.0, atol=1.0)

    popup_path.close()
    popup_plane.close()
```

### 4.2. Manual Human-in-the-Loop 3D Inspection Checklist

After `pytest tests/test_phase4_3d_probing_popups.py` passes completely, run `python scripts/main.py` and verify:

1. **Multi-Field Colormaps:**
   * [ ] Load a solved VHCF specimen in the **3D Results** tab.
   * [ ] Toggle `Active Scalar Field` across all 4 options (`Displacement Magnitude (U)`, `Displacement Y (U2)`, `Von Mises Stress`, `Max Principal Stress`). Confirm smooth colormap updates without camera jumps, and confirm peak stress appears in the gauge neck rather than at the free ends.
   * [ ] Scrub the `Deformation scale` slider and toggle `Make it move!` while `Von Mises Stress` is active. Confirm smooth deformation animation with stress colors intact.

2. **Right-Click Stress Path (Line):**
   * [ ] Right-click the 3D model and choose `Define Stress Path (Line)`.
   * [ ] Left-click two points spanning across the gauge section. Confirm a floating Matplotlib window opens with `Stress [MPa]` vs. `Distance along path [mm]` and normal 3D camera rotation works immediately afterward.
   * [ ] Move the slider at the bottom of the popup and confirm the stress curve rescales instantaneously without freezing the 3D window or altering `ProjectSession`.

3. **Right-Click Cross-Section (Plane) & Multiple Popups:**
   * [ ] Without closing the first popup, right-click the 3D model again and choose `Define Cross-Section (Plane)`.
   * [ ] Select the transverse plane (e.g., `xOz`) at the center of the gauge section. Confirm a second independent floating window opens showing a clean, axis-free 2D stress contour map with a colorbar.
   * [ ] Minimize and restore both popups, move their amplitude sliders independently, and confirm zero UI lag.