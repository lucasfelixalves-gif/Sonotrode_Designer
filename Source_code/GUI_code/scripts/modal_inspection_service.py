import os
import re
import tempfile

import meshio
import numpy as np
import pyvista as pv


_CACHE = {}

STATE_SEARCHING_MODE = "SEARCHING_MODE"
STATE_VALIDATING_BLOCK = "VALIDATING_BLOCK"
STATE_READING_DATA = "READING_DATA"

MODE_LINE_REGEX = re.compile(r"1PMODE\s+(-?\d+)")
FRD_VECTOR_REGEX = re.compile(r"[-+]?\d*\.?\d+[EeDd][-+]?\d{2,3}")
FRD_FLOAT_REGEX = re.compile(r"[-+]?\d*\.\d+(?:[EeDd][-+]?\d+)?")
FRD_NUMBER_REGEX = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?")


def _cache_key(project_dir, model_name):
    project_dir_abs = os.path.abspath(project_dir or "")
    model_name_str = str(model_name)
    inp_path = os.path.join(project_dir_abs, "03_Meshes_INP", f"{model_name_str}_mesh.inp")
    frd_path = os.path.join(project_dir_abs, "04_Results_CCX", f"{model_name_str}.frd")

    try:
        inp_mtime = os.path.getmtime(inp_path) if os.path.isfile(inp_path) else 0
    except OSError:
        inp_mtime = 0

    try:
        frd_mtime = os.path.getmtime(frd_path) if os.path.isfile(frd_path) else 0
    except OSError:
        frd_mtime = 0

    return (project_dir_abs, model_name_str, inp_mtime, frd_mtime)


def _to_float(value):
    return float(str(value).replace("D", "E").replace("d", "E"))


def _extract_mode_from_line(line):
    match = MODE_LINE_REGEX.search(line)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _get_or_create_model_cache(project_dir, model_name):
    key = _cache_key(project_dir, model_name)
    entry = _CACHE.get(key)
    if entry is None:
        entry = {
            "base_dataset": None,
            "node_mapping": None,
            "modes_info": None,
            "frd_path": os.path.join(project_dir or "", "04_Results_CCX", f"{model_name}.frd"),
            "inp_path": os.path.join(project_dir or "", "03_Meshes_INP", f"{model_name}_mesh.inp"),
        }
        _CACHE[key] = entry
    return entry


def _build_node_mapping(inp_path):
    """Read INP and map explicit node IDs to 0-based PyVista indices."""
    mapping = {}
    idx = 0
    in_node_block = False

    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("*"):
                in_node_block = stripped.upper().startswith("*NODE")
                continue

            if not in_node_block or not stripped:
                continue

            parts = stripped.split(",")
            if len(parts) < 3:
                continue

            try:
                nid = int(parts[0])
            except ValueError:
                continue

            mapping[nid] = idx
            idx += 1

    return mapping


def extract_node_sets(inp_path, target_sets=("YMIN", "YMAX")):
    """Return explicit node IDs from selected *NSET cards in an INP file."""
    targets = {str(name).strip().upper() for name in (target_sets or ()) if str(name).strip()}
    if not targets:
        return set()

    collected = set()
    active_capture = False

    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("*"):
                upper = line.upper()
                active_capture = False
                if upper.startswith("*NSET"):
                    match = re.search(r"\bNSET\s*=\s*([^,\s]+)", upper)
                    # Only capture explicit IDs, not GENERATED ranges.
                    if match and "GENERATE" not in upper:
                        nset_name = match.group(1).strip().upper()
                        if nset_name in targets:
                            active_capture = True
                continue

            if not active_capture:
                continue

            for token in line.split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    collected.add(int(token))
                except ValueError:
                    continue

    return collected


def _read_base_dataset_from_inp(inp_path):
    """Load the mesh from INP through meshio and bridge it into PyVista."""
    mesh = meshio.read(inp_path)

    with tempfile.NamedTemporaryFile(suffix=".vtu", delete=False) as tmp:
        temp_vtu_path = tmp.name

    try:
        meshio.write(temp_vtu_path, mesh, file_format="vtu")
        dataset = pv.read(temp_vtu_path)
    finally:
        if os.path.exists(temp_vtu_path):
            try:
                os.remove(temp_vtu_path)
            except OSError:
                pass

    return dataset


