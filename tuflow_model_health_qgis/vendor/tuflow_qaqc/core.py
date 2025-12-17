"""
Core data types for TUFLOW QA/QC pre-run validator.

Includes dataclasses for issues, control files, test results, and summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Set


class Severity(str, Enum):
    """Issue severity levels."""
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"


@dataclass
class Issue:
    """A single validation issue found during QA checks."""
    id: str
    severity: Severity
    category: str
    message: str
    suggestion: str
    file: Optional[Path] = None
    line: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ControlDirective:
    """A single key==value directive from a control file."""
    keyword: str
    value: str
    line: int
    raw: str


@dataclass
class ControlFile:
    """A parsed TUFLOW control file."""
    path: Path
    directives: List[ControlDirective] = field(default_factory=list)


@dataclass
class ControlTree:
    """Tree structure of all control files in a model."""
    root_tcf: Path
    edges: Dict[Path, List[Path]]  # parent -> children
    all_files: Set[Path]
    issues: List[Issue]


class InputCategory(str, Enum):
    """Classification for model files discovered during scanning."""

    CONTROL = "CONTROL"
    INPUT = "INPUT"
    DATABASE = "DATABASE"
    GIS = "GIS"
    GRID = "GRID"


@dataclass
class ModelNode:
    """A node in the unified model tree used by the CLI, UI, and reports."""

    name: str
    path: Optional[Path]
    category: Optional[InputCategory]
    children: List["ModelNode"] = field(default_factory=list)
    exists: bool = True
    source_control: Optional[str] = None


@dataclass
class InputRef:
    """Reference to an input GIS or database file."""
    path: Path
    category: InputCategory
    from_control: Path
    line: int
    exists: bool
    layer: Optional[str] = None


@dataclass
class InputScanResult:
    """Result of scanning a model for all input file references."""
    tcf_path: Path
    control_tree: ControlTree
    inputs: List[InputRef]
    model_tree: Optional[ModelNode]
    debug_log: List[str] = field(default_factory=list)
    seen_directives: Set[str] = field(default_factory=set)
    missing_required_directives: List[str] = field(default_factory=list)


# ---- Stage 2: TUFLOW run test ----

@dataclass
class TuflowRunLogs:
    """Locations of TUFLOW log files for a single run."""
    log_dir: Path
    tlf: Optional[Path] = None
    hpc_tlf: Optional[Path] = None
    messages_csv: Optional[Path] = None


@dataclass
class TuflowTestResult:
    """Summary of the TUFLOW -t test run and basic log parsing."""
    tcf_path: Path
    return_code: Optional[int]
    logs: TuflowRunLogs
    errors: List[str] = field(default_factory=list)        # formatted error lines (from _messages.csv)
    warnings: List[str] = field(default_factory=list)      # optional summary strings
    checks: List[str] = field(default_factory=list)        # optional summary strings
    error_count: int = 0
    warning_count: int = 0
    check_count: int = 0
    message_number_counts: Dict[int, int] = field(default_factory=dict)  # msg_no -> count
    stdout: str = ""
    stderr: str = ""


# ---- Stage 3: TUFLOW .tlf / .hpc.tlf summaries ----

@dataclass
class TuflowMaterial:
    """Material properties extracted from .tlf."""
    index: int
    name: str
    manning_n: Optional[float] = None


@dataclass
class TuflowSoil:
    """Soil properties extracted from .tlf."""
    index: int
    name: str
    approach: str = ""
    initial_loss_mm: Optional[float] = None
    continuing_loss_mm_per_hr: Optional[float] = None


@dataclass
class TuflowTlfSummary:
    """Parsed summary of a TUFLOW .tlf log file."""
    path: Path
    has_running_line: bool = False
    solution_scheme: Optional[str] = None  # raw string from log, normalised later
    start_time_h: Optional[float] = None
    end_time_h: Optional[float] = None
    duration_h: Optional[float] = None

    map_output_interval_s: Optional[float] = None
    ts_output_interval_s: Optional[float] = None

    # Cell size from .tlf if present (HPC models usually from .hpc.tlf)
    cell_size_m: Optional[float] = None

    materials: List[TuflowMaterial] = field(default_factory=list)
    soils: List[TuflowSoil] = field(default_factory=list)


@dataclass
class TuflowHpcSummary:
    """Parsed summary of a TUFLOW .hpc.tlf log file."""
    path: Path
    cell_size_m: Optional[float] = None
    timestep_min_s: Optional[float] = None
    timestep_max_s: Optional[float] = None
    gpu_found: Optional[bool] = None
    gpu_error_messages: List[str] = field(default_factory=list)
