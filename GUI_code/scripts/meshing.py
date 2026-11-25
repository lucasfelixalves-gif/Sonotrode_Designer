"""Meshing service for GUI-driven CAE workflow.

Canonical responsibility of this module:
- Read one STEP file
- Apply mesh controls
- Create physical groups for semantic/fallback boundaries
- Export one CalculiX INP mesh
"""

import math
import os
import tempfile
from pathlib import Path

import gmsh
import meshio
import numpy as np


def _normalize_gauge_bounds(gauge_bounds):
    """Validate and normalize AABB bounds into [xmin, xmax, ymin, ymax, zmin, zmax]."""
    if gauge_bounds is None or isinstance(gauge_bounds, (str, bytes)):
        raise ValueError("gauge_bounds must be a 6-element sequence of finite numbers.")
    try:
        items = list(gauge_bounds)
    except TypeError as exc:
        raise ValueError("gauge_bounds must be a 6-element sequence of finite numbers.") from exc

    if len(items) != 6:
        raise ValueError(f"gauge_bounds must contain exactly 6 values, got {len(items)}.")

    vals = []
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
        raise ValueError("gauge_bounds must have strictly positive extents along X, Y, and Z.")

    return [xmin, xmax, ymin, ymax, zmin, zmax]


def select_elements_in_bounds(
    node_coords: np.ndarray,
    node_ids: np.ndarray,
    element_conn: np.ndarray,
    element_ids: np.ndarray,
    gauge_bounds: list[float],
) -> tuple[list[int], list[int]]:
    """Return sorted 1-based (selected_element_ids, selected_node_ids) inside gauge_bounds."""
    xmin, xmax, ymin, ymax, zmin, zmax = _normalize_gauge_bounds(gauge_bounds)

    coords = np.asarray(node_coords, dtype=float)
    nids = np.asarray(node_ids, dtype=int)
    conn = np.asarray(element_conn, dtype=int)
    eids = np.asarray(element_ids, dtype=int)

    if coords.size == 0 or nids.size == 0 or conn.size == 0 or eids.size == 0:
        return ([], [])

    centroids = coords[conn].mean(axis=1)
    mask = (
        (centroids[:, 0] >= xmin)
        & (centroids[:, 0] <= xmax)
        & (centroids[:, 1] >= ymin)
        & (centroids[:, 1] <= ymax)
        & (centroids[:, 2] >= zmin)
        & (centroids[:, 2] <= zmax)
    )

    if not np.any(mask):
        return ([], [])

    selected_element_ids = sorted(int(e) for e in np.unique(eids[mask]))
    selected_node_indices = np.unique(conn[mask].ravel())
    selected_node_ids = sorted(int(n) for n in np.unique(nids[selected_node_indices]))
    return (selected_element_ids, selected_node_ids)


def format_abaqus_set_block(
    keyword: str,
    name: str,
    ids: list[int],
    per_line: int = 16,
) -> str:
    """Format *ELSET or *NSET block with <=16 comma-separated IDs per line."""
    per_line_int = int(per_line)
    if per_line_int < 1 or per_line_int > 16:
        raise ValueError(f"per_line must be between 1 and 16, got {per_line!r}.")

    id_list = [int(i) for i in ids]
    if not id_list:
        return ""

    kw = str(keyword).strip().upper()
    if not kw.startswith("*"):
        kw = f"*{kw}"
    param = kw.lstrip("*")
    set_name = str(name).strip()

    lines = [f"{kw}, {param}={set_name}"]
    for start in range(0, len(id_list), per_line_int):
        chunk = id_list[start: start + per_line_int]
        lines.append(", ".join(str(i) for i in chunk))
    return "\n".join(lines)


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _role_centroid(role_info):
    if not isinstance(role_info, dict):
        return None
    centroid = role_info.get("centroid")
    if not isinstance(centroid, (list, tuple)) or len(centroid) < 3:
        return None
    try:
        return [float(centroid[0]), float(centroid[1]), float(centroid[2])]
    except (TypeError, ValueError):
        return None