def get_available_modes_and_frequencies(project_dir, model_name):
    """Return {mode_index: frequency_hz} parsed from a CalculiX .frd file."""
    cache_entry = _get_or_create_model_cache(project_dir, model_name)
    if cache_entry["modes_info"] is not None:
        return cache_entry["modes_info"]

    frd_path = cache_entry["frd_path"]
    if not os.path.isfile(frd_path):
        raise FileNotFoundError(f"Results file not found: {frd_path}")

    modes_info = {}
    state = STATE_SEARCHING_MODE
    pending_mode = None
    validating_window = 0

    with open(frd_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if state == STATE_SEARCHING_MODE:
                mode_index = _extract_mode_from_line(line)
                if mode_index is not None:
                    pending_mode = mode_index
                    state = STATE_VALIDATING_BLOCK
                    validating_window = 20
                continue

            if state == STATE_VALIDATING_BLOCK:
                if pending_mode is None:
                    state = STATE_SEARCHING_MODE
                    continue

                if validating_window <= 0:
                    state = STATE_SEARCHING_MODE
                    pending_mode = None
                    continue
                validating_window -= 1

                if not line.startswith("100C") and not line.startswith(" 100C") and not line.strip().startswith("100C"):
                    continue

                float_matches = FRD_FLOAT_REGEX.findall(line)
                if float_matches:
                    modes_info[pending_mode] = _to_float(float_matches[0])
                    state = STATE_SEARCHING_MODE
                    pending_mode = None
                    continue

                number_matches = FRD_NUMBER_REGEX.findall(line)
                if number_matches:
                    modes_info[pending_mode] = _to_float(number_matches[-1])
                    state = STATE_SEARCHING_MODE
                    pending_mode = None

    cache_entry["modes_info"] = modes_info
    return modes_info


def _load_frd_displacements(frd_path, node_mapping, target_mode_index):
    """Parse FRD displacement vectors for one mode using a strict state machine."""
    displacements = np.zeros((len(node_mapping), 3))
    parsed_count = 0
    target_mode_index = int(target_mode_index)

    state = STATE_SEARCHING_MODE
    current_mode = None
    block_is_target = False

    with open(frd_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            mode_index = _extract_mode_from_line(line)
            if mode_index is not None:
                current_mode = mode_index
                block_is_target = False
                state = STATE_VALIDATING_BLOCK
                continue

            if state == STATE_VALIDATING_BLOCK:
                if current_mode != target_mode_index:
                    continue

                if line.strip().startswith("-4") and ("DISP" in line or line.rstrip().endswith("U")):
                    block_is_target = True
                    state = STATE_READING_DATA
                continue

            if state == STATE_READING_DATA:
                if line.startswith(" -3"):
                    break

                if not line.startswith(" -1"):
                    continue

                try:
                    nid_str = line[3:13].strip()
                    if not nid_str:
                        raise ValueError("Missing node ID field")

                    nid = int(nid_str)
                    if nid not in node_mapping:
                        continue

                    values = FRD_VECTOR_REGEX.findall(line[13:])
                    if len(values) < 3:
                        raise ValueError(f"Expected 3 displacement components, found {len(values)}")

                    idx = node_mapping[nid]
                    displacements[idx] = [
                        _to_float(values[0]),
                        _to_float(values[1]),
                        _to_float(values[2]),
                    ]
                    parsed_count += 1
                except ValueError:
                    continue

    if parsed_count == 0:
        raise RuntimeError(f"Could not find or parse data for Mode {target_mode_index} in FRD file.")
    return displacements


def _load_or_build_base_mesh(project_dir, model_name):
    cache_entry = _get_or_create_model_cache(project_dir, model_name)

    if cache_entry["base_dataset"] is not None and cache_entry["node_mapping"] is not None:
        return cache_entry["base_dataset"], cache_entry["node_mapping"]

    inp_path = cache_entry["inp_path"]
    if not os.path.isfile(inp_path):
        raise FileNotFoundError(f"Mesh file not found: {inp_path}")

    dataset = _read_base_dataset_from_inp(inp_path)
    node_mapping = _build_node_mapping(inp_path)

    cache_entry["base_dataset"] = dataset
    cache_entry["node_mapping"] = node_mapping
    return dataset, node_mapping


def load_base_result_mesh(project_dir, model_name, mode_index):
    cache_entry = _get_or_create_model_cache(project_dir, model_name)
    frd_path = cache_entry["frd_path"]
    if not os.path.isfile(frd_path):
        raise FileNotFoundError(f"Results file not found: {frd_path}")

    dataset, node_mapping = _load_or_build_base_mesh(project_dir, model_name)
    inp_path = cache_entry["inp_path"]

    boundary_node_ids = extract_node_sets(inp_path, target_sets=("YMIN", "YMAX"))
    boundary_mask = np.zeros(dataset.n_points, dtype=int)
    for node_id in boundary_node_ids:
        mapped_index = node_mapping.get(node_id)
        if mapped_index is None:
            continue
        if 0 <= mapped_index < dataset.n_points:
            boundary_mask[mapped_index] = 1

    if cache_entry["modes_info"] is None:
        cache_entry["modes_info"] = get_available_modes_and_frequencies(project_dir, model_name)
    vectors = _load_frd_displacements(frd_path, node_mapping, mode_index)

    vector_name = f"U_Mode_{mode_index}"
    dataset = dataset.copy(deep=True)
    dataset.point_data["Boundary_Nodes"] = boundary_mask
    dataset.point_data[vector_name] = vectors
    dataset.set_active_vectors(vector_name)

    max_disp = np.max(np.linalg.norm(vectors, axis=1))

    if max_disp > 1e-12:
        bounds = dataset.bounds
        diag = np.sqrt(
            (bounds[1] - bounds[0]) ** 2
            + (bounds[3] - bounds[2]) ** 2
            + (bounds[5] - bounds[4]) ** 2
        )
        auto_scale = (0.15 * diag) / max_disp
        dataset.field_data["AutoWarpFactor"] = [auto_scale]
    else:
        dataset.field_data["AutoWarpFactor"] = [1.0]

    return dataset, vector_name


def load_base_mesh_preview(project_dir, model_name, target_sets=("YMIN", "YMAX")):
    """Load base mesh and attach Boundary_Nodes mask without requiring FRD data."""
    cache_entry = _get_or_create_model_cache(project_dir, model_name)
    inp_path = cache_entry["inp_path"]
    if not os.path.isfile(inp_path):
        raise FileNotFoundError(f"Mesh file not found: {inp_path}")

    dataset, node_mapping = _load_or_build_base_mesh(project_dir, model_name)
    boundary_node_ids = extract_node_sets(inp_path, target_sets=target_sets)
    boundary_mask = np.zeros(dataset.n_points, dtype=int)
    for node_id in boundary_node_ids:
        mapped_index = node_mapping.get(node_id)
        if mapped_index is None:
            continue
        if 0 <= mapped_index < dataset.n_points:
            boundary_mask[mapped_index] = 1

    preview = dataset.copy(deep=True)
    preview.point_data["Boundary_Nodes"] = boundary_mask
    return preview


def warp_result_mesh(base_mesh, slider_value):
    slider_pct = float(slider_value) / 100.0
    auto_scale = base_mesh.field_data.get("AutoWarpFactor", [1.0])[0]
    final_factor = slider_pct * auto_scale
    vector_name = base_mesh.active_vectors_name

    warped = base_mesh.warp_by_vector(vector_name, factor=final_factor)

    magnitude = np.linalg.norm(warped.point_data[vector_name], axis=1)
    scalar_name = "Displacement_Magnitude"
    warped.point_data[scalar_name] = magnitude

    return warped, scalar_name


def clear_inspection_cache():
    global _CACHE
    _CACHE.clear()
