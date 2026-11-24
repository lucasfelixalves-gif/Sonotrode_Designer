# AGENTS.md — Sonotrode Designer

## 1. Project Overview

**Sonotrode Designer** is a Windows-first, multithreaded **PySide6** desktop CAE application for designing and evaluating ultrasonic sonotrodes (with planned extensions for Very High Cycle Fatigue [VHCF] specimens). It orchestrates a file-system-driven engineering pipeline:

1. **CAD & Design Table (External):** SolidWorks part configurations + Excel master workbook → batch STEP export (`solidworks_step_export.bas`).
2. **Meshing:** STEP geometry → Gmsh 3D tetrahedral mesh → `meshio` Abaqus/CalculiX `.inp` volume deck with semantic `*NSET` boundary groups (`meshing.py`).
3. **FEA Modal Solve:** Mesh `.inp` + workbook material/step parameters → CalculiX `*FREQUENCY` (`SOLVER=PARDISO`) run via bundled `bin/ccx.exe` (`ccx_solver.py`).
4. **Post-Processing & Analytics:** Parse `.dat`/`.frd` outputs, select the longitudinal mode via a dimensionless fitness score (`ccx_results_parser.py`), merge with workbook geometry/material columns, plot 2D/3D trends, and export styled Excel reports (`analytics_controller.py`).
5. **3D Modal Inspection:** Render deformed mode shapes, boundary-node previews, and sinusoidal warp animations in PyVista (`modal_inspection_service.py`, `results_controller.py`).

For extended user and pipeline documentation, see `README.md` and `GUI_code/GUI_pipeline_documentation.md` (when docs and code diverge, **treat the Python source in `GUI_code/scripts/` as the source of truth**).

---

## 2. Repository & Runtime Layout

Do not confuse the **source repository** with the **runtime project folder** created/loaded by the user.

### Source Repository (`c:\GitHub\Sonotrode_Designer`)
- `bin/` — Bundled Windows **CalculiX 2.22** executable (`ccx.exe`) plus required Intel MKL / OpenMP runtime DLLs (`libiomp5md.dll`, `mkl_*.2.dll`). Keep `ccx.exe` and its DLLs together here.
- `GUI_code/` — Main application root:
  - `environment.yml` — Conda/Mamba environment specification (`sonotrode_lab`).
  - `Sonotrode_Designer.bat` — Windows launcher (activates `sonotrode_lab` from a machine-specific miniforge path and launches `pythonw scripts/main.py`).
  - `GUI_pipeline_documentation.md` — Pipeline/architecture documentation.
  - `scripts/` — All Python source code, `MainWindow.ui`, and SolidWorks macro files.
- `Phase_by_phase_intructions/` *(note spelling; currently untracked)* — Specification documents for planned VHCF Specimen Designer phases (Phases 1–4). **Not yet implemented in `GUI_code/scripts/`.**
- `SonotrodeBatchTools/` — Empty leftover Visual Studio `bin`/`obj` directories; unused.
- `.venv/` — Minimal Python 3.9 virtualenv (pip/setuptools only); **do not use** for running or testing the app.

### Runtime Project Folder (Created/Loaded via Setup Tab)
Every user analysis project uses five standard folders:
- `01_Master_Config/` — Single `.xlsx` master workbook (Sheet 0 = SolidWorks geometry design table; additional sheets added by `augment_master_workbook.py`).
- `02_Geometry_STEP/` — Input `.step` files (`<Model_name>.step`).
- `03_Meshes_INP/` — Generated `<Model_name>_mesh.inp` (and `<Model_name>_mesh_fallback_o1.inp` if first-order Jacobian fallback runs).
- `04_Results_CCX/` — Final solver deck `<Model_name>.inp`, `<Model_name>.log`, `.dat`, `.frd`, `.sta`, `.cvg`.
- `05_Reports/` — Exported Excel summary workbooks (default `Results_Summary.xlsx`).
- `temp_ref.vtk` — Temporary 2D preview mesh written directly in `project_dir` when inspecting a STEP file in Tab 1.

---

## 3. Environment, Running & Testing

