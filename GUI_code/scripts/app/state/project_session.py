from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


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

        self.worker = None
        self.mesh_worker = None
        self.ccx_worker = None
        self.table_model = None
