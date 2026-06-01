"""Parse CalculiX modal outputs and build summary metrics.

This module extracts YMIN/YMAX node sets from mesh INP files, reads modal
Y-displacements from CCX DAT files, selects the longitudinal mode, and computes
summary metrics for UI and report export workflows.
"""

import math
import re
import statistics
from typing import Dict, Iterable, Set, Tuple


SUMMARY_COLUMNS = [
    "Model_name",
    "Number_of_nodes",
    "Mode_Index",
    "Frequency_Hz",
    "YMAX_Mean_µm",
    "YMIN_Mean_µm",
    "Gain_Ratio",
    "Tip_Std_µm",
    "Base_Std_µm",
]

_FLOAT_RE = r"[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[Ee][+-]?\d+)?"
_FREQ_ROW_RE = re.compile(
    rf"^\s*(\d+)\s+({_FLOAT_RE})\s+({_FLOAT_RE})\s+({_FLOAT_RE})\s+({_FLOAT_RE})\s*$"
)
_EIGEN_MODE_RE = re.compile(
    r"E\s*I\s*G\s*E\s*N\s*V\s*A\s*L\s*U\s*E\s*N\s*U\s*M\s*B\s*E\s*R\s*(\d+)",
    re.IGNORECASE,
)
_DISP_SET_RE = re.compile(
    r"displacements\s*\(vx,vy,vz\)\s*for\s*set\s+([A-Za-z0-9_]+)",
    re.IGNORECASE,
)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_mesh_node_sets(mesh_path: str, set_names: Iterable[str] = ("YMIN", "YMAX")) -> Tuple[Dict[str, Set[int]], int]:
    """Return node IDs for requested NSET names and total *NODE count."""
    targets = {str(name).strip().upper() for name in set_names}
    node_sets = {name: set() for name in targets}
    node_coords = {}

    in_node_block = False
    active_set = None
    active_generate = False
    total_nodes = 0

    with open(mesh_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("*"):
                upper = line.upper()

                in_node_block = upper.startswith("*NODE")
                active_set = None
                active_generate = False

                if upper.startswith("*NSET"):
                    match = re.search(r"\bNSET\s*=\s*([^,\s]+)", upper)
                    if match:
                        candidate = match.group(1).strip().upper()
                        if candidate in targets:
                            active_set = candidate
                            active_generate = "GENERATE" in upper
                continue

            if in_node_block:
                parts = [tok.strip() for tok in line.split(",")]
                first = parts[0] if parts else ""
                try:
                    nid = int(first)
                except ValueError:
                    pass
                else:
                    total_nodes += 1
                    if len(parts) >= 4:
                        try:
                            node_coords[nid] = (
                                float(parts[1]),
                                float(parts[2]),
                                float(parts[3]),
                            )
                        except ValueError:
                            pass

            if active_set is None:
                continue

            numbers = []
            for token in line.split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    numbers.append(int(token))
                except ValueError:
                    continue

            if active_generate:
                for idx in range(0, len(numbers), 3):
                    chunk = numbers[idx: idx + 3]
                    if len(chunk) != 3:
                        continue
                    start, end, step = chunk
                    if step == 0:
                        continue
                    stop = end + (1 if step > 0 else -1)
                    for nid in range(start, stop, step):
                        node_sets[active_set].add(nid)
            else:
                node_sets[active_set].update(numbers)

    # Fallback when mesh export does not include explicit YMIN/YMAX NSET cards.
    if node_coords and ("YMIN" in targets or "YMAX" in targets):
        y_values = [coord[1] for coord in node_coords.values()]
        y_min = min(y_values)
        y_max = max(y_values)
        span = max(y_max - y_min, 1.0)
        tol = max(1e-8, 1e-6 * span)

        if "YMIN" in targets and not node_sets.get("YMIN"):
            node_sets["YMIN"] = {
                nid for nid, (_, y, _) in node_coords.items() if abs(y - y_min) <= tol
            }

        if "YMAX" in targets and not node_sets.get("YMAX"):
            node_sets["YMAX"] = {
                nid for nid, (_, y, _) in node_coords.items() if abs(y - y_max) <= tol
            }

    return node_sets, total_nodes


def parse_dat_modal_results(dat_path: str, node_sets: Dict[str, Set[int]]):
    """Return frequency table and Y-displacements per mode for requested node sets."""
    mode_frequencies = {}
    mode_displacements = {}

    tracked_sets = set(node_sets.keys())
    current_mode = None
    current_set = None

    with open(dat_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            mode_match = _EIGEN_MODE_RE.search(line)
            if mode_match:
                current_mode = int(mode_match.group(1))
                current_set = None
                mode_displacements.setdefault(current_mode, {name: [] for name in tracked_sets})
                continue

            freq_match = _FREQ_ROW_RE.match(line)
            if freq_match:
                mode_idx = int(freq_match.group(1))
                # Frequency in cycles/time (Hz in this workflow).
                mode_frequencies[mode_idx] = _safe_float(freq_match.group(4), 0.0)
                continue

            set_match = _DISP_SET_RE.search(line)
            if set_match and current_mode is not None:
                candidate = set_match.group(1).strip().upper()
                current_set = candidate if candidate in tracked_sets else None
                continue

            if current_mode is None or current_set is None:
                continue

            parts = line.split()
            if len(parts) < 4 or not parts[0].isdigit():
                continue

            nid = int(parts[0])
            if nid not in node_sets[current_set]:
                continue

            ux = _safe_float(parts[1], 0.0)
            uy = _safe_float(parts[2], 0.0)
            uz = _safe_float(parts[3], 0.0)
            mode_displacements[current_mode][current_set].append((ux, uy, uz))

    return mode_frequencies, mode_displacements

def select_longitudinal_mode( 
    mode_displacements,
    tip_set="YMAX",
    base_set="YMIN",
    near_zero=1e-12,
    input_amplitude=1.0,
):
    """
    Pick the longitudinal mode using a fitness score.
    
    For each mode, calculates:
    - tip_xz_mean: mean of sqrt(x^2 + z^2) at tip
    - Penalties for transverse motion and non-uniformity
    - Score formula: abs(tip_y_mean) * exp(-5.0 * transverse_ratio) * exp(-3.0 * tip_uniformity) * exp(-3.0 * base_uniformity)
    - Applies 1.2x bonus if tip and base have opposite signs (anti-phase motion)
    
    Returns the highest-scoring mode dict with _all_ranked_modes containing sorted list.
    """
    ranked_modes = []

    for mode_idx, set_data in mode_displacements.items():
        tip_raw = set_data.get(tip_set, [])
        base_raw = set_data.get(base_set, [])
        if not tip_raw or not base_raw:
            continue

        # Extract X, Y, Z components
        tip_x_vals = [v[0] if hasattr(v, "__getitem__") else 0.0 for v in tip_raw]
        tip_y_vals = [v[1] if hasattr(v, "__getitem__") else 0.0 for v in tip_raw]
        tip_z_vals = [v[2] if hasattr(v, "__getitem__") else 0.0 for v in tip_raw]
        
        base_x_vals = [v[0] if hasattr(v, "__getitem__") else 0.0 for v in base_raw]
        base_y_vals = [v[1] if hasattr(v, "__getitem__") else 0.0 for v in base_raw]
        base_z_vals = [v[2] if hasattr(v, "__getitem__") else 0.0 for v in base_raw]

        # Calculate means and standard deviations
        tip_x_mean = statistics.fmean(tip_x_vals)
        tip_y_mean = statistics.fmean(tip_y_vals)
        tip_z_mean = statistics.fmean(tip_z_vals)
        tip_y_std = statistics.pstdev(tip_y_vals) if len(tip_y_vals) > 1 else 0.0

        base_x_mean = statistics.fmean(base_x_vals)
        base_y_mean = statistics.fmean(base_y_vals)
        base_z_mean = statistics.fmean(base_z_vals)
        base_y_std = statistics.pstdev(base_y_vals) if len(base_y_vals) > 1 else 0.0

        abs_tip_y_mean = abs(tip_y_mean)
        abs_base_y_mean = abs(base_y_mean)

        # Calculate total 3D vector magnitudes
        tip_mag = math.sqrt(tip_x_mean**2 + tip_y_mean**2 + tip_z_mean**2)
        base_mag = math.sqrt(base_x_mean**2 + base_y_mean**2 + base_z_mean**2)

        # Calculate Axial Participation Fraction (1.0 = pure Y motion, 0.0 = pure transverse)
        tip_axial_frac = abs_tip_y_mean / tip_mag if tip_mag > near_zero else 0.0
        base_axial_frac = abs_base_y_mean / base_mag if base_mag > near_zero else 0.0

        # Uniformity penalties (Standard deviation relative to mean Y displacement)
        tip_uniformity = tip_y_std / abs_tip_y_mean if abs_tip_y_mean > near_zero else math.inf
        base_uniformity = base_y_std / abs_base_y_mean if abs_base_y_mean > near_zero else math.inf

        # Dimensionless Fitness Score (Bounded ~0.0 to 1.2)
        score = tip_axial_frac * base_axial_frac * math.exp(-3.0 * tip_uniformity) * math.exp(-3.0 * base_uniformity)

        # Bonus for anti-phase motion (Tip and Base moving in opposite directions)
        if tip_y_mean * base_y_mean < 0:
            score *= 1.2

        try:
            gain_ratio = abs_tip_y_mean / abs_base_y_mean if abs_base_y_mean > near_zero else 999.0
        except ZeroDivisionError:
            gain_ratio = 999.0

        mode_record = {
            "mode_index": mode_idx,
            "ymax_mean": tip_y_mean,
            "ymin_mean": base_y_mean,
            "tip_std": tip_y_std,
            "base_std": base_y_std,
            "tip_axial_frac": tip_axial_frac,
            "base_axial_frac": base_axial_frac,
            "gain_ratio": gain_ratio,
            "fitness_score": score,
            "_tip_y_vals": tip_y_vals,
        }
        ranked_modes.append(mode_record)

    if not ranked_modes:
        return None

    # Sort by fitness score descending
    ranked_modes.sort(key=lambda row: row["fitness_score"], reverse=True)
    selected = ranked_modes[0]

    # Calculate scaling factor to match physical amplitude.
    # CalculiX FRD/DAT values are in the model's base length unit (mm here),
    # so convert the physical outputs to micrometers after scaling.
    raw_base_mean = selected["ymin_mean"]
    scaling_factor = abs(input_amplitude / raw_base_mean) if abs(raw_base_mean) > near_zero else 1.0
    micrometer_scale = scaling_factor

    # Apply scaling factor to core metrics before calculating ratios.
    tip_mean = selected["ymax_mean"] * micrometer_scale
    base_mean = selected["ymin_mean"] * micrometer_scale
    tip_std = selected["tip_std"] * micrometer_scale
    base_std = selected["base_std"] * micrometer_scale
    tip_y_vals = [val * micrometer_scale for val in selected.get("_tip_y_vals", [])]

    # Recalculate gain and uniformity using scaled values
    try:
        if abs(base_mean) <= near_zero:
            raise ZeroDivisionError("Base mean too close to zero")
        gain_ratio = abs(tip_mean / base_mean)
    except ZeroDivisionError:
        gain_ratio = 999.0

    try:
        if abs(tip_mean) <= near_zero:
            raise ZeroDivisionError("Tip mean too close to zero")
        if tip_y_vals:
            uniformity = (max(tip_y_vals) - min(tip_y_vals)) / abs(tip_mean) * 100.0
        else:
            uniformity = 999.0
    except (ZeroDivisionError, ValueError):
        uniformity = 999.0

    ranked_modes_um = []
    for mode_record in ranked_modes:
        ranked_modes_um.append(
            {
                **mode_record,
                "ymax_mean": mode_record["ymax_mean"] * micrometer_scale,
                "ymin_mean": mode_record["ymin_mean"] * micrometer_scale,
                "tip_std": mode_record["tip_std"] * micrometer_scale,
                "base_std": mode_record["base_std"] * micrometer_scale,
                "_tip_y_vals": [val * micrometer_scale for val in mode_record.get("_tip_y_vals", [])],
            }
        )

    # Add the full ranked list to the result
    selected["_all_ranked_modes"] = ranked_modes_um

    # Update selected record with scaled values
    selected["ymax_mean"] = tip_mean
    selected["ymin_mean"] = base_mean
    selected["tip_std"] = tip_std
    selected["base_std"] = base_std
    selected["gain_ratio"] = gain_ratio

    return selected


def build_summary_row(model_name, node_count, mode_frequencies, metrics):
    """Build one row matching the Results_Summary.xlsx schema."""
    mode_idx = int(metrics["mode_index"])
    return {
        "Model_name": model_name,
        "Number_of_nodes": int(node_count),
        "Mode_Index": mode_idx,
        "Frequency_Hz": _safe_float(mode_frequencies.get(mode_idx, math.nan), math.nan),
        "YMAX_Mean_µm": _safe_float(metrics["ymax_mean"], math.nan),
        "YMIN_Mean_µm": _safe_float(metrics["ymin_mean"], math.nan),
        "Gain_Ratio": _safe_float(metrics["gain_ratio"], math.nan),
        "Tip_Std_µm": _safe_float(metrics["tip_std"], math.nan),
        "Base_Std_µm": _safe_float(metrics["base_std"], math.nan),
        "_Ranked_Metrics": metrics.get("_all_ranked_modes", []),
    }
