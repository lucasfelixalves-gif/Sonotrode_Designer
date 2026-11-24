# Phase 1: State Management & Setup UI Specification

> **⚠️ CRITICAL AI DIRECTIVE: STRICT PRESERVATION OF INDEPENDENT BEHAVIORS**
> Do not alter any behavior, function, signal, or script that is not strictly related to the changes requested in this document. Existing pipelines—especially SolidWorks STEP export handling, the general Gmsh meshing pipeline, CalculiX deck execution, and the logic that merges geometrical parameters into the final pandas DataFrame—must remain completely untouched. Follow the existing Model-View-Controller (MVC) architecture strictly.

---

## 1. Objective & Intended Behavior

The goal of Phase 1 is to expand the application's state model and graphical user interface (Setup Tab and 3D Results Tab) to capture and persist **Very High Cycle Fatigue (VHCF)** specimen constraints without altering any underlying FEA solver or parsing logic yet.

### Intended User & System Behavior:
1. **Specimen Class Selection:** On the **Setup Tab**, the user can select the physical geometry class of the specimen being tested via a dropdown menu (`combo_specimen_type`). The available options are:
   * `Longitudinal Specimen` (Default)
   * `Disc Specimen (Biaxial)`
   * `Flat/Thin-Walled Specimen`
2. **Material Yield Limit Definition:** On the **Setup Tab**, alongside the existing excitation amplitude input, the user can input the material's macroscopic yield strength ($\sigma_{yield}$) in Megapascals (`spin_yield_strength`), defaulting to `300.0 MPa`.
3. **3D Scalar Field Toggle (UI Scaffolding):** On the **3D Results Tab** (Modal Inspection), a dropdown menu (`combo_active_scalar`) is visible above/near the 3D viewer, allowing the user to select between:
   * `Displacement Magnitude (U)` (Default)
   * `Displacement Y (U2)`
   * `Von Mises Stress`
   * `Max Principal Stress`
   *(Note: In Phase 1, this dropdown only needs to exist in the UI and update state/log changes; 3D mesh colormap re-rendering is deferred to later phases).*
4. **State Persistence & Reset:** Any changes made to `combo_specimen_type` or `spin_yield_strength` immediately update the centralized `ProjectSession` state object. When a user clicks "Create New Project" or "Load Project" (triggering a session reset), these values cleanly revert to their defaults (`"Longitudinal Specimen"` and `300.0`).

---

## 2. Required AI Agent Skills & Domain Knowledge

Before modifying the codebase, the AI agent executing this phase must apply the following technical skills and architectural conventions:

* **PySide6 / Qt Designer XML Schema (`MainWindow.ui`):** Ability to read and safely edit Qt `.ui` XML files without corrupting widget hierarchies, layout geometries, or existing `objectName` bindings. Understanding of `QComboBox`, `QDoubleSpinBox`, `QLabel`, and `QFormLayout`/`QHBoxLayout` structures in PySide6.
* **MVC Decoupling in Python:** Strict separation of concerns:
  * **Model (`ProjectSession`):** Pure Python data/state container. Must *never* import `PySide6.QtWidgets`.
  * **View (`MainWindow.ui`):** Declarative UI layout loaded via `QUiLoader` or compiled UI class. Contains zero business logic.
  * **Controller (`SetupController`):** Connects Qt widget signals (`currentTextChanged`, `valueChanged`) to state mutations and handles logging.
* **Defensive Signal Binding:** Ensuring UI widgets are initialized with the current `ProjectSession` values *before* or *during* controller startup so the View and Model are never out of sync on launch.
* **Pytest & Headless Qt Testing (`pytest-qt` or `QApplication`):** Writing automated unit and integration tests that instantiate `ProjectSession` and `MainWindow` in a headless environment (`QT_QPA_PLATFORM=offscreen`) to verify signal-slot execution without manual clicking.

---

## 3. Step-by-Step Implementation Plan

Execute these steps in exact sequential order.

