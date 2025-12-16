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

SOIL_EXTS: Set[str] = {
    ".tsoilf",
}

GIS_EXTS: Set[str] = {
    ".shp", ".tab", ".mif", ".mid", ".gpkg", ".gdb",
    ".tif", ".tiff", ".asc", ".flt", ".grd",
}

DB_EXTS: Set[str] = {
    ".csv", ".txt", ".dat", ".dbf",
}

# ---- Control file keywords ----

CONTROL_KEY_HINTS: Set[str] = {
    "Geometry Control",
    "BC Control",
    "ESTRY Control",
    "Quadtree Control",
    "Event File",
    "Rainfall Control",
    "Operations Control",
    "Advection Dispersion Control",
    "Read File",  # generic include
}

INPUT_KEY_HINTS: Set[str] = {
    "Read Soils File",
    "Soils File",
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
