"""
Configuration constants for TUFLOW QA/QC pre-run validator.

Includes file extensions, regex patterns, and validation thresholds.
"""

import re
from pathlib import Path
from typing import Set, Dict, Literal

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

# These allow-lists mirror TUFLOW documentation. They must be explicit; no
# inference from unknown directives is allowed. Keep entries lower-cased and
# whitespace-normalised for matching.

CONTROL_DIRECTIVES: Set[str] = {
    "read file",
    "geometry control file",
    "bc control file",
    "event control file",
    "quadtree control file",
    "estry control file",
    "structure control file",
    "event file",
    "rainfall control file",
    "operations control file",
    "read operating controls",
    "external stress file",
    "ad control file",
    "swmm control file",
}

INPUT_DIRECTIVES: Set[str] = {
    "soils file",
    "read soils file",
    "infiltration file",
    "losses file",
    "rainfall file",
    "rainfall pattern file",
    "read rainfall",
    "read rf",
    "inflow file",
    "flow hydrograph",
    "stage hydrograph",
    "hq file",
    "zq file",
    "qt file",
    "restart file",
    "initial conditions file",
    "read materials file",
    "read table",
    "read roughness file",
    "read resistance file",
    "blockage matrix file",
    "fews input file",
}

GIS_DIRECTIVES: Set[str] = {
    "read gis",
    "read gis z shape",
    "read gis code",
    "read gis attribute",
    "read gis materials",
    "read gis roughness",
    "read gis resistance",
    "read gis source",
    "read gis boundary",
    "read gis flow",
    "read bc",
    "read bc gis",
    "read source gis",
}

DATABASE_DIRECTIVES: Set[str] = {
    "bc database",
    "read bc database",
    "spatial database",
    "read structure database",
    "read attribute database",
}

GRID_DIRECTIVES: Set[str] = {
    "read grid",
    "read dem",
    "read asc",
    "read tif",
    "read tiff",
    "read bil",
    "read flt",
    "rainfall grid",
    "read rainfall grid",
}

NON_FILE_DIRECTIVES: Set[str] = {
    "scenario",
    "event",
    "else if scenario",
    "set variable",
    "define",
    "if",
    "else",
    "end if",
}

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
