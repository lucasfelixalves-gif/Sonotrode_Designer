import os
from glob import glob

import pandas as pd

def _find_master_workbook(project_dir):
    config_dir = os.path.join(project_dir, "01_Master_Config")
    xlsx_files = sorted(
        path for path in glob(os.path.join(config_dir, "*.xlsx"))
        if not os.path.basename(path).startswith("~$")
    )

    if len(xlsx_files) == 0:
        raise FileNotFoundError(
            "No valid master workbook found in 01_Master_Config (temporary '~$' files are ignored)."
        )

    if len(xlsx_files) > 1:
        listed_files = ", ".join(os.path.basename(path) for path in xlsx_files)
        selected_file = xlsx_files[0]
        print(
            "[WARNING] Multiple workbooks found in 01_Master_Config: "
            f"{listed_files}. Loading: {os.path.basename(selected_file)}"
        )
        return selected_file

    return xlsx_files[0]

def _make_unique_headers(values):
    headers = []
    counts = {}
    for index, value in enumerate(values):
        if index == 0:
            base = "Model_name"
        else:
            # Clean up SolidWorks variables (e.g., 'D1@Sketch1' becomes 'D1' for the UI)
            raw_val = str(value).strip() if pd.notna(value) else ""
            base = raw_val.split("@")[0] if raw_val else f"Column_{index + 1}"

        count = counts.get(base, 0)
        counts[base] = count + 1
        headers.append(base if count == 0 else f"{base}_{count + 1}")
    return headers

def _load_geometry_table(workbook_path):
    """Load the first sheet using the workbook convention: headers on row 2, data on row 4+."""
    xls = pd.ExcelFile(workbook_path)
    try:
        if not xls.sheet_names:
            raise RuntimeError("Workbook contains no sheets.")

        first_sheet = xls.sheet_names[0]
        raw = pd.read_excel(workbook_path, sheet_name=first_sheet, header=None)
    finally:
        xls.close()

    if raw.empty or raw.shape[0] < 4:
        raise RuntimeError("First sheet does not contain enough rows for geometry data.")

    headers = _make_unique_headers(raw.iloc[1].tolist())
    df_geo = raw.iloc[3:].copy()
    df_geo.columns = headers
    df_geo = df_geo.dropna(how="all")

    if "Model_name" not in df_geo.columns:
        raise RuntimeError("Could not derive Model_name column from first workbook sheet.")

    df_geo = df_geo.dropna(subset=["Model_name"])
    df_geo["Model_name"] = df_geo["Model_name"].astype(str).str.strip()
    df_geo = df_geo[df_geo["Model_name"].str.lower() != "nan"]
    df_geo = df_geo[df_geo["Model_name"] != ""]
    df_geo = df_geo[df_geo["Model_name"].str.upper() != "DEFAULT"]
    df_geo = df_geo.reset_index(drop=True)
    return df_geo


def load_geometry_parameters(project_dir):
    """Load geometry parameters from the first sheet of the master workbook."""
    if not project_dir:
        return pd.DataFrame()

    master_wb = _find_master_workbook(project_dir)
    return _load_geometry_table(master_wb)