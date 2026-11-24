# Phase 3: Analytics Tab, Stress Metrics Computation & Dynamic Columns

> **⚠️ CRITICAL AI DIRECTIVE: STRICT PRESERVATION OF INDEPENDENT BEHAVIORS**
> 1. **IGNORE SPECIMEN-SPECIFIC MODE FILTERING:** Do **not** modify, replace, or branch the existing mode-selection algorithm (`select_longitudinal_mode` in `scripts/ccx_results_parser.py`). All specimen types must continue using the existing mode-selection logic unchanged in this phase. Specimen-specific kinematic mode filtering (e.g., biaxial disc modes or flat bending/torsion separation) is intentionally deferred to a future phase.
> 2. **PRESERVE EXISTING PIPELINES:** Do not alter SolidWorks STEP export, Gmsh meshing, CalculiX execution, or the existing pandas `df_merged` logic that appends geometrical and material parameters from the project Excel workbook. Only update simulation metric extraction, stress post-processing, and dynamic summary column selection.

## 1. Objective & Detailed Intended Behavior

Phase 3 upgrades the post-processing parser (`ccx_results_parser.py`) and the **Analytics Tab** (`analytics_controller.py` / table model) so that after CalculiX solves a model, the application extracts modal stress tensors inside `GAUGE_VOL`, scales them to physical stress units based on the user's input excitation amplitude, validates them against the material's yield strength, and displays a tailored summary table for the selected specimen type.

### 1.1. Post-Processing Flow (Mode Selection $\rightarrow$ Stress Extraction)

1. **Unchanged Mode Selection:**
   * For every solved model, the parser reads the `.dat` file and runs the existing `select_longitudinal_mode(...)` function to identify `Mode_Index`, `Frequency_Hz`, and the raw modal displacements at the base (`YMIN`) and tip (`YMAX`).
2. **Gauge Volume Stress Harvesting:**
   * Using the selected `Mode_Index`, the parser reads the corresponding modal stress block (`STRESS`) from the model's `.frd` file (`04_Results_CCX/<model>.frd`).
   * It reads the `GAUGE_VOL_NODES` node set (and/or `GAUGE_VOL` element set) from the model's mesh `.inp` file (`03_Meshes_INP/<model>_mesh.inp`, or fallback mesh if used).
   * It filters the nodal stress tensors strictly to the nodes belonging to `GAUGE_VOL_NODES`, ignoring artificial stress singularities at grips, threads, or outer edges outside the user's bounding box.
3. **Graceful Degradation (Backward Compatibility):**
   * If a legacy project or model has **no** `GAUGE_VOL_NODES` in its `.inp` file, or if the `.frd` file has no `STRESS` block for the selected mode, the parser must **not** crash. It must populate `Max_Stress [MPa]` and `Stress_Gain [MPa/µm]` with `np.nan` and `Yield_Status` with `"N/A"`, while still returning all valid frequency and displacement metrics.

### 1.2. Dynamic Analytics Table Schemas

The Analytics Tab dynamically adapts its displayed simulation metric columns based on `self.session.specimen_type`, while **always** preserving the `Status` column (if present in the job table) and all geometrical/material columns appended by the existing Excel `df_merged` merge.

* **Common Base Simulation Columns (Always Included):**
  * `Model_name`
  * `Number_of_nodes`
  * `Mode_Index`
  * `Frequency_Hz`
* **If `specimen_type == "Longitudinal Specimen"`:**
  * Add: `Base_Disp_µm`, `Tip_Disp_µm`, `Displacement_Ratio`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`
* **If `specimen_type == "Disc Specimen (Biaxial)"`:**
  * Add: `Base_Disp_µm`, `Center_Disp_Z_µm`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`
  * *(Note for Phase 3: Because specimen-specific mode filtering is deferred, `Center_Disp_Z_µm` may be computed as the scaled mean $|U_z|$ across `GAUGE_VOL_NODES` if FRD displacements are available, or set to `np.nan` cleanly without crashing).*