#Add normal calculating checking for nset assigning.
def _smart_assign_surface_roles(surfaces, semantic_roles):
    found_essentials = {"YMAX": False, "YMIN": False}
    if not semantic_roles:
        return found_essentials

    for role_name, role_info in semantic_roles.items():
        centroid = _role_centroid(role_info)
        if centroid is None:
            continue

        role_upper = str(role_name).upper()
        if "YMAX" in role_upper:
            canonical_name = "YMAX"
        elif "YMIN" in role_upper:
            canonical_name = "YMIN"
        else:
            canonical_name = str(role_name).strip().upper().replace(" ", "_")

        winning_tag = None
        best_distance_sq = float('inf')

        for _, tag in surfaces:
            #Add normal calculation 

            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(2, tag)
            cx = (xmin + xmax) / 2.0
            cy = (ymin + ymax) / 2.0
            cz = (zmin + zmax) / 2.0
            
            dx = cx - centroid[0]
            dy = cy - centroid[1]
            dz = cz - centroid[2]
            distance_sq = dx * dx + dy * dy + dz * dz
            
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                winning_tag = tag

        if winning_tag is None:
            continue

        group = gmsh.model.addPhysicalGroup(2, [winning_tag])
        gmsh.model.setPhysicalName(2, group, canonical_name)

        if canonical_name == "YMAX":
            found_essentials["YMAX"] = True
        if canonical_name == "YMIN":
            found_essentials["YMIN"] = True

    return found_essentials


def _assign_fallback_essential_surfaces(surfaces, found_essentials, tol=1e-6):
    if not surfaces:
        return

    # 1. Calculate global bounding box extrema for Y
    ymins, ymaxs = [], []
    bounding_boxes = {}

    for _, tag in surfaces:
        _, ymin, _, _, ymax, _ = gmsh.model.getBoundingBox(2, tag)
        bounding_boxes[tag] = (ymin, ymax)
        ymins.append(ymin)
        ymaxs.append(ymax)

    if not ymins or not ymaxs:
        return

    ymin_global = min(ymins)
    ymax_global = max(ymaxs)

    # 2. Dynamic tolerance based on model size
    span = max(ymax_global - ymin_global, 1.0)
    effective_tol = max(tol, 1e-5 * span)

    # 3. Find perfectly flat faces at the extrema
    ymax_tags = []
    ymin_tags = []

    for tag, (ymin, ymax) in bounding_boxes.items():
        # Face must be entirely flat at the global YMAX
        if abs(ymin - ymax_global) <= effective_tol and abs(ymax - ymax_global) <= effective_tol:
            ymax_tags.append(tag)

        # Face must be entirely flat at the global YMIN
        if abs(ymin - ymin_global) <= effective_tol and abs(ymax - ymin_global) <= effective_tol:
            ymin_tags.append(tag)

    # 4. Assign groups if they weren't already found via smart selection
    if not found_essentials.get("YMAX") and ymax_tags:
        group = gmsh.model.addPhysicalGroup(2, ymax_tags)
        gmsh.model.setPhysicalName(2, group, "YMAX")

    if not found_essentials.get("YMIN") and ymin_tags:
        group = gmsh.model.addPhysicalGroup(2, ymin_tags)
        gmsh.model.setPhysicalName(2, group, "YMIN")


def _assign_volume_group():
    volumes = gmsh.model.getEntities(3)
    if not volumes:
        raise RuntimeError("No 3D volume entities found in STEP geometry.")
    volume_tags = [tag for _, tag in volumes]
    group = gmsh.model.addPhysicalGroup(3, volume_tags)
    gmsh.model.setPhysicalName(3, group, "Volume1")


def _assign_unique_surface_physical_groups():
    surfaces = gmsh.model.getEntities(2)
    for _, surface_tag in surfaces:
        # Keep physical IDs numerically aligned with CAD surface tags.
        group_tag = gmsh.model.addPhysicalGroup(2, [surface_tag], tag=surface_tag)
        gmsh.model.setPhysicalName(2, group_tag, f"CAD_SURFACE_{surface_tag}")


