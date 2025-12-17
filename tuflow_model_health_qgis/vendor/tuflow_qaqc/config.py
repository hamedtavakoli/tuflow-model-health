"""
Configuration constants for TUFLOW QA/QC pre-run validator.

Includes file extensions, regex patterns, and validation thresholds.
"""

import re
from pathlib import Path
from typing import Set, Dict, Literal


def normalize_directive(s: str) -> str:
    """Canonicalise directive keywords for case-insensitive matching."""

    return " ".join(s.strip().split()).casefold()

# ---- File extensions ----

CONTROL_EXTS: Set[str] = {
    ".tcf", ".tgc", ".tbc", ".ecf",
    ".qcf", ".tef", ".toc", ".trfc",
    ".adcf",
}

INPUT_EXTS: Set[str] = set()

SOIL_EXTS: Set[str] = {
    ".tsoilf",
}
INPUT_EXTS |= SOIL_EXTS

GIS_EXTS: Set[str] = {
    ".shp",
    ".tab",
    ".mif",
    ".mid",
    ".gpkg",
    ".gdb",
    ".tif",
    ".tiff",
    ".asc",
    ".flt",
    ".bil",
    ".grd",
}

DB_EXTS: Set[str] = {
    ".csv",
    ".txt",
    ".dat",
    ".dbf",
    ".sqlite",
    ".gpkg",
}

ALL_KNOWN_FILE_EXTS: Set[str] = set()
ALL_KNOWN_FILE_EXTS |= CONTROL_EXTS
ALL_KNOWN_FILE_EXTS |= INPUT_EXTS
ALL_KNOWN_FILE_EXTS |= GIS_EXTS
ALL_KNOWN_FILE_EXTS |= DB_EXTS

# ---- Directive allow/deny lists ----

CONTROL_DIRECTIVES: Set[str] = {
    "Read File",
    "Geometry Control File",
    "BC Control File",
    "ESTRY Control File",
    "Quadtree Control File",
    "Event File",
    "Rainfall Control File",
    "Operations Control File",   # some models use this explicit form
    "Operations Control",        # keep for compatibility with existing hints
    "AD Control File",
    "Advection Dispersion Control File",
    "Advection Dispersion Control",
    "External Stress File",
    "SWMM Control File",
}

# Directives that introduce GIS layers (vector/raster containers; may be "file | layer")
GIS_DIRECTIVES: Set[str] = {
    # TCF-level GIS integration (e.g. 12D / legacy links)
    "Read GIS 12D Network",
    "Read GIS 12D Nodes",
    "Read GIS 12D WLL Points",
    "Calibration Points MI File",

    # TGC-level core GIS reads
    "Read GIS",
    "Read GIS Z Shape",
    "Read GIS Code",
    "Read GIS Attribute",
    "Read GIS Materials",
    "Read GIS Roughness",
    "Read GIS Resistance",
    "Read GIS Source",
    "Read GIS Boundary",
    "Read GIS Flow",

    # TBC-level GIS reads
    "Read BC",
    "Read BC GIS",
    "Read Source GIS",

    # ECF-level 1D GIS reads (common names)
    "Read GIS Network",
    "Read GIS Nodes",
    "Read GIS Links",
}

# Directives that introduce database files (CSV/DBF/SQLite/GPKG containers)
DATABASE_DIRECTIVES: Set[str] = {
    "BC Database",
    "Read BC Database",
    "Spatial Database",
    "Read Structure Database",
    "Read Attribute Database",
}

# Directives that introduce generic input files (non-control, non-GIS)
INPUT_DIRECTIVES: Set[str] = {
    # Soils / losses
    "Soils File",
    "Read Soils File",
    "Infiltration File",
    "Losses File",
    "Initial Loss File",
    "Continuing Loss File",

    # Rainfall (often in TEF/TRFC, but can appear elsewhere)
    "Rainfall File",
    "Read Rainfall",
    "Read RF",
    "Rainfall Pattern File",

    # Time series / hydrographs / curves
    "Inflow File",
    "Flow Hydrograph",
    "Stage Hydrograph",
    "HQ File",
    "ZQ File",
    "QT File",

    # Tables / materials / roughness (non-GIS)
    "Read Table",
    "Read Materials File",
    "Read Roughness File",
    "Read Resistance File",

    # Restart / initialisation
    "Restart File",
    "Initial Conditions File",
    "Hot Start File",

    # Misc / external integration
    "FEWS Input File",
    "Blockage Matrix File",
}