* **If `specimen_type == "Flat/Thin-Walled Specimen"`:**
  * Add: `Base_Disp_µm`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`

### 1.3. Visual Yield Validation & Interactive Plotting

1. **Conditional Formatting in the Analytics Table:**
   * In the `Yield_Status` column:
     * `"Pass"` renders with a **green** visual indicator (e.g., dark green bold text or soft green cell background).
     * `"Fail"` renders with a **red** visual indicator (e.g., dark red bold text or soft red cell background).
     * `"N/A"` renders in neutral default/muted text.
2. **Automatic Plot & Export Compatibility:**
   * Because `Max_Stress [MPa]` and `Stress_Gain [MPa/µm]` are stored as standard numeric `float` columns in the Pandas DataFrame, the existing Analytics Tab 2D/3D Matplotlib scatter plot dropdowns (`X`, `Y`, `Z`) automatically list them as plottable metrics.
   * Exporting to `05_Reports/Results_Summary.xlsx` exports the active dynamic columns along with the merged geometry parameters.

## 2. Mathematical Specification of Stress Metrics

Because CalculiX performs a free-free linear modal analysis (`*FREQUENCY`), the eigenvectors (modal displacements and modal stresses) are mass-normalized and have **only relative physical validity** within a given mode. Physical VHCF stress levels are recovered via linear elastic scaling against the nominal ultrasonic booster excitation amplitude $A_{\text{input}}$.

### 2.1. Unit Consistency Convention (CRITICAL)

In this codebase's CalculiX pipeline:
* CAD geometry (`.step` / `.inp`) is in **millimeters ($\text{mm}$)**.
* Young's modulus $E$ is in **Megapascals ($\text{MPa} = \text{N}/\text{mm}^2$)**.
* Consequently, raw CalculiX `.frd` nodal displacements $U_{\text{raw}}$ are in **$\text{mm}$**, and raw `.frd` nodal stress tensor components $\sigma_{ij,\text{raw}}$ are in **$\text{MPa}$**.
* The user's input excitation amplitude $A_{\text{input}}$ in the Setup Tab is specified in **micrometers ($\mu\text{m}$)**, where $1\text{ mm} = 1000\text{ }\mu\text{m}$.

### 2.2. Per-Node Equivalent Stress Computation

For every node $k \in \text{GAUGE\_VOL\_NODES}$, CalculiX writes the 6 independent components of the symmetric Cauchy stress tensor in the `.frd` `STRESS` block:

$$
\boldsymbol{\sigma}^{(k)}_{\text{raw}} = \begin{bmatrix} \sigma_{xx} & \tau_{xy} & \tau_{zx} \\ \tau_{xy} & \sigma_{yy} & \tau_{yz} \\ \tau_{zx} & \tau_{yz} & \sigma_{zz} \end{bmatrix}
$$

1. **Von Mises Equivalent Stress ($\sigma_{\text{vM}, \text{raw}}^{(k)}$):**
   Computed at every node $k$ in `GAUGE_VOL_NODES`:

   $$
   \sigma_{\text{vM}, \text{raw}}^{(k)} = \sqrt{\frac{1}{2} \left[ (\sigma_{xx} - \sigma_{yy})^2 + (\sigma_{yy} - \sigma_{zz})^2 + (\sigma_{zz} - \sigma_{xx})^2 + 6\left(\tau_{xy}^2 + \tau_{yz}^2 + \tau_{zx}^2\right) \right]}
   $$

2. **Maximum Principal Stress ($\sigma_{1, \text{raw}}^{(k)}$):**
   Also compute and expose via a reusable helper (for consistency with Phase 4 3D colormaps) as the largest real eigenvalue of the symmetric $3 \times 3$ matrix $\boldsymbol{\sigma}^{(k)}_{\text{raw}}$:

   $$
   \sigma_{1, \text{raw}}^{(k)} = \max\left(\lambda_1, \lambda_2, \lambda_3\right), \quad \text{where } \lambda_i = \text{eigvalsh}\left(\boldsymbol{\sigma}^{(k)}_{\text{raw}}\right)
   $$

*(By default, the Analytics table metrics `Stress_Gain [MPa/µm]` and `Max_Stress [MPa]` use **Von Mises equivalent stress** $\sigma_{\text{vM}}$ as the primary scalar).*

### 2.3. Reference Base Displacement ($U_{\text{base}}$)

From the selected mode's displacement field at the booster connection surface (`NSET=YMIN`), compute the mean axial displacement magnitude in native solver units ($\text{mm}$) and convert to micrometers ($\mu\text{m}$):

$$
U_{\text{base, mm}} = \left| \frac{1}{N_{\text{YMIN}}} \sum_{j \in \text{YMIN}} u_{y,\text{raw}}^{(j)} \right|
$$

$$
U_{\text{base, }\mu\text{m}} = U_{\text{base, mm}} \times 1000.0
$$

* **Zero-Division Guard:** If $U_{\text{base, }\mu\text{m}} < 10^{-12}$, treat the scaling factor as undefined (`np.nan`) to prevent `ZeroDivisionError` or `inf` values.

### 2.4. Linear Elastic Scaling Factor ($\alpha$)

To scale the arbitrary modal eigenvector to the physical excitation amplitude $A_{\text{input}}$ (in $\mu\text{m}$), define the dimensionless physical scaling factor $\alpha$:

$$
\alpha = \frac{A_{\text{input, }\mu\text{m}}}{U_{\text{base, }\mu\text{m}}} = \frac{A_{\text{input, }\mu\text{m}}}{U_{\text{base, mm}} \times 1000.0}
$$

*Note:* Applying $\alpha$ to `Base_Disp_µm` yields $U_{\text{base, }\mu\text{m}} \times \alpha = A_{\text{input, }\mu\text{m}}$ (matching the user's nominal booster input amplitude). Applying $\alpha$ to any raw nodal stress $\sigma_{\text{raw}}$ (in $\text{MPa}$) yields the physical stress amplitude in $\text{MPa}$:

$$
\sigma_{\text{scaled}}^{(k)} = \alpha \cdot \sigma_{\text{vM, raw}}^{(k)} \quad [\text{MPa}]
$$

### 2.5. Stress Gain ($C_s$)

Per project requirements, **Stress Gain ($C_s$) must be computed from the spatial average stress across the gauge volume—never from a single node**—to avoid mesh-singularity bias:

$$
\bar{\sigma}_{\text{gauge, raw}} = \frac{1}{N_{\text{gauge}}} \sum_{k \in \text{GAUGE\_VOL\_NODES}} \sigma_{\text{vM, raw}}^{(k)} \quad [\text{MPa}]
$$

$$
C_s = \frac{\bar{\sigma}_{\text{gauge, raw}}}{U_{\text{base, }\mu\text{m}}} \quad \left[\frac{\text{MPa}}{\mu\text{m}}\right]
$$

Notice that $C_s$ is an intrinsic geometric-material property of the specimen mode shape: it is **independent of $A_{\text{input}}$**.

### 2.6. Theoretical Maximum Stress ($\sigma_{\max}$) & Yield Validation

To verify that the specimen stays within the macroscopic linear elastic regime everywhere inside the gauge volume, compute the scaled peak stress inside `GAUGE_VOL_NODES`:

$$
\sigma_{\max} = \alpha \cdot \max_{k \in \text{GAUGE\_VOL\_NODES}} \left( \sigma_{\text{vM, raw}}^{(k)} \right) \quad [\text{MPa}]
$$

Evaluate against the user-defined material yield strength $\sigma_{\text{yield}}$ (`self.session.yield_strength` in $\text{MPa}$):

$$
\text{Yield\_Status} = \begin{cases} \text{"Pass"} & \text{if } \sigma_{\max} < \sigma_{\text{yield}} \\ \text{"Fail"} & \text{if } \sigma_{\max} \ge \sigma_{\text{yield}} \\ \text{"N/A"} & \text{if } \sigma_{\max} \text{ is } \text{NaN} \text{ or } \sigma_{\text{yield}} \le 0 \end{cases}
$$

## 3. Required AI Agent Skills & Domain Knowledge

Before modifying the codebase, the AI agent executing this phase must apply the following technical skills:

* **CalculiX ASCII `.frd` File Parsing (CRITICAL):**
  * Understanding the CalculiX `.frd` block structure:
    * Step/mode header lines starting with `100CL` (containing mode number and eigenvalue/frequency).
    * Dataset header lines starting with ` -4  STRESS` followed by ` -5` component declarations (`SXX`, `SYY`, `SZZ`, `SXY`, `SYZ`, `SZX`).
    * Nodal data lines starting with ` -1`, followed by a 10-character node ID and **six 12-character fixed-width Fortran scientific floats** (indices `[3:13]` for node ID, then slices of width 12: `[13:25]`, `[25:37]`, `[37:49]`, `[49:61]`, `[61:73]`, `[73:85]`).
  * **Why fixed-width slicing is mandatory:** In Fortran `.frd` output, negative numbers frequently touch the preceding number with **zero whitespace** (e.g., `1.23456E+02-2.34567E+01`). Calling `line.split()` **will fail** on real CalculiX files. Always parse `.frd` numeric fields using fixed-width slicing (or a compiled float regex fallback).
* **Vectorized Continuum Mechanics (NumPy):**
  * Computing Von Mises stress and batched $3 \times 3$ symmetric eigenvalues (`np.linalg.eigvalsh`) over tens of thousands of nodes in milliseconds using NumPy arrays rather than Python loops.
* **Safe Pandas DataFrame Schema Projection:**
  * Selecting/reordering simulation summary columns dynamically according to `specimen_type` while preserving all dynamic Excel geometry columns merged via `df_merged`.
* **PySide6 Table Styling (`QAbstractTableModel` / `QTableWidget`):**
  * Applying conditional foreground/background colors (`QColor` / `QBrush`) specifically to the `Yield_Status` column without breaking sorting, numeric formatting, or row selection.

## 4. Step-by-Step Implementation Plan

Execute these steps in exact sequential order.

### Step 3.1: Add Stress Parsing & Math Helpers to `scripts/ccx_results_parser.py`

* **Target File:** `scripts/ccx_results_parser.py`
* **Action:**
  1. Implement `parse_inp_node_set(inp_path: str, set_name: str = "GAUGE_VOL_NODES") -> set[int]` (or reuse/extend the existing INP NSET parser) to extract 1-based node IDs for `GAUGE_VOL_NODES` (and fallback to extracting nodes from `*ELSET, ELSET=GAUGE_VOL` + `*ELEMENT` if only the ELSET is present).
  2. Implement `parse_frd_stress_for_mode(frd_path: str, mode_index: int) -> dict[int, np.ndarray]` (returning `{node_id: np.array([sxx, syy, szz, sxy, syz, szx])}` or vectorized `(node_ids, stress_tensor_nx6)`):
     * Must parse fixed-width 12-character Fortran float fields safely.
     * Must match the requested `mode_index` (1-based mode step in `100CL` header).
  3. Implement pure math helpers:
     * `compute_von_mises(stress_nx6: np.ndarray) -> np.ndarray`
     * `compute_max_principal_stress(stress_nx6: np.ndarray) -> np.ndarray`
     * `compute_gauge_stress_metrics(stress_nx6: np.ndarray, base_disp_mm: float, input_amplitude_um: float, yield_strength_mpa: float) -> dict` returning:
       * `Stress_Gain [MPa/µm]`
       * `Max_Stress [MPa]`
       * `Yield_Status`
  4. **Keep `select_longitudinal_mode(...)` completely intact.** Do not add specimen-specific mode filtering branches.

### Step 3.2: Define Specimen Summary Column Schemas

* **Target File:** `scripts/ccx_results_parser.py` (and imported by `analytics_controller.py` / `analytics_table_model.py`)
* **Action:**
  1. Define a canonical dictionary `SPECIMEN_SUMMARY_COLUMNS`:
     ```python
     COMMON_BASE_COLUMNS = [
         "Model_name",
         "Number_of_nodes",
         "Mode_Index",
         "Frequency_Hz",
     ]

     SPECIMEN_SUMMARY_COLUMNS = {
         "Longitudinal Specimen": COMMON_BASE_COLUMNS + [
             "Base_Disp_µm",
             "Tip_Disp_µm",
             "Displacement_Ratio",
             "Max_Stress [MPa]",
             "Stress_Gain [MPa/µm]",
             "Yield_Status",
         ],
         "Disc Specimen (Biaxial)": COMMON_BASE_COLUMNS + [
             "Base_Disp_µm",
             "Center_Disp_Z_µm",
             "Max_Stress [MPa]",
             "Stress_Gain [MPa/µm]",
             "Yield_Status",
         ],
         "Flat/Thin-Walled Specimen": COMMON_BASE_COLUMNS + [
             "Base_Disp_µm",
             "Max_Stress [MPa]",
             "Stress_Gain [MPa/µm]",
             "Yield_Status",
         ],
     }
     ```
  2. Add a helper `get_summary_columns(specimen_type: str) -> list[str]` that defaults safely to `"Longitudinal Specimen"` if an unknown string is passed.
  3. Update the summary-row builder function in `ccx_results_parser.py` to accept optional parameters `specimen_type="Longitudinal Specimen"`, `input_amplitude_um=20.0`, `yield_strength_mpa=300.0`, and populate the new columns (`Base_Disp_µm`, `Tip_Disp_µm`, `Displacement_Ratio`, `Center_Disp_Z_µm`, `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, `Yield_Status`) while preserving backward-compatible defaults.

