import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import pandas as pd


def _normalize_gauge_bounds(bounds: Sequence[float]) -> list[float]:
    """Validate and normalize an AABB into [xmin, xmax, ymin, ymax, zmin, zmax]."""
    if bounds is None or isinstance(bounds, (str, bytes)):
        raise ValueError("gauge_bounds must be a 6-element sequence of finite numbers.")
    try:
        items = list(bounds)
    except TypeError as exc:
        raise ValueError("gauge_bounds must be a 6-element sequence of finite numbers.") from exc

    if len(items) != 6:
        raise ValueError(f"gauge_bounds must contain exactly 6 values, got {len(items)}.")

    vals: list[float] = []
    for item in items:
        try:
            num = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"gauge_bounds entry {item!r} is not numeric.") from exc
        if not math.isfinite(num):
            raise ValueError("gauge_bounds entries must be finite numbers.")
        vals.append(num)

    xmin, xmax = sorted((vals[0], vals[1]))
    ymin, ymax = sorted((vals[2], vals[3]))
    zmin, zmax = sorted((vals[4], vals[5]))

    if not (xmin < xmax and ymin < ymax and zmin < zmax):
        raise ValueError(
            "gauge_bounds must have strictly positive extents along X, Y, and Z."
        )

    return [xmin, xmax, ymin, ymax, zmin, zmax]


@dataclass
class ProjectSession:
    # Project paths
    project_dir: Optional[str] = None
    master_workbook_path: Optional[str] = None

    # Dataframes
    df_mesh: Optional[pd.DataFrame] = None
    df_material: Optional[pd.DataFrame] = None
    df_step: Optional[pd.DataFrame] = None
    df_results: Optional[pd.DataFrame] = None
    df_merged: Optional[pd.DataFrame] = None
    job_table_df: Optional[pd.DataFrame] = None

    # UI and runtime state
    semantic_roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_picked_info: Optional[dict[str, Any]] = None
    selected_result_row: Optional[dict[str, Any]] = None
    base_result_mesh: Any = None
    result_camera_initialized: bool = False
    current_model_name: Optional[str] = None
    current_mode_index: Optional[int] = None
    current_render_status: Optional[str] = None
    available_modes_dict: dict[int, float] = field(default_factory=dict)
    input_amplitude: float = 1.0
    specimen_type: str = "Longitudinal Specimen"
    yield_strength: float = 300.0
    active_scalar: str = "Displacement Magnitude (U)"
    gauge_bounds: Optional[list[float]] = None

    is_solving: bool = False
    animation_phase: float = 0.0
    sim_start_time: float = 0.0

    # Transitional runtime references
    worker: Any = None
    mesh_worker: Any = None
    ccx_worker: Any = None
    table_model: Any = None
    plotter: Any = None
    plotter_results: Any = None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "yield_strength":
            numeric_value = float(value)
            if not math.isfinite(numeric_value) or numeric_value < 0.0:
                raise ValueError("yield_strength must be a finite non-negative number.")
            value = numeric_value
        elif name == "gauge_bounds" and value is not None:
            value = _normalize_gauge_bounds(value)
        super().__setattr__(name, value)

    def set_gauge_bounds(self, bounds: Sequence[float]) -> list[float]:
        """Validate, normalize, and store AABB bounds [xmin, xmax, ymin, ymax, zmin, zmax]."""
        normalized = _normalize_gauge_bounds(bounds)
        self.gauge_bounds = normalized
        return list(normalized)

    def clear_project_data(self) -> None:
        """Reset project-dependent data while keeping the session object alive."""
        self.project_dir = None
        self.master_workbook_path = None

        self.df_mesh = None
        self.df_material = None
        self.df_step = None
        self.df_results = None
        self.df_merged = None
        self.job_table_df = None

        self.semantic_roles.clear()
        self.last_picked_info = None

        self.selected_result_row = None
        self.base_result_mesh = None
        self.result_camera_initialized = False
        self.current_model_name = None
        self.current_mode_index = None
        self.current_render_status = None
        self.available_modes_dict.clear()

        self.is_solving = False
        self.animation_phase = 0.0
        self.sim_start_time = 0.0
        self.input_amplitude = 1.0
        self.specimen_type = "Longitudinal Specimen"
        self.yield_strength = 300.0
        self.active_scalar = "Displacement Magnitude (U)"
        self.gauge_bounds = None

        self.worker = None
        self.mesh_worker = None
        self.ccx_worker = None
        self.table_model = None
