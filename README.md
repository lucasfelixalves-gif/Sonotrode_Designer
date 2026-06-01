# Sonotrode Designer - Installation Guide

**Sonotrode Designer** is a multithreaded PySide6 desktop application for orchestrating CAD (SolidWorks/STEP), Meshing (Gmsh), and FEA (CalculiX) workflows. This guide provides step-by-step instructions for setting up and deploying the application.

---

## Prerequisites

Before installing Sonotrode Designer, ensure the following are available on your system:

### 1. **Miniforge/Mamba**
   - Download and install [Miniforge](https://github.com/conda-forge/miniforge) (includes Mamba and Conda)
   - Verify installation by running:
     ```bash
     mamba --version
     conda --version
     ```

### 2. **SolidWorks** (Optional, for STEP export)
   - Must be installed to export STEP geometry files
   - The macro `solidworks_step_export.bas` is provided to automate batch exports
   - See [SolidWorks Workflow](#solidworks-workflow) section below

### 3. **CalculiX (CCX)** Binaries
   - Download **ccx.exe** and its associated .dll files
   - Windows builds are available from:
     - [CalculiX Parametric Institute](http://www.calculix.de/) (official source)
     - Or pre-compiled Windows binaries from community sources
   - **Critical:** See [CCX Setup](#ccx-setup-critical) for proper installation

---

## Environment Setup

### Step 1: Create the Conda Environment

Navigate to the `GUI_code/` directory (where `environment.yml` is located) and run:

```bash
mamba env create -f environment.yml
```

This creates an environment named `sonotrode_lab` with all required dependencies:
- Python 3.11
- Scientific stack: NumPy, SciPy, Matplotlib, Pandas
- FEA/Meshing: Gmsh, Meshio, PyVista (with native .frd support)
- GUI: PySide6
- Excel support: OpenPyXL

### Step 2: Activate the Environment

```bash
conda activate sonotrode_lab
```

### Step 3: Verify Installation (Smoke Test)

Run a quick Python check to confirm all critical modules load:

```bash
python -c "import gmsh; import pyvista; import PySide6; import meshio; print('✓ All critical modules loaded successfully')"
```

**Expected output:** `✓ All critical modules loaded successfully`

If any import fails, see the [Troubleshooting](#troubleshooting) section.

---

## CCX Verification/Setup (CRITICAL)

The CalculiX solver is required for running FEA simulations. It should be distributed with the rest of the code.
If `bin/` does not exist, follow these steps carefully:

### Step 1: Create the `bin/` Directory

At the **repository root** (the folder containing `GUI_code/` and `bin/`), create a new folder named `bin/`:

```
your_project_root/
├── bin/                     ← Create this folder
├── GUI_code/
│   ├── environment.yml
│   └── scripts/
│       ├── main.py
│       ├── ccx_solver.py
│       └── ...
└── README.md
```

### Step 2: Place CCX Binaries

Copy the following files into the `bin/` folder:
- **ccx.exe** — The CalculiX executable
- **All associated .dll files** — Windows runtime dependencies (e.g., `libiomp5md.dll`, `libmkl_core.dll`, etc.)

Example structure:
```
bin/
├── ccx.exe
├── libiomp5md.dll
├── libmkl_core.dll
├── libmkl_intel_lp64.dll
├── libmkl_sequential.dll
└── ... (other required .dll files)
```

### Step 3: Verification

The application **automatically detects** and uses the local `bin/ccx.exe` path. No additional configuration is needed. When you run a simulation, the solver will execute from this location.

**Note:** If CCX binaries are not found in the `bin/` folder, solver execution will fail with an error message indicating the missing path.

---

## SolidWorks Workflow

If using SolidWorks to design geometries, follow this process to export STEP files:

### Step 1: Prepare Your SolidWorks Assembly

- Ensure your assembly is fully constrained and saved
- Verify that parametric dimensions are properly defined (these will become design variables in the optimization loop)

### Step 2: Load the Macro

In SolidWorks, load the provided macro:
- **File:** `solidworks_step_export.bas` (located in `GUI_code/scripts/`)
- **Alternative:** `STEP_batch_generator.swp` (SolidWorks macro template)

Steps to load:
1. Open SolidWorks
2. Go to **Tools → Macros → Edit Macro**
3. Open `solidworks_step_export.bas`
4. Click **Run** to execute

### Step 3: Export to 02_Geometry_STEP

The macro will export STEP files to the designated output folder. Ensure these files are placed in:

```
project_root/
├── 02_Geometry_STEP/
│   ├── design_variant_1.step
│   ├── design_variant_2.step
│   └── ...
```

The application expects STEP files (.step or .stp) in this directory for meshing and FEA.

---

## GUI Workflow

### Launching the Application

From the project root (with `sonotrode_lab` environment activated), run:

```bash
python scripts/main.py
```

A PySide6 window will open with three tabs:
1. **Setup** — Configure geometry, mesh, material, and step configurations
2. **Analytics** — Execute batch meshing and FEA solvesa and View results and performance metrics
3. **Modal Inspection** — Visualize mode shapes and deformations

### Basic Workflow Steps

#### Tab 1: Setup Phase
1. **Ensure Master Workbook Exists**
   - Place an Excel file (`.xlsx`) in `01_Master_Config/`
   - This workbook defines design parameters and their values
   - Format: Row 2 has headers (e.g., D1@Sketch1, D2@Sketch1, ...), Row 4+ has model data

2. **Run Augment Master Workbook**
   - Click "Augment Master Workbook" to validate and enhance the workbook
   - This derives additional computational parameters needed for analysis

3. **Verify STEP Files**
   - Confirm that STEP files exist in `02_Geometry_STEP/`
   - The app matches files to rows in the master workbook by model name

4. **Assign Role Configuration**
   - Select roles for different geometry sections (e.g., "Active Horn", "Backing Material", etc.)
   - These roles control material properties and boundary conditions

#### Tab 2: Analytics - Run Phase
1. **Select Target Models**
   - Choose which models to process from the table

2. **Run Batch Processing**
   - Click "Mesh Selected Items" and "Run CCX" to execute, respectively:
     - Meshing (Gmsh) → generates `.inp` files in `03_Meshes_INP/`
     - Modal FEA (CalculiX) → generates `.frd` and `.dat` files in `04_Results_CCX/`
     - Status messages indicate each stage (meshing, solving, parsing results)
   
#### Tab 2: Analytics - Results Phase
1. **View Results Summary**
   - Frequency, displacement metrics, and uniformity scores are populated
   - Download results as `Results_Summary.xlsx`

2. **Interactive Plots**
   - Hover over data points to see model details
   - Visualize relationships between design parameters and performance metrics

#### Tab 3: Modal Inspection Phase
1. **Select a Solved Model**
   - Choose from models with completed FEA results

2. **Choose Mode and Visualization**
   - View deformed geometry at different mode shapes
   - Inspect node displacement patterns

---

## Troubleshooting

### Issue 1: `ImportError: cannot import name 'gmsh'`

**Symptom:** The application fails to start with "ImportError: cannot import name 'gmsh'"

**Solution:**
```bash
# Deactivate and reactivate the environment
conda deactivate
conda activate sonotrode_lab

# If still failing, reinstall gmsh and python-gmsh
pip uninstall gmsh pyvista -y
pip install --upgrade gmsh pyvista>=0.48

# Then try starting the app again
python scripts/main.py
```

### Issue 2: Solved Models Not Showing Results (Missing .frd Files)

**Symptom:** The Analytics tab shows "Status" as "DONE" but no frequency/metric data appears

**Cause:** CalculiX did not produce `.frd` result files, often because:
- CCX binaries were not found
- The mesh file was malformed
- The FEA analysis failed silently

**Solution:**
1. Check that CCX binaries exist:
   ```bash
   ls -la bin/ccx.exe  # Should exist
   ```

2. Review the solver log file:
   ```bash
   # Check the most recent log in 04_Results_CCX/
   cat 04_Results_CCX/*.log
   ```

3. Look for error messages indicating mesh or CCX issues

4. Verify mesh files were generated:
   ```bash
   ls -la 03_Meshes_INP/
   ```

### Issue 3: CCX Immediately Aborts with No Output

**Symptom:** Solver runs but fails instantly (returncode != 0) with no error message in the log

**Cause:** CCX executable not found or incompatible with system

**Solution:**
1. **Verify bin/ folder exists and is in the correct location:**
   ```bash
   # Should show ccx.exe in the bin/ folder at project root
   ls -la bin/ccx.exe
   ```

2. **Test CCX directly:**
   ```bash
   cd bin
   ./ccx.exe  # On Windows: ccx.exe
   ```
   - If you see "Usage: ccx ..." then CCX is working
   - If you get "not found" or a DLL error, check that all .dll files are in `bin/`

3. **Ensure all required DLL dependencies are present:**
   - Common missing DLLs: `libiomp5md.dll`, MKL libraries
   - These must be in the `bin/` folder alongside `ccx.exe`

4. **Re-check the path in the application:**
   - Open `scripts/ccx_solver.py` and verify the path resolution logic points to `bin/ccx.exe`

### Issue 4: Mesh Generation Fails (Gmsh Errors)

**Symptom:** Meshing step fails or produces malformed `.inp` files

**Solution:**
1. Verify STEP file is valid:
   ```bash
   python -c "import meshio; mesh = meshio.read('02_Geometry_STEP/model.step'); print('Valid')"
   ```

2. Check Gmsh version:
   ```bash
   python -c "import gmsh; gmsh.initialize(); print(gmsh.__version__); gmsh.finalize()"
   ```

3. Inspect the mesh quality in Modal Inspection tab or use an external viewer

---

## Directory Structure Overview

After setup and first run, your project structure will look like:

```
project_root/
├── 01_Master_Config/
│   └── master_workbook.xlsx       ← Your design parameters
├── 02_Geometry_STEP/
│   ├── model_1.step
│   ├── model_2.step
│   └── ...
├── 03_Meshes_INP/
│   ├── model_1_mesh.inp           ← Generated by Gmsh
│   ├── model_2_mesh.inp
│   └── ...
├── 04_Results_CCX/
│   ├── model_1.frd                ← Generated by CalculiX
│   ├── model_1.dat
│   ├── model_1.log
│   └── ...
├── bin/
│   ├── ccx.exe                    ← CalculiX solver
│   ├── libiomp5md.dll
│   └── ... (other DLLs)
├── scripts/
│   ├── main.py
│   ├── ccx_solver.py
│   ├── meshing.py
│   └── ...
├── environment.yml
└── README.md                       ← This file
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Create environment | `mamba env create -f environment.yml` |
| Activate environment | `conda activate sonotrode_lab` |
| Start application | `python scripts/main.py` |
| Test gmsh import | `python -c "import gmsh; print('OK')"` |
| Verify CCX exists | `ls -la bin/ccx.exe` |
| Test CCX binary | `bin/ccx.exe` |
| Check PyVista version | `python -c "import pyvista; print(pyvista.__version__)"` |

---

## Support & Resources

- **CalculiX Documentation:** http://www.calculix.de/
- **Gmsh Documentation:** https://gmsh.info/
- **PyVista Documentation:** https://docs.pyvista.org/
- **PySide6 Documentation:** https://doc.qt.io/qtforpython/

---

**Version:** 1.0  
**Last Updated:** May 2026