# Grid/raster reads (often appear in TGC/TRFC). Treat as GIS-raster or INPUT-raster.
GRID_DIRECTIVES: Set[str] = {
    "Read Grid",
    "Read DEM",
    "Read ASC",
    "Read TIF",
    "Read TIFF",
    "Read BIL",
    "Read FLT",
    "Rainfall Grid",
    "Read Rainfall Grid",
}

# Directives that MUST NEVER be treated as files (even though they use "==")
NON_FILE_DIRECTIVES: Set[str] = {
    "Scenario",
    "Event",
    "Else if Scenario",
    "Set Variable",
    "Define",
    "If",
    "Else",
    "End If",
}

# Category map for directive-driven classification
# Use this in parsing: directive -> "control" | "gis" | "database" | "input" | "grid"
DIRECTIVE_CATEGORY: Dict[str, str] = {
    **{k: "control" for k in CONTROL_DIRECTIVES},
    **{k: "gis" for k in GIS_DIRECTIVES},
    **{k: "database" for k in DATABASE_DIRECTIVES},
    **{k: "input" for k in INPUT_DIRECTIVES},
    **{k: "grid" for k in GRID_DIRECTIVES},
}

# Known non-file literal RHS values (common flags)
NON_FILE_LITERALS: Set[str] = {
    "on", "off", "yes", "no", "true", "false",
}

# Numeric-ish RHS patterns (used to prevent false file detection like "2.5" or "2.5m")
NUMERIC_ONLY_RE = re.compile(r"^\s*[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*$")
NUMERIC_WITH_UNIT_RE = re.compile(r"^\s*[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?\s*[A-Za-z]+\s*$")

def _normalise_set(values: Set[str]) -> Set[str]:
    return {normalize_directive(v) for v in values}


# Normalised (case-insensitive) versions for parsing
CONTROL_DIRECTIVES = _normalise_set(CONTROL_DIRECTIVES)
GIS_DIRECTIVES = _normalise_set(GIS_DIRECTIVES)
DATABASE_DIRECTIVES = _normalise_set(DATABASE_DIRECTIVES)
INPUT_DIRECTIVES = _normalise_set(INPUT_DIRECTIVES)
GRID_DIRECTIVES = _normalise_set(GRID_DIRECTIVES)
NON_FILE_DIRECTIVES = _normalise_set(NON_FILE_DIRECTIVES)
DIRECTIVE_CATEGORY = {normalize_directive(k): v for k, v in DIRECTIVE_CATEGORY.items()}
NON_FILE_LITERALS = {v.casefold() for v in NON_FILE_LITERALS}

# ---- Regex patterns ----

COMMENT_RE = re.compile(r"^\s*(!|#|//)")
DIRECTIVE_RE = re.compile(
    r"""
    ^\s*
    (?P<key>[^=!]+?)      # keyword until = or ==
    \s*={1,2}\s*
    (?P<value>.+?)        # rest of line
    \s*$
    """,
    re.VERBOSE,
)

INLINE_COMMENT_SPLIT_RE = re.compile(r"(!|//|#|;)")
WILDCARD_RE = re.compile(r"~(?P<var>[A-Za-z0-9_]+)~")
FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")

# ---- Default TUFLOW executable ----

DEFAULT_TUFLOW_EXE = Path("TUFLOW_iSP_w64.exe")

# ---- Thresholds for time & timestep checks (5.x) ----

MAX_DURATION_HOURS_MAJOR: float = 200.0
MAX_DURATION_HOURS_MINOR: float = 100.0

MIN_HPC_TIMESTEP_TINY: float = 1e-4  # seconds
HPC_DTMAX_FACTOR_WARN: float = 0.5   # ~0.5 * dx (seconds) heuristic

COURANT_C_ASSUMED: float = 3.0       # m/s for Classic pre-check
COURANT_MAJOR: float = 1.5
COURANT_MINOR: float = 1.0

MAX_OUTPUTS_MAJOR: float = 10000.0
MIN_OUTPUTS_MINOR: float = 2.0

# ---- Thresholds for parameter checks (6.x) ----

MANNING_MIN_ACCEPTABLE: float = 0.01
MANNING_MAX_ACCEPTABLE: float = 0.25
MANNING_CRITICAL_HIGH: float = 0.5

IL_MAJOR_THRESHOLD: float = 200.0    # mm
IL_CRITICAL_THRESHOLD: float = 500.0
CL_MAJOR_THRESHOLD: float = 50.0     # mm/hr
CL_CRITICAL_THRESHOLD: float = 200.0

# ---- Solution scheme normalization ----

SOLUTION_SCHEMES: Dict[str, Literal["HPC", "CLASSIC"]] = {
    "hpc": "HPC",
    "classic": "CLASSIC",
}