### Step 1.1: Update the State Model
* **Target File:** `scripts/app/state/project_session.py`
* **Action:**
  1. Locate the `ProjectSession` class initialization (`__init__`) and its reset method (e.g., `reset()` or `clear()`).
  2. Add the following attributes with type hints and default values:
     ```python
     self.specimen_type: str = "Longitudinal Specimen"
     self.yield_strength: float = 300.0
     self.active_scalar: str = "Displacement Magnitude (U)"
     ```
  3. Ensure the project reset method explicitly resets `specimen_type` to `"Longitudinal Specimen"`, `yield_strength` to `300.0`, and `active_scalar` to `"Displacement Magnitude (U)"`.
  4. *(Optional but recommended)* Add basic validation or property setters if `ProjectSession` uses `@property` decorators for existing fields, ensuring `yield_strength` cannot be negative.

### Step 1.2: Update the View (UI Layout)
* **Target File:** `scripts/MainWindow.ui`
* **Action (Setup Tab):**
  1. Locate the configuration/input group box in the **Setup Tab** where the input amplitude (`µm`) or material/step parameters are defined.
  2. Add a `QLabel` with text `"Specimen Type:"` and a `QComboBox` with `objectName="combo_specimen_type"`.
  3. Populate `combo_specimen_type` with exact item strings:
     * `Longitudinal Specimen`
     * `Disc Specimen (Biaxial)`
     * `Flat/Thin-Walled Specimen`
  4. Add a `QLabel` with text `"Material Yield Strength:"` and a `QDoubleSpinBox` with `objectName="spin_yield_strength"`.
  5. Configure `spin_yield_strength` properties:
     * `minimum`: `0.0`
     * `maximum`: `5000.0`
     * `decimals`: `1`
     * `singleStep`: `10.0`
     * `value`: `300.0`
     * `suffix`: `" MPa"`
* **Action (3D Results / Modal Inspection Tab):**
  1. Locate the top toolbar or control layout above the PyVista 3D render widget in the **Modal Inspection / 3D Results Tab**.
  2. Add a `QLabel` with text `"Active Scalar Field:"` and a `QComboBox` with `objectName="combo_active_scalar"`.
  3. Populate `combo_active_scalar` with exact item strings:
     * `Displacement Magnitude (U)`
     * `Displacement Y (U2)`
     * `Von Mises Stress`
     * `Max Principal Stress`

### Step 1.3: Update the Setup Controller
* **Target File:** `scripts/app/controllers/setup_controller.py`
* **Action:**
  1. Locate where UI widgets are referenced and bound (typically in `__init__` or `_connect_signals()`).
  2. Synchronize initial UI state from `self.session`:
     ```python
     self.ui.combo_specimen_type.setCurrentText(self.session.specimen_type)
     self.ui.spin_yield_strength.setValue(self.session.yield_strength)
     ```
  3. Connect widget signals to dedicated handler methods:
     ```python
     self.ui.combo_specimen_type.currentTextChanged.connect(self._on_specimen_type_changed)
     self.ui.spin_yield_strength.valueChanged.connect(self._on_yield_strength_changed)
     ```
  4. Implement the handler methods with terminal/logger verification:
     ```python
     def _on_specimen_type_changed(self, text: str) -> None:
         self.session.specimen_type = text
         print(f"[SetupController] Specimen type updated to: {self.session.specimen_type}")

     def _on_yield_strength_changed(self, value: float) -> None:
         self.session.yield_strength = float(value)
         print(f"[SetupController] Yield strength updated to: {self.session.yield_strength} MPa")
     ```
  5. Locate the method that handles loading/creating a new project (where `self.session.reset()` is called) and ensure the UI widgets (`combo_specimen_type` and `spin_yield_strength`) refresh to reflect the reset session values (using `blockSignals(True/False)` if necessary to prevent redundant log spam).

### Step 1.4: Bind Active Scalar Dropdown (Minimal Scaffolding)
* **Target File:** `scripts/app/controllers/results_controller.py` (or the controller managing the Modal Inspection tab)
* **Action:**
  1. Bind `self.ui.combo_active_scalar.currentTextChanged` to update `self.session.active_scalar` and print `[ResultsController] Active scalar set to: {text}`.
  2. Do **not** alter any PyVista rendering pipelines yet.