### Step 3.3: Wire Dynamic Columns & Yield Highlighting in Analytics Controller / Table Model

* **Target Files:** `scripts/app/controllers/analytics_controller.py` (and `scripts/analytics_table_model.py` if present)
* **Action:**
  1. When parsing results or refreshing the Analytics table, pass `self.session.specimen_type`, the active input excitation amplitude (`µm`), and `self.session.yield_strength` (`MPa`) to the parser.
  2. When constructing the final display DataFrame after `df_merged` combines simulation results with the Excel geometry/material table:
     * Keep `Status` (if present) + `get_summary_columns(self.session.specimen_type)` + all non-simulation Excel geometry columns from `df_merged`.
     * **Do not drop or overwrite any Excel geometrical parameter columns.**
  3. Re-evaluate/refresh the displayed columns if the user changes `specimen_type` or `yield_strength` on the Setup Tab and switches to the Analytics Tab.
  4. Add conditional cell coloring for the `Yield_Status` column:
     * `"Pass"` $\rightarrow$ Green text/background.
     * `"Fail"` $\rightarrow$ Red text/background.

## 5. Verification & Automated Tests

Create and execute `tests/test_phase3_stress_analytics.py` in the `sonotrode_lab` environment using `pytest`. Phase 3 is complete only when all automated tests pass and the manual UI check confirms clean table rendering and geometry merge preservation.