### Python Environment
Use the Conda/Mamba environment `sonotrode_lab` defined in `GUI_code/environment.yml`:
- Pinned/core stack: `python=3.11`, `pyside6==6.10.1`, `pandas==3.0.1`, `mkl==2025.3.0`, `numpy>=1.26`, `scipy>=1.11`, `matplotlib>=3.8`, `openpyxl>=3.1`, `gmsh>=4.12`, `python-gmsh`, `meshio>=5.3`, `pyvista>=0.48`, `pyvistaqt>=0.11`.

```powershell
# Create environment (first time)
mamba env create -f GUI_code/environment.yml

# Activate and launch GUI (run from GUI_code/)
conda activate sonotrode_lab
cd GUI_code
python scripts/main.py
```

### Verification & Testing
- **Smoke test imports:**
  ```powershell
  python -c "import gmsh, pyvista, pyvistaqt, PySide6, meshio, pandas, openpyxl; print('OK')"
  ```
- **Standalone workbook augmentation CLI:**
  ```powershell
  python GUI_code/scripts/augment_master_workbook.py --masters-dir <dir> [--master <stem>] [--geometry-sheet <name>]
  ```
- **Automated tests (UI + Visual Screenshot Rig):**
  - Run the `pytest` + `pytest-qt` suite using `sonotrode_lab` (configured via [pytest.ini](file:///c:/GitHub/Sonotrode_Designer/pytest.ini)):
    ```powershell
    C:\Users\lucas\miniforge3\envs\sonotrode_lab\python.exe -m pytest -v
    ```
  - UI harness & dialog interception live in `tests/ui_harness.py` (`DialogRecorder`, `UIHarness`, `build_synthetic_project`) and `tests/conftest.py`.
  - Visual verification screenshots (`01_setup_tab.png`, `02_analytics_tab.png`, `03_results_tab_mode1_warped.png`, `04_results_tab_mode2_bending.png`, plus 3D renders) are saved to `tests/artifacts/` (gitignored via `tests/.gitignore`). Run on the live Windows desktop for full OpenGL PyVista 3D compositing; `QT_QPA_PLATFORM=offscreen` works for pure Qt widget/unit checks without 3D OpenGL rendering.
  - Keep unit/numerical/parser tests independent of SolidWorks installations.
- **CCX resolution:** `ccx_solver._resolve_ccx_executable()` checks `<repo_root>/bin/ccx.exe` **first**, before `PATH` and conda environment directories.

---

## 4. Architecture & Module Map

The codebase follows a strict **MVC + Services + QThread Workers** separation inside `GUI_code/scripts/`:

| Layer | File | Key Symbols & Responsibility |
|---|---|---|
| **Composition Root** | `scripts/main.py` | `MainWindow`: loads `MainWindow.ui` via `QUiLoader`, reparents `centralWidget`, owns `ProjectSession`, `AppContext`, `widgets` (`SimpleNamespace`), timers (`animation_timer`, `sim_timer`), Matplotlib canvas/toolbar in `frame_plot`, stdout/stderr redirection (`EmittingStream`), `F5` disk refresh, and safe VTK plotter teardown in `closeEvent`. |
| **View** | `scripts/MainWindow.ui` | Qt Designer XML layout (`QTabWidget` named `TAB` with tabs `Setup`, `Analytics`, `3D Results`, plus bottom `plainTextEdit_console`). Loaded dynamically at runtime—not compiled to Python. |
| **Model / State** | `scripts/app/state/project_session.py` | `ProjectSession` dataclass: pure Python state container (must **not** import `PySide6.QtWidgets`). Holds paths, workbook/merged DataFrames, `semantic_roles`, `last_picked_info`, `input_amplitude` (default `1.0`), 3D inspection state, and worker/model references. Reset method: `clear_project_data()`. |
| **Table Model** | `scripts/analytics_table_model.py` | `DataFrameTableModel(QAbstractTableModel)`: bridges `job_table_df` to `table_results`; allows inline editing of `Mode_Index`. |
| **Base Controller** | `scripts/app/controllers/base_controller.py` | `AppContext`, `BaseController`. Cross-controller calls go through `self.context.controllers["setup" \| "analytics" \| "results"]`. |
| **Tab 1 Controller** | `scripts/app/controllers/setup_controller.py` | `SetupController`: create/load project, workbook augmentation, STEP geometry list, lazy `QtInteractor` init (`_ensure_plotters`), 2D VTK preview & CAD-face picking (`semantic_roles`), `input_amplitude` assignment, full-batch `SolverWorker` orchestration, `TetrisDialog`. |
| **Tab 2 Controller** | `scripts/app/controllers/analytics_controller.py` | `AnalyticsController`: disk-driven job table rebuild, geometry + material merge, varying-column UI table filtering, 2D/3D Matplotlib scatter plots with hover tooltips & selection path highlights, selected-row `MeshGenerationWorker` / `CCXSolverWorker` execution (`Run CCX`/`Abort CCX`), formatted Excel report export (`05_Reports/`). |
| **Tab 3 Controller** | `scripts/app/controllers/results_controller.py` | `ResultsController`: solved FRD mode rendering & meshed boundary-node preview, `slider_warp` (`-99..99`), `< Previous Mode` / `Next Mode >`, sinusoidal animation (`Make it move!`, 50 ms timer). |
| **Workers** | `scripts/app/workers/mesh_worker.py` | `MeshGenerationWorker(QThread)`: meshes selected rows via `mesh_step_to_inp`. |
| | `scripts/app/workers/solver_worker.py` | `SolverWorker(QThread)`: full-project mesh+solve batch with automatic `Element_order=1` fallback remesh on `"nonpositive jacobian"`. |
| | `scripts/ccx_solver.py` | `CCXSolverWorker(QThread)`: runs CCX only for selected models from Tab 2 (lives in `ccx_solver.py`, not `app/workers/`). |
| | `scripts/app/workers/stream_redirect.py` | `EmittingStream(QObject)`: routes `sys.stdout`/`sys.stderr` to `plainTextEdit_console`. |
| **Services** | `scripts/meshing.py` | `generate_preview_mesh()` (2D VTK with physical tag == CAD surface tag) and `mesh_step_to_inp()` (3D mesh, Netgen + HighOrder optimize, volume-only Abaqus INP + filtered 1-based `*NSET`s). |
| | `scripts/ccx_solver.py` | `_resolve_ccx_executable()`, `_normalize_mesh_for_ccx()`, `_append_bbox_nsets_if_missing()`, `build_frequency_deck()`, `CCXJobRunner`, `solve_frequency_case()`. |
| | `scripts/ccx_results_parser.py` | `SUMMARY_COLUMNS`, `parse_mesh_node_sets()`, `parse_dat_modal_results()`, `select_longitudinal_mode()`, `build_summary_row()`. |
| | `scripts/modal_inspection_service.py` | mtime-keyed `_CACHE`, INP→VTU→PyVista mesh loader, strict state-machine ASCII `.frd` parser, `load_base_result_mesh()`, `load_base_mesh_preview()`, `warp_result_mesh()`. |
| | `scripts/analytics_service.py` | `load_geometry_parameters()` — parses Sheet 0 of the master workbook. |
| | `scripts/augment_master_workbook.py` | `augment_workbook()` — ensures simulation sheets and normalizes legacy material headers. |
| **Optional UI** | `scripts/app/widgets/tetris_*.py`, `tetrix.py` | Optional Tetris popup enabled during active solves. |
| **CAD Macros** | `scripts/solidworks_step_export.bas`, `STEP_batch_generator.swp` | SolidWorks VBA batch STEP exporter. `.bas` is editable source; `.swp` is the SolidWorks binary container—mirror `.bas` changes manually into `.swp` via SolidWorks if modified. |

---

## 5. Domain & Engineering Conventions

### Unit System (Critical)
- **Geometry & Mesh (`.step`, `.inp`):** millimeters (`mm`).
- **Master Workbook `Materials` sheet:** `Density_kg_m^3` (`kg/m³`), `Youngs_modulus_GPa` (`GPa`), `Poissons_ratio` (legacy aliases `Density`, `Density_ton_m^3`, `Youngs_modulus` are normalized automatically).
- **CalculiX Deck (N–mm–tonne consistent system in `ccx_solver.build_frequency_deck`):**
  - `E [MPa] = Youngs_modulus_GPa * 1e3`
  - `rho [tonne/mm³] = Density_kg_m^3 * 1e-12`
- **CalculiX Outputs (`.dat`, `.frd`):** frequencies in `Hz`, raw eigenvector displacements in `mm`, raw stresses (when requested) in `MPa`.
- **Amplitude Scaling Subtlety:** `spin_input_amplitude` (`session.input_amplitude`) is in **µm**. In `ccx_results_parser.select_longitudinal_mode()`, `scaling_factor = abs(input_amplitude / raw_base_mean)` scales raw displacements directly into `µm` because the raw `mm` units cancel. **When scaling stresses (`MPa`) against physical displacement (`µm`)**, you must first convert `raw_base_mean` from `mm` to `µm` (`* 1000.0`) so the dimensionless scale factor is `alpha = input_amplitude_um / (abs(raw_base_mean_mm) * 1000.0)`.

### Coordinate Axis & Semantic Roles
- The longitudinal acoustic axis is **Y**: `YMAX` = Tip, `YMIN` = Base.
- If semantic roles are picked in Tab 1, `meshing.py` matches CAD faces by bounding-box centroid proximity; missing `YMAX`/`YMIN` faces fall back to flat faces at global Y extrema. `ccx_solver.py` can also synthesize missing `YMIN`/`YMAX` `*NSET`s from node Y-extrema.
- `select_longitudinal_mode()` ranks modes by a dimensionless fitness score (`0.0` to `1.2`) based on axial participation `R_a = |Uy| / ||U||`, uniformity penalty `exp(-3.0 * std(Uy) / |Uy|)` on both tip and base, and a `1.2x` anti-phase bonus (`Uy_tip * Uy_base < 0`). *(Note: the function docstring still describes an older formula; trust the code.)*

### Master Workbook Schema
- **Sheet 0 (Geometry source, SolidWorks Design Table layout):** Row 2 = headers (cleaned by splitting at `@`, e.g., `D1@Sketch1` → `D1`), Row 4+ = data, Column 0 = `Model_name`. Blank, `nan`, and `DEFAULT` rows are filtered out.
- **Simulation Sheets (`Meshing_Parameters`, `Materials`, `Step_Configuration`):** Exact `Model_name` match takes precedence; `Model_name == "*"` is the wildcard fallback row.
- `Meshing_Parameters` template columns `Algorithm`, `Recombine`, and `Msh_version` are generated by `augment_master_workbook.py` but are not currently consumed by `meshing.py`.
- `Step_Configuration` currently supports `Step_type = "frequency"` only.

### Abaqus / CalculiX File Format Rules
- **`.inp` decks:** Strictly **1-based** node and element IDs; maximum **16 comma-separated integers per line** in `*NSET`/`*ELSET` blocks; no empty set blocks; no trailing commas on final lines. `meshio` element type `C3D10MH` must be rewritten to `C3D10` for CCX. `ELSET=Volume1` is required for `*SOLID SECTION`.
- **`.frd` results:** Fixed-width Fortran ASCII output where negative numbers often touch adjacent numbers with zero whitespace (e.g. `1.50000E+02-2.50000E+01`) and exponents may use `D`/`d`. Never parse `.frd` numeric rows with plain `str.split()`; use fixed-width slicing or compiled float regexes (`modal_inspection_service.py`).

---

## 6. Coding Conventions & Known Gotchas

1. **Dual Import Pattern:** Every script in `GUI_code/scripts/` uses:
   ```python
   try:
       from scripts.module import symbol
   except ModuleNotFoundError:
       from module import symbol
   ```
   Preserve this pattern so modules work regardless of whether `GUI_code/` or `GUI_code/scripts/` is on `sys.path`.
2. **Dynamic `.ui` Binding & Widget Access:** `MainWindow` loads `MainWindow.ui` into `self.ui` via `QUiLoader` and reparents `centralWidget` onto `MainWindow`. Widgets are accessed as `self.ui.<objectName>` (controllers guard optional widgets with `hasattr(self.ui, ...)`). Several legacy/optional widget names checked in controllers (`btn_run`, `btn_abort_sim`, `progress_bar`, `lbl_status`, `label_sim_timer`, `btn_load_3d`, `tabWidget`) do not exist in the current `MainWindow.ui`.
3. **Table Column Formatting Trap (`analytics_table_model.py`):** `DataFrameTableModel.data()` formats **every column with `index.column() >= 3`** via `f"{float(value):.1f}"`. If adding string columns (e.g. `Yield_Status`) or integer columns beyond index 2, update formatting logic carefully (strings fall through on `ValueError`, but integers like `Mode_Index` are formatted with `.1f`!).
4. **Unicode Micro Sign in Column Names:** Canonical columns in `ccx_results_parser.SUMMARY_COLUMNS` and `AnalyticsController.CORE_TABLE_COLUMNS` use `µ` (`YMAX_Mean_µm`, `YMIN_Mean_µm`, `Tip_Std_µm`, `Base_Std_µm`). Match exact characters when referencing DataFrame columns.
5. **Disk-Driven Status & File Extension Asymmetries:**
   - Job status is inferred from disk: `Solved` (`_mesh.inp` + `.frd`), `Meshed` (`_mesh.inp` only), `Pending` (neither).
   - `SetupController` and `MeshGenerationWorker` discover `*.step`/`*.STEP`, whereas `AnalyticsController._find_step_models()` also includes `*.stp`/`*.STP`.
   - `AnalyticsController._build_results_rows_from_disk()` checks `<Model_name>_mesh.inp` (not `<Model_name>_mesh_fallback_o1.inp`), whereas `CCXSolverWorker` checks both.
   - `analytics_service._find_master_workbook()` ignores Excel lock files (`~$*.xlsx`), whereas `SetupController.run_augmentation()` and `_find_single_master_workbook()` use plain `glob("*.xlsx")`.
6. **Threading, VTK & Qt Safety:**
   - Never invoke Gmsh or CalculiX on the GUI thread; keep them inside `QThread` workers.
   - Always stop `self.widgets.animation_timer` before changing table rows, modes, or meshes (as done in `ResultsController`).
   - Always close PyVista `QtInteractor` instances (`self.widgets.plotter`, `self.widgets.plotter_results`) before `MainWindow` teardown to prevent VTK OpenGL crashes.
   - Call `modal_inspection_service.clear_inspection_cache()` when re-running solves so stale cached meshes/modes are invalidated.
7. **Worker Status Protocol:** `MeshGenerationWorker` and `CCXSolverWorker` update Tab 2 row statuses via pipe-delimited `status_updated` messages (`MESH|<STAGE>|<payload>`, `SOLVE|<STAGE>|<payload>`). Keep stage prefixes intact when modifying worker messages.

---

## 7. Planned Roadmap (`Phase_by_phase_intructions/`)

Four detailed specification files define a future **VHCF Specimen Designer** upgrade (currently **not implemented**):
- **Phase 1:** `specimen_type`, `yield_strength`, `active_scalar` in `ProjectSession` + Setup/3D Results UI controls.
- **Phase 2:** 3D AABB gauge-volume selection (`pyvista` box widget) → `*ELSET, ELSET=GAUGE_VOL` & `*NSET, NSET=GAUGE_VOL_NODES` in `meshing.py` + `*EL FILE` `S` stress output in `ccx_solver.py`.
- **Phase 3:** `.frd` stress parsing, Von Mises & Max Principal stress, gauge-averaged `Stress_Gain [MPa/µm]`, `Max_Stress [MPa]`, `Yield_Status`, and specimen-specific dynamic Analytics columns (preserving `select_longitudinal_mode` and Excel `df_merged` geometry columns).
- **Phase 4:** Multi-field 3D stress colormaps, right-click 1D line sampling & 2D plane slicing, and decoupled floating `StressPlotPopup` windows.

### Spec-vs-Codebase Mapping Notes (Read Before Implementing Any Phase)
When implementing the Phase 1–4 specs, reconcile these existing codebase names rather than breaking existing APIs:
- `ProjectSession` resets via `clear_project_data()` (specs refer to `reset()` / `clear()`).
- `MainWindow` exposes loaded `.ui` widgets on `window.ui.<objectName>` and has no `create_main_window()` factory yet.
- `SetupController` accesses the 3D viewport at `self.widgets.plotter` (specs refer to `self.plotter`).
- The selected-row mesh worker is `MeshGenerationWorker` in `scripts/app/workers/mesh_worker.py` (specs call it `MeshWorker`), and `CCXSolverWorker` lives in `scripts/ccx_solver.py`.
- Always honor each phase's preservation directive: do not alter SolidWorks export, core Gmsh meshing, CCX execution, `select_longitudinal_mode()`, or Excel geometry `df_merged` merging unless explicitly specified.