---

## 4. Verification & Automated Tests

To confirm Phase 1 is complete and regression-free, create a test script `tests/test_phase1_setup_state.py` and run it using `pytest` in the `sonotrode_lab` conda environment.

### 4.1. Automated Test Suite (`tests/test_phase1_setup_state.py`)

```python
import os
import sys
import pytest
from PySide6.QtWidgets import QApplication

# Ensure scripts directory is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app.state.project_session import ProjectSession

# Set offscreen platform for headless CI/agent testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_project_session_defaults_and_reset():
    """Verify ProjectSession initializes and resets Phase 1 attributes properly."""
    session = ProjectSession()
    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == 300.0
    assert session.active_scalar == "Displacement Magnitude (U)"

    # Mutate state
    session.specimen_type = "Disc Specimen (Biaxial)"
    session.yield_strength = 450.5
    session.active_scalar = "Von Mises Stress"

    # Reset state (adjust method name if ProjectSession uses clear() instead of reset())
    if hasattr(session, "reset"):
        session.reset()
    elif hasattr(session, "clear"):
        session.clear()
    else:
        pytest.fail("ProjectSession lacks a reset() or clear() method.")

    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == 300.0
    assert session.active_scalar == "Displacement Magnitude (U)"


def test_ui_widgets_and_controller_bindings(qapp):
    """Verify UI widgets exist with exact objectNames and bind properly to ProjectSession."""
    # Import main window builder/loader used by scripts/main.py
    from main import create_main_window  # Adjust if main.py uses a different entry function

    window, session = create_main_window()

    # 1. Verify Setup Tab Widgets exist
    assert hasattr(window, "combo_specimen_type"), "Missing combo_specimen_type in MainWindow.ui"
    assert hasattr(window, "spin_yield_strength"), "Missing spin_yield_strength in MainWindow.ui"
    assert hasattr(window, "combo_active_scalar"), "Missing combo_active_scalar in MainWindow.ui"

    # 2. Verify ComboBox Options
    specimen_items = [window.combo_specimen_type.itemText(i) for i in range(window.combo_specimen_type.count())]
    assert specimen_items == [
        "Longitudinal Specimen",
        "Disc Specimen (Biaxial)",
        "Flat/Thin-Walled Specimen",
    ]

    scalar_items = [window.combo_active_scalar.itemText(i) for i in range(window.combo_active_scalar.count())]
    assert scalar_items == [
        "Displacement Magnitude (U)",
        "Displacement Y (U2)",
        "Von Mises Stress",
        "Max Principal Stress",
    ]

    # 3. Verify SpinBox Constraints
    assert window.spin_yield_strength.suffix() == " MPa"
    assert window.spin_yield_strength.value() == 300.0

    # 4. Simulate User Interaction -> Verify State Updates
    window.combo_specimen_type.setCurrentText("Flat/Thin-Walled Specimen")
    assert session.specimen_type == "Flat/Thin-Walled Specimen"

    window.spin_yield_strength.setValue(620.0)
    assert session.yield_strength == 620.0

    window.combo_active_scalar.setCurrentText("Max Principal Stress")
    assert session.active_scalar == "Max Principal Stress"

    window.close()
```

### 4.2. Manual Visual Smoke Check
After automated tests pass, execute:
```bash
python scripts/main.py
```
1. Confirm the application launches with zero `AttributeError` or XML parsing warnings.
2. Visually inspect the **Setup Tab** to ensure `combo_specimen_type` and `spin_yield_strength` align cleanly without overlapping existing buttons or text.
3. Change both inputs and confirm the console outputs:
   * `[SetupController] Specimen type updated to: Disc Specimen (Biaxial)`
   * `[SetupController] Yield strength updated to: 450.0 MPa`
4. Switch to the **Modal Inspection / 3D Results Tab** and verify `combo_active_scalar` is visible and responsive.