### 5.1. Automated Test Suite (`tests/test_phase3_stress_analytics.py`)

```python
import os
import sys
import math
import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from ccx_results_parser import (
    compute_von_mises,
    compute_max_principal_stress,
    compute_gauge_stress_metrics,
    parse_frd_stress_for_mode,
    get_summary_columns,
)


# ---------------------------------------------------------------------------
# 1. Continuum Mechanics Math Verification
# ---------------------------------------------------------------------------
def test_von_mises_and_principal_stress_analytical():
    """Verify Von Mises and Max Principal stress against closed-form analytical cases."""
    # Case A: Pure uniaxial tension (sxx = 100 MPa) -> vM = 100, sigma_1 = 100
    # Case B: Pure shear (sxy = 100 MPa) -> vM = sqrt(3)*100, sigma_1 = 100
    # Case C: Equi-biaxial tension (sxx = syy = 100 MPa) -> vM = 100, sigma_1 = 100
    tensors = np.array([
        [100.0,   0.0, 0.0,   0.0, 0.0, 0.0],
        [  0.0,   0.0, 0.0, 100.0, 0.0, 0.0],
        [100.0, 100.0, 0.0,   0.0, 0.0, 0.0],
    ], dtype=float)

    vm = compute_von_mises(tensors)
    s1 = compute_max_principal_stress(tensors)

    assert np.allclose(vm, [100.0, 100.0 * math.sqrt(3.0), 100.0], rtol=1e-6)
    assert np.allclose(s1, [100.0, 100.0, 100.0], rtol=1e-6)


# ---------------------------------------------------------------------------
# 2. Unit Conversion, Stress Gain (Cs), Scaling & Yield Status Tests
# ---------------------------------------------------------------------------
def test_stress_gain_scaling_and_yield_validation():
    """
    Verify exact mm -> um unit conversion:
      - 2 nodes in GAUGE_VOL with raw uniaxial stresses 1000 MPa and 2000 MPa
        -> mean raw vM = 1500 MPa, max raw vM = 2000 MPa
      - Raw base displacement = 0.2 mm (= 200 um)
      - Expected Stress Gain Cs = 1500 / 200 = 7.5 MPa/um (independent of input amplitude)
      - Input amplitude = 20 um -> scale factor alpha = 20 / 200 = 0.1
      - Expected Max_Stress = 2000 * 0.1 = 200.0 MPa
      - Yield strength = 300.0 MPa -> Pass; Yield strength = 150.0 MPa -> Fail
    """
    gauge_tensors = np.array([
        [1000.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [2000.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ], dtype=float)

    res_pass = compute_gauge_stress_metrics(
        stress_nx6=gauge_tensors,
        base_disp_mm=0.2,
        input_amplitude_um=20.0,
        yield_strength_mpa=300.0,
    )
    assert math.isclose(res_pass["Stress_Gain [MPa/µm]"], 7.5, rel_tol=1e-6)
    assert math.isclose(res_pass["Max_Stress [MPa]"], 200.0, rel_tol=1e-6)
    assert res_pass["Yield_Status"] == "Pass"

    res_fail = compute_gauge_stress_metrics(
        stress_nx6=gauge_tensors,
        base_disp_mm=0.2,
        input_amplitude_um=20.0,
        yield_strength_mpa=150.0,
    )
    assert math.isclose(res_fail["Stress_Gain [MPa/µm]"], 7.5, rel_tol=1e-6)
    assert math.isclose(res_fail["Max_Stress [MPa]"], 200.0, rel_tol=1e-6)
    assert res_fail["Yield_Status"] == "Fail"


def test_stress_metrics_zero_displacement_and_empty_gauge_guard():
    """Verify near-zero base displacement or empty gauge array never crashes."""
    empty_tensors = np.empty((0, 6), dtype=float)
    res_empty = compute_gauge_stress_metrics(empty_tensors, 0.2, 20.0, 300.0)
    assert math.isnan(res_empty["Stress_Gain [MPa/µm]"])
    assert math.isnan(res_empty["Max_Stress [MPa]"])
    assert res_empty["Yield_Status"] == "N/A"

    valid_tensors = np.array([[500.0, 0.0, 0.0, 0.0, 0.0, 0.0]], dtype=float)
    res_zero = compute_gauge_stress_metrics(valid_tensors, 0.0, 20.0, 300.0)
    assert math.isnan(res_zero["Stress_Gain [MPa/µm]"])
    assert math.isnan(res_zero["Max_Stress [MPa]"])
    assert res_zero["Yield_Status"] == "N/A"


# ---------------------------------------------------------------------------
# 3. Synthetic CalculiX .frd Fixed-Width Fortran Parsing Test
# ---------------------------------------------------------------------------
def test_parse_frd_stress_fixed_width_touching_negatives(tmp_path):
    """
    Verify FRD parser handles Fortran 12-char fixed-width floats where negative
    numbers touch adjacent numbers with zero whitespace.
    """
    frd_content = (
        "    1C\n"
        "  100CL  101 2.00000E+04           2                     2    1           1\n"
        " -4  STRESS      6    1\n"
        " -5  SXX         1    4    1    1\n"
        " -5  SYY         1    4    2    2\n"
        " -5  SZZ         1    4    3    3\n"
        " -5  SXY         1    4    1    2\n"
        " -5  SYZ         1    4    2    3\n"
        " -5  SZX         1    4    3    1\n"
        " -1         1 1.50000E+02-2.50000E+01 0.00000E+00-1.00000E+01 5.00000E+00-3.00000E+00\n"
        " -1         2-4.00000E+01 8.00000E+01-1.20000E+01 0.00000E+00 0.00000E+00 0.00000E+00\n"
        " -3\n"
        "  9999\n"
    )
    frd_file = tmp_path / "synthetic.frd"
    frd_file.write_text(frd_content, encoding="utf-8")

    stress_map = parse_frd_stress_for_mode(str(frd_file), mode_index=1)
    assert 1 in stress_map and 2 in stress_map
    assert np.allclose(stress_map[1], [150.0, -25.0, 0.0, -10.0, 5.0, -3.0])
    assert np.allclose(stress_map[2], [-40.0, 80.0, -12.0, 0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# 4. Dynamic Column Schema & Geometry Merge Preservation Test
# ---------------------------------------------------------------------------
def test_dynamic_summary_columns_and_geometry_preservation():
    """Verify exact headers per specimen type and ensure Excel geometry columns survive."""
    long_cols = get_summary_columns("Longitudinal Specimen")
    assert "Tip_Disp_µm" in long_cols
    assert "Displacement_Ratio" in long_cols
    assert "Center_Disp_Z_µm" not in long_cols
    assert "Stress_Gain [MPa/µm]" in long_cols

    disc_cols = get_summary_columns("Disc Specimen (Biaxial)")
    assert "Center_Disp_Z_µm" in disc_cols
    assert "Tip_Disp_µm" not in disc_cols
    assert "Displacement_Ratio" not in disc_cols

    flat_cols = get_summary_columns("Flat/Thin-Walled Specimen")
    assert "Base_Disp_µm" in flat_cols
    assert "Max_Stress [MPa]" in flat_cols
    assert "Tip_Disp_µm" not in flat_cols
    assert "Center_Disp_Z_µm" not in flat_cols

    # Simulate df_merged with Excel geometry parameters
    df_sim = pd.DataFrame([{
        "Model_name": "Spec_01",
        "Number_of_nodes": 12000,
        "Mode_Index": 7,
        "Frequency_Hz": 20015.4,
        "Base_Disp_µm": 20.0,
        "Tip_Disp_µm": 20.1,
        "Displacement_Ratio": 1.005,
        "Max_Stress [MPa]": 185.2,
        "Stress_Gain [MPa/µm]": 8.1,
        "Yield_Status": "Pass",
    }])
    df_excel = pd.DataFrame([{
        "Model_name": "Spec_01",
        "Gauge_Width_mm": 4.0,
        "Fillet_Radius_mm": 15.0,
    }])

    df_merged = pd.merge(df_sim, df_excel, on="Model_name", how="left")
    expected_sim_cols = [c for c in flat_cols if c in df_merged.columns]
    geom_cols = [c for c in df_excel.columns if c != "Model_name"]
    df_view = df_merged[expected_sim_cols + geom_cols]

    assert "Gauge_Width_mm" in df_view.columns
    assert "Fillet_Radius_mm" in df_view.columns
    assert "Tip_Disp_µm" not in df_view.columns
```

### 5.2. Manual Analytics UI Smoke Check

After `pytest tests/test_phase3_stress_analytics.py` passes:

1. Launch `python scripts/main.py` and load a project containing at least one solved model with `GAUGE_VOL` and `.frd` stress output.
2. Verify the Analytics table populates `Max_Stress [MPa]`, `Stress_Gain [MPa/µm]`, and `Yield_Status`, and that all geometrical columns from the Excel workbook remain intact on the right side of the table.
3. Lower `Material Yield Strength` on the Setup Tab below the computed `Max_Stress [MPa]` and refresh: confirm `Yield_Status` flips from green `"Pass"` to red `"Fail"`.
4. Switch `Specimen Type` between `Longitudinal Specimen`, `Disc Specimen (Biaxial)`, and `Flat/Thin-Walled Specimen` and confirm the table headers dynamically update while preserving the Excel geometry columns.
5. Select `Stress_Gain [MPa/µm]` on the Analytics scatter plot Y-axis dropdown and confirm it plots cleanly without errors.