def generate_preview_mesh(*, step_path, vtk_output_path, quiet=True):
    """Export a 2D VTK preview mesh with one physical group per CAD surface.

    The physical group tag is forced to each CAD surface tag so PyVista picking can
    recover exact CAD surface IDs from cell_data.
    """
    output_dir = os.path.dirname(vtk_output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    gmsh_started = False
    try:
        if not gmsh.isInitialized():
            gmsh.initialize()
            gmsh_started = True

        gmsh.clear()
        gmsh.option.setNumber("General.Terminal", 0 if quiet else 1)
        gmsh.option.setNumber("Mesh.SaveElementTagType", 1)

        gmsh.model.add(Path(step_path).stem)
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        _assign_unique_surface_physical_groups()
        gmsh.model.mesh.generate(2)
        gmsh.write(vtk_output_path)

        return vtk_output_path
    finally:
        try:
            gmsh.clear()
        except Exception:
            pass
        if gmsh_started:
            gmsh.finalize()


def _is_volume_cell(cell_type):
    return cell_type.startswith(("tetra", "hexahedron", "wedge", "pyramid", "voxel"))


def _is_second_order_volume_cell(cell_type):
    base_linear_types = {"tetra", "hexahedron", "wedge", "pyramid", "voxel"}
    if cell_type in base_linear_types:
        return False
    return _is_volume_cell(cell_type)


def _is_surface_cell(cell_type):
    return cell_type.startswith(("triangle", "quad"))


def _convert_msh_to_volume_inp(
    msh_path,
    inp_path,
    expected_element_order=2,
    gauge_bounds=None,
    strict_gauge_bounds=False,
):
    mesh = meshio.read(msh_path)

    kept_cells = []
    valid_node_ids = set()
    has_second_order_volume = False

    for block in mesh.cells:
        if _is_volume_cell(block.type):
            kept_cells.append(meshio.CellBlock(block.type, block.data))
            if _is_second_order_volume_cell(block.type):
                has_second_order_volume = True
            # CRITICAL: Track which nodes actually belong to the 3D mesh
            for cell in block.data:
                for nid in cell:
                    valid_node_ids.add(int(nid))

    if not kept_cells:
        raise RuntimeError("No 3D volume elements were generated by Gmsh.")

    if int(expected_element_order) >= 2 and not has_second_order_volume:
        raise RuntimeError(
            "Requested Element_order=2, but Gmsh exported only first-order volume elements. "
            "Check Meshing_Parameters.Element_order and Gmsh high-order settings."
        )

    volume_mesh = meshio.Mesh(points=mesh.points, cells=kept_cells)
    meshio.write(inp_path, volume_mesh, file_format="abaqus")

    # Normalize uncommon element aliases to CCX-supported names.
    with open(inp_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("TYPE=C3D10MH", "TYPE=C3D10")

    # Export surface physical groups as NSETs so GUI-picked roles reach CCX.
    nset_lines = []
    for set_name, per_block_cells in mesh.cell_sets.items():
        if str(set_name).startswith("gmsh:"):
            continue

        node_ids_0 = set()
        for block_index, cell_indices in enumerate(per_block_cells):
            if cell_indices is None or len(cell_indices) == 0:
                continue
            if block_index >= len(mesh.cells):
                continue

            cell_block = mesh.cells[block_index]
            if not _is_surface_cell(cell_block.type):
                continue

            for cell_index in cell_indices:
                for nid in cell_block.data[int(cell_index)]:
                    # Only add the node if it actively participates in the 3D volume
                    if int(nid) in valid_node_ids:
                        node_ids_0.add(int(nid))

        if not node_ids_0:
            continue

        canonical_name = str(set_name).strip().upper().replace(" ", "_")
        nset_lines.append(f"*NSET, NSET={canonical_name}")
        node_ids_1 = sorted(nid + 1 for nid in node_ids_0)
        for chunk_start in range(0, len(node_ids_1), 16):
            chunk = node_ids_1[chunk_start: chunk_start + 16]
            nset_lines.append(", ".join(str(n) for n in chunk))

    if nset_lines:
        content = content.rstrip() + "\n" + "\n".join(nset_lines) + "\n"

    if gauge_bounds is not None:
        norm_bounds = _normalize_gauge_bounds(gauge_bounds)
        node_coords = np.asarray(volume_mesh.points, dtype=float)
        node_ids = np.arange(1, len(node_coords) + 1, dtype=int)

        gauge_elem_ids = set()
        gauge_node_ids = set()
        eid_offset = 1
        for block in kept_cells:
            block_len = len(block.data)
            if block_len == 0:
                continue
            block_eids = np.arange(eid_offset, eid_offset + block_len, dtype=int)
            sel_elems, sel_nodes = select_elements_in_bounds(
                node_coords=node_coords,
                node_ids=node_ids,
                element_conn=np.asarray(block.data, dtype=int),
                element_ids=block_eids,
                gauge_bounds=norm_bounds,
            )
            gauge_elem_ids.update(sel_elems)
            gauge_node_ids.update(sel_nodes)
            eid_offset += block_len

        if gauge_elem_ids:
            elset_block = format_abaqus_set_block(
                "*ELSET", "GAUGE_VOL", sorted(gauge_elem_ids), per_line=16
            )
            nset_block = format_abaqus_set_block(
                "*NSET", "GAUGE_VOL_NODES", sorted(gauge_node_ids), per_line=16
            )
            extra_blocks = [b for b in (elset_block, nset_block) if b]
            if extra_blocks:
                content = content.rstrip() + "\n" + "\n".join(extra_blocks) + "\n"
        else:
            if valid_node_ids:
                active_pts = node_coords[sorted(valid_node_ids)]
            else:
                active_pts = node_coords
            if len(active_pts) > 0:
                mins = active_pts.min(axis=0)
                maxs = active_pts.max(axis=0)
                mesh_bounds = [
                    float(mins[0]), float(maxs[0]),
                    float(mins[1]), float(maxs[1]),
                    float(mins[2]), float(maxs[2]),
                ]
            else:
                mesh_bounds = []
            msg = (
                f"[meshing][WARNING] No volume elements matched gauge_bounds={norm_bounds}; "
                f"actual mesh bounds={mesh_bounds}. Skipping GAUGE_VOL/GAUGE_VOL_NODES."
            )
            if strict_gauge_bounds:
                raise ValueError(msg)
            print(msg)

    with open(inp_path, "w", encoding="utf-8") as f:
        f.write(content)


def mesh_step_to_inp(
    *,
    step_path,
    mesh_output_path,
    mesh_config,
    semantic_roles=None,
    gauge_bounds=None,
    strict_gauge_bounds=False,
    quiet=True,
):
    """Generate a 3D second-order mesh INP for one STEP model.

    Args:
        step_path: Absolute path to STEP file.
        mesh_output_path: Absolute output path for generated INP mesh.
        mesh_config: Dictionary containing Characteristic_length_min/max.
        semantic_roles: Role->reference centroid mapping from GUI picking.
        gauge_bounds: Optional AABB [xmin, xmax, ymin, ymax, zmin, zmax] for GAUGE_VOL.
        strict_gauge_bounds: If True, raise ValueError when 0 elements match gauge_bounds.
        quiet: If True, suppress Gmsh terminal output.

    Returns:
        mesh_output_path for chaining.
    """
    semantic_roles = semantic_roles or {}
    mesh_config = mesh_config or {}

    os.makedirs(os.path.dirname(mesh_output_path), exist_ok=True)

    gmsh_started = False
    try:
        if not gmsh.isInitialized():
            gmsh.initialize()
            gmsh_started = True

        gmsh.clear()
        gmsh.option.setNumber("General.Terminal", 0 if quiet else 1)
        element_order = _as_int(mesh_config.get("Element_order"), 2)
        if element_order not in (1, 2):
            element_order = 2
        # Generate as linear first so Netgen optimization is stable.
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        if element_order >= 2:
            second_order_incomplete = _as_bool(
                mesh_config.get("Second_order_incomplete"),
                True,
            )
            gmsh.option.setNumber("Mesh.SecondOrderIncomplete", 1 if second_order_incomplete else 0)
            gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)
        gmsh.option.setNumber(
            "Mesh.MeshSizeMax",
            _as_float(mesh_config.get("Characteristic_length_max"), 2.0),
        )
        gmsh.option.setNumber(
            "Mesh.MeshSizeMin",
            _as_float(mesh_config.get("Characteristic_length_min"), 0.5),
        )

        gmsh.model.add(Path(step_path).stem)
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        surfaces = gmsh.model.getEntities(2)
        found_essentials = _smart_assign_surface_roles(surfaces, semantic_roles)
        _assign_fallback_essential_surfaces(surfaces, found_essentials)
        _assign_volume_group()

        gmsh.model.mesh.generate(3)
        try:
            gmsh.model.mesh.optimize("Netgen")
        except Exception:
            pass

        if element_order >= 2:
            gmsh.model.mesh.setOrder(2)
            try:
                gmsh.model.mesh.optimize("HighOrder")
            except Exception:
                pass

        with tempfile.NamedTemporaryFile(suffix=".msh", delete=False) as tmp:
            msh_tmp_path = tmp.name
        try:
            gmsh.write(msh_tmp_path)
            _convert_msh_to_volume_inp(
                msh_tmp_path,
                mesh_output_path,
                expected_element_order=element_order,
                gauge_bounds=gauge_bounds,
                strict_gauge_bounds=strict_gauge_bounds,
            )
        finally:
            if os.path.isfile(msh_tmp_path):
                os.remove(msh_tmp_path)

        return mesh_output_path
    finally:
        try:
            gmsh.clear()
        except Exception:
            pass
        if gmsh_started:
            gmsh.finalize()
