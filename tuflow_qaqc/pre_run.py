from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple
import re
import sys
import subprocess
import csv


# ---------- Core types ----------

class Severity(str, Enum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"


@dataclass
class Issue:
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
    keyword: str
    value: str
    line: int
    raw: str


@dataclass
class ControlFile:
    path: Path
    directives: List[ControlDirective] = field(default_factory=list)


@dataclass
class ControlTree:
    root_tcf: Path
    edges: Dict[Path, List[Path]]  # parent -> children
    all_files: Set[Path]
    issues: List[Issue]


@dataclass
class InputRef:
    path: Path
    kind: str  # "gis" or "database" or "other"
    from_control: Path
    line: int
    exists: bool


@dataclass
class InputScanResult:
    tcf_path: Path
    control_tree: ControlTree
    inputs: List[InputRef]

# ---------- Stage 2: TUFLOW run test (-t) ----------

@dataclass
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


# ---------- Stage 3: TUFLOW .tlf / .hpc.tlf summaries ----------

@dataclass
class TuflowMaterial:
    index: int
    name: str
    manning_n: Optional[float] = None


@dataclass
class TuflowSoil:
    index: int
    name: str
    approach: str = ""
    initial_loss_mm: Optional[float] = None
    continuing_loss_mm_per_hr: Optional[float] = None


@dataclass
class TuflowTlfSummary:
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
    path: Path
    cell_size_m: Optional[float] = None
    timestep_min_s: Optional[float] = None
    timestep_max_s: Optional[float] = None
    gpu_found: Optional[bool] = None
    gpu_error_messages: List[str] = field(default_factory=list)


# ---------- Regex & parsing helpers ----------

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

INLINE_COMMENT_SPLIT_RE = re.compile(r"(!|//|#)")
WILDCARD_RE = re.compile(r"~(?P<var>[A-Za-z0-9_]+)~")


def _strip_inline_comment(line: str) -> str:
    """Remove inline comments starting with ! or // or #."""
    parts = INLINE_COMMENT_SPLIT_RE.split(line, maxsplit=1)
    return parts[0]


def escape_regexp(str_: str) -> str:
    return re.escape(str_)


def parse_control_file(path: Path) -> ControlFile:
    """Parse a TUFLOW-style control file into directives (key == value lines)."""
    directives: List[ControlDirective] = []

    text = path.read_text(encoding="utf-8", errors="ignore")

    for i, raw_line in enumerate(text.splitlines(), start=1):
        no_comment = _strip_inline_comment(raw_line)
        line = no_comment.strip()
        if not line:
            continue
        if COMMENT_RE.match(line):
            continue

        m = DIRECTIVE_RE.match(line)
        if not m:
            # Non key==value lines (IF, DEFINE, etc.) are ignored at this stage
            continue

        key = m.group("key").strip()
        value = m.group("value").strip()
        directives.append(
            ControlDirective(keyword=key, value=value, line=i, raw=raw_line)
        )

    return ControlFile(path=path, directives=directives)


# ---------- Wildcard utilities ----------

def find_wildcards_in_filename(path: Path) -> List[str]:
    """Return wildcard names (without tildes) from a filename."""
    return [m.group("var") for m in WILDCARD_RE.finditer(path.name)]


def build_wildcard_map_from_args(
    filename_wildcards: List[str],
    argv: List[str],
) -> Dict[str, str]:
    """
    Build a wildcard->value map from CLI args.
    Supports args like: -e1 00100Y -e2 0060m -s1 5m -s2 CL0
    If any required wildcard is missing, prompt the user.
    """
    supplied: Dict[str, str] = {}

    # Very simple CLI parsing: look for '-name value' pairs
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("-") and len(token) > 1:
            name = token[1:]  # e.g. "-e1" -> "e1"
            if i + 1 < len(argv):
                supplied[name] = argv[i + 1]
                i += 2
                continue
        i += 1

    # Prompt for any missing required wildcards
    for w in filename_wildcards:
        if w not in supplied:
            prompt_name = f"-{w}"
            val = input(f"Enter value for {prompt_name}: ").strip()
            supplied[w] = val

    return supplied


def substitute_wildcards(value: str, wildcards: Dict[str, str]) -> str:
    """Replace ~var~ tokens in a string with provided wildcard values (if available)."""

    def repl(match: re.Match) -> str:
        var = match.group("var")
        return wildcards.get(var, match.group(0))  # leave as-is if not provided

    return WILDCARD_RE.sub(repl, value)


# ---------- Control file tree (Stage 0) ----------

CONTROL_EXTS = {
    ".tcf", ".tgc", ".tbc", ".ecf",
    ".qcf", ".tef", ".toc", ".trfc",
    ".adcf", ".tsoilf",
}

# Keywords that typically reference another control file
CONTROL_KEY_HINTS = {
    "Geometry Control",
    "BC Control",
    "ESTRY Control",
    "Quadtree Control",
    "Event File",
    "Rainfall Control",
    "Operations Control",
    "Soils File",
    "Advection Dispersion Control",
    "Read File",  # generic include
}

# Default TUFLOW executable name (can be overridden via CLI or QGIS settings)
DEFAULT_TUFLOW_EXE = Path("TUFLOW_iSP_w64.exe")


def is_control_file_path(p: Path) -> bool:
    return p.suffix.lower() in CONTROL_EXTS


def _collect_control_children(
    cf: ControlFile,
    wildcards: Dict[str, str],
) -> List[Path]:
    """
    From a parsed control file, find all referenced control files,
    substituting wildcards in the values.
    """
    children: List[Path] = []
    base_dir = cf.path.parent

    for d in cf.directives:
        key = d.keyword.strip()
        if not any(h.lower() in key.lower() for h in CONTROL_KEY_HINTS):
            # Not a known control-file directive; skip
            continue

        # Substitute wildcards in the value (path)
        value = substitute_wildcards(d.value, wildcards)

        # Simple token split: allow for multiple filenames in one line
        tokens = re.split(r"[\s,;]+", value.strip('"').strip("'"))
        for tok in tokens:
            if not tok:
                continue
            p = (base_dir / tok).resolve()
            if is_control_file_path(p):
                children.append(p)

    return children


def build_control_tree(
    tcf_path: Path,
    wildcards: Dict[str, str],
) -> ControlTree:
    """
    Build a tree of control files starting from the main TCF.
    We DO NOT modify the TCF filename itself; wildcards are only used
    when resolving referenced control-file paths.
    """
    edges: Dict[Path, List[Path]] = {}
    all_files: Set[Path] = set()
    issues: List[Issue] = []
    visited: Set[Path] = set()

    def visit(path: Path) -> None:
        if path in visited:
            return
        visited.add(path)
        all_files.add(path)
        edges.setdefault(path, [])

        if not path.exists():
            issues.append(
                Issue(
                    id="CT001_CONTROL_FILE_MISSING",
                    severity=Severity.CRITICAL,
                    category="ControlFiles",
                    message=f"Control file not found: {path}",
                    suggestion=(
                        "Check that the file exists and that the path is correct in the calling control file."
                    ),
                    file=path,
                )
            )
            return

        try:
            cf = parse_control_file(path)
        except Exception as e:
            issues.append(
                Issue(
                    id="CT002_CONTROL_FILE_READ_ERROR",
                    severity=Severity.CRITICAL,
                    category="ControlFiles",
                    message=f"Error reading control file {path}: {e}",
                    suggestion="Check file permissions and encoding.",
                    file=path,
                )
            )
            return

        children = _collect_control_children(cf, wildcards)
        edges[path] = children
        for child in children:
            visit(child)

    visit(tcf_path)

    return ControlTree(
        root_tcf=tcf_path,
        edges=edges,
        all_files=all_files,
        issues=issues,
    )


# ---------- Stage 1: scan input GIS layers and databases ----------

GIS_EXTS = {
    ".shp", ".tab", ".mif", ".mid", ".gpkg", ".gdb",
    ".tif", ".tiff", ".asc", ".flt", ".grd",
}
DB_EXTS = {
    ".csv", ".txt", ".dat", ".dbf",
}


def _categorise_input_path(p: Path, keyword: str) -> str:
    """Roughly categorise an input file as gis/database/other."""
    ext = p.suffix.lower()
    if ext in GIS_EXTS:
        return "gis"
    if ext in DB_EXTS:
        return "database"
    # Prefer marking 'Database' keywords as database even without known ext
    if "database" in keyword.lower():
        return "database"
    return "other"


def _scan_inputs_in_control_file(
    path: Path,
    wildcards: Dict[str, str],
) -> List[InputRef]:
    """Scan a single control file for input file references (GIS, CSV, etc.)."""
    inputs: List[InputRef] = []

    if not path.exists():
        return inputs

    base_dir = path.parent
    text = path.read_text(encoding="utf-8", errors="ignore")

    for i, raw_line in enumerate(text.splitlines(), start=1):
        no_comment = _strip_inline_comment(raw_line)
        line = no_comment.strip()
        if not line or COMMENT_RE.match(line):
            continue

        m = DIRECTIVE_RE.match(line)
        if not m:
            continue

        key = m.group("key").strip()
        val_raw = m.group("value").strip()

        # Substitute wildcards in the value
        val = substitute_wildcards(val_raw, wildcards)

        # Heuristic: if the keyword strongly suggests an input file, or the
        # value looks like a filename with an extension
        tokens = re.split(r"[\s,;]+", val.strip('"').strip("'"))
        for tok in tokens:
            if not tok:
                continue

            # Only treat tokens with a dot as file-like
            if "." not in tok:
                continue

            p = (base_dir / tok).resolve()
            kind = _categorise_input_path(p, key)

            # Only keep those that look like genuine inputs
            if kind in {"gis", "database"}:
                exists = p.exists()
                inputs.append(
                    InputRef(
                        path=p,
                        kind=kind,
                        from_control=path,
                        line=i,
                        exists=exists,
                    )
                )

    return inputs


def scan_all_inputs(
    tcf_path: Path,
    wildcards: Dict[str, str],
) -> InputScanResult:
    """
    Stage 1: given a TCF and wildcard values, build the control tree,
    then scan all control files for GIS and database inputs.
    """
    control_tree = build_control_tree(tcf_path, wildcards)
    seen_paths: Set[Path] = set()
    all_inputs: List[InputRef] = []

    for cf_path in control_tree.all_files:
        inputs = _scan_inputs_in_control_file(cf_path, wildcards)
        for inp in inputs:
            # avoid duplicates: (path, from_control, line) can be unique;
            # but here we just dedupe by path and kind
            key = (inp.path, inp.kind)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            all_inputs.append(inp)

    return InputScanResult(
        tcf_path=tcf_path,
        control_tree=control_tree,
        inputs=all_inputs,
    )

# ---------- Stage 2 helpers: log stem, log folder, TUFLOW -t, log parsing ----------

def build_log_stem(tcf_path: Path, wildcards: Dict[str, str]) -> str:
    """
    Build the log file name stem from the TCF filename stem by substituting
    ~var~ tokens with wildcard values. This does NOT change which TCF file
    is run – it is only used to locate log files.
    """
    return substitute_wildcards(tcf_path.stem, wildcards)


def find_log_folder(
    tcf_path: Path,
    wildcards: Dict[str, str],
    control_files: Set[Path],
) -> Path:
    """
    Determine the log folder for this run.

    Priority:
      1) 'Log Folder ==' directive in the TCF (after wildcard substitution)
      2) 'Log Folder ==' directive in any other control file
      3) Fallback: the TCF's parent directory
    """
    # 1) Prefer Log Folder in the TCF
    ordered_files: List[Path] = [tcf_path] + [
        p for p in control_files if p != tcf_path
    ]

    for path in ordered_files:
        if not path.exists():
            continue

        try:
            cf = parse_control_file(path)
        except Exception:
            continue

        for d in cf.directives:
            if d.keyword.strip().lower() == "log folder":
                raw = substitute_wildcards(d.value, wildcards).strip()
                raw = raw.strip('"').strip("'")
                if not raw:
                    continue
                base_dir = path.parent
                log_dir = (base_dir / raw).resolve()
                return log_dir

    # 3) Fallback
    return tcf_path.parent


def run_tuflow_test(
    tcf_path: Path,
    tuflow_exe: Path,
    wildcards: Dict[str, str],
) -> Tuple[int, str, str]:
    """
    Run TUFLOW in test mode (-t) for the given TCF.

    Correct form (as per CMD usage):
        TUFLOW.exe -t -b -e1 value -e2 value ... full\path\model.tcf
    """
    cmd = [str(tuflow_exe), "-t", "-b"]

    # Append wildcard flags BEFORE the TCF file path
    # Example: -e1 05p -e2 1hr
    for key in sorted(wildcards.keys()):
        value = wildcards[key]
        if not key:
            continue
        flag = f"-{key}"
        cmd.append(flag)
        cmd.append(str(value))

    # NOW append the full TCF path (with wildcards unresolved)
    cmd.append(str(tcf_path))

    try:
        proc = subprocess.run(
            cmd,
            cwd=tcf_path.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError as e:
        return -1, "", str(e)

    return proc.returncode, proc.stdout, proc.stderr


def find_tuflow_logs(
    tcf_path: Path,
    wildcards: Dict[str, str],
    control_tree: ControlTree,
) -> TuflowRunLogs:
    """
    Use Log Folder (if any) and the resolved log stem to locate the .tlf,
    .hpc.tlf, and _messages.csv files for this run.
    """
    log_dir = find_log_folder(tcf_path, wildcards, control_tree.all_files)
    log_stem = build_log_stem(tcf_path, wildcards)

    tlf_path = log_dir / f"{log_stem}.tlf"
    hpc_tlf_path = log_dir / f"{log_stem}.hpc.tlf"
    messages_path = log_dir / f"{log_stem}_messages.csv"

    if not tlf_path.exists():
        tlf_path = None
    if not hpc_tlf_path.exists():
        hpc_tlf_path = None
    if not messages_path.exists():
        messages_path = None

    return TuflowRunLogs(
        log_dir=log_dir,
        tlf=tlf_path,
        hpc_tlf=hpc_tlf_path,
        messages_csv=messages_path,
    )


def _parse_single_log(path: Path) -> Tuple[List[str], List[str], List[str]]:
    """
    Parse a single TUFLOW log file (.tlf or .hpc.tlf) for ERROR, WARNING, CHECK lines.

    This is a simple first pass; later we can extend it to parse the Simulation Summary.
    """
    errors: List[str] = []
    warnings: List[str] = []
    checks: List[str] = []

    if not path or not path.exists():
        return errors, warnings, checks

    text = path.read_text(encoding="utf-8", errors="ignore")

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        upper = stripped.upper()
        if "ERROR" in upper:
            errors.append(stripped)
        elif "WARNING" in upper:
            warnings.append(stripped)
        elif "CHECK" in upper:
            checks.append(stripped)

    return errors, warnings, checks


def parse_messages_csv(path: Path) -> Tuple[int, int, int, List[str], Dict[int, int]]:
    """
    Parse the TUFLOW <stem>_messages.csv file.

    Returns:
        error_count, warning_count, check_count,
        error_lines (formatted strings),
        message_number_counts (msg_no -> count)
    """
    error_count = 0
    warning_count = 0
    check_count = 0
    error_lines: List[str] = []
    message_number_counts: Dict[int, int] = {}

    if not path or not path.exists():
        return error_count, warning_count, check_count, error_lines, message_number_counts

    with path.open("r", newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 6:
                continue
            try:
                msg_no = int(row[0])
                code = int(row[1])
            except ValueError:
                # skip header or malformed rows
                continue

            x = row[2].strip()
            y = row[3].strip()
            text = row[4].strip()
            link = row[5].strip()

            # Count per message number
            message_number_counts[msg_no] = message_number_counts.get(msg_no, 0) + 1

            if code == 1:
                error_count += 1
                # formatted error line with coordinates and link
                formatted = (
                    f"{msg_no}: {text} (X={x}, Y={y}) [{link}]"
                    if link
                    else f"{msg_no}: {text} (X={x}, Y={y})"
                )
                error_lines.append(formatted)
            elif code == 2:
                warning_count += 1
            elif code == 3:
                check_count += 1

    return error_count, warning_count, check_count, error_lines, message_number_counts


def run_tuflow_test_and_analyse(
    tcf_path: Path,
    wildcards: Dict[str, str],
    control_tree: ControlTree,
    tuflow_exe: Path,
) -> TuflowTestResult:
    """
    Stage 2: Run TUFLOW in test mode (-t), then locate and parse the log files.

    IMPORTANT:
    - Errors, Warnings and Checks are taken ONLY from the <stem>_messages.csv file.
    - We do NOT use .tlf / .hpc.tlf for error/warning/check classification.
    """
    return_code, stdout, stderr = run_tuflow_test(tcf_path, tuflow_exe, wildcards)

    logs = find_tuflow_logs(tcf_path, wildcards, control_tree)

    error_count = 0
    warning_count = 0
    check_count = 0
    error_lines: List[str] = []
    msg_number_counts: Dict[int, int] = {}

    if logs.messages_csv:
        (
            error_count,
            warning_count,
            check_count,
            error_lines,
            msg_number_counts,
        ) = parse_messages_csv(logs.messages_csv)

    # For warnings/checks we keep short summary strings (for CLI display)
    warnings_summary: List[str] = []
    checks_summary: List[str] = []

    if warning_count > 0:
        warnings_summary.append(f"Total warnings in messages.csv: {warning_count}")
    if check_count > 0:
        checks_summary.append(f"Total checks in messages.csv: {check_count}")

    return TuflowTestResult(
        tcf_path=tcf_path,
        return_code=return_code,
        logs=logs,
        errors=error_lines,
        warnings=warnings_summary,
        checks=checks_summary,
        error_count=error_count,
        warning_count=warning_count,
        check_count=check_count,
        message_number_counts=msg_number_counts,
        stdout=stdout,
        stderr=stderr,
    )


# ---------- Stage 3 helpers: parse .tlf / .hpc.tlf and run QA checks (5.x & 6.x) ----------

# Simple float extractor for log lines
_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")

def _extract_first_float(text: str) -> Optional[float]:
    m = _FLOAT_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_tlf_summary(tlf_path: Optional[Path]) -> Optional[TuflowTlfSummary]:
    """
    Parse a TUFLOW .tlf log file into a structured summary.

    If tlf_path is None or does not exist, returns None.
    """
    if not tlf_path or not tlf_path.exists():
        return None

    text = tlf_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    summary = TuflowTlfSummary(path=tlf_path)

    # First pass: high-level flags and scalar values
    for line in lines:
        stripped = line.strip()

        # Run-test success marker
        if "Running TUFLOW" in stripped:
            summary.has_running_line = True

        # Solution Scheme (HPC / Classic / etc.)
        if "2D Solution Scheme" in stripped and "==" in stripped:
            parts = stripped.split("==", 1)
            value = parts[1].strip() if len(parts) > 1 else ""
            summary.solution_scheme = value

        # Start / End time in hours
        if stripped.startswith("Start Time (h)") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.start_time_h = val

        if stripped.startswith("End Time (h)") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.end_time_h = val

        # Output intervals
        if "ASC Map Output Interval (s)" in stripped and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.map_output_interval_s = val

        if "Time Series Output Interval (s)" in stripped and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.ts_output_interval_s = val

        # Cell size (if reported in .tlf)
        if stripped.startswith("Cell Size") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.cell_size_m = val

    if summary.start_time_h is not None and summary.end_time_h is not None:
        summary.duration_h = summary.end_time_h - summary.start_time_h

    # Second pass: materials and soils blocks
    current_material: Optional[TuflowMaterial] = None
    current_soil: Optional[TuflowSoil] = None

    for line in lines:
        stripped = line.strip()

        # Material header, e.g. "#1 - Material 1:"
        if stripped.startswith("#") and "Material" in stripped:
            current_soil = None
            try:
                hash_removed = stripped.lstrip("#").strip()
                idx_part, name_part = hash_removed.split("-", 1)
                idx = int(idx_part.strip())
                name = name_part.strip().rstrip(":")
            except Exception:
                idx = -1
                name = stripped

            current_material = TuflowMaterial(index=idx, name=name)
            summary.materials.append(current_material)
            continue

        # Soil header, e.g. "#1 - Soil 1:"
        if stripped.startswith("#") and "Soil" in stripped:
            current_material = None
            try:
                hash_removed = stripped.lstrip("#").strip()
                idx_part, name_part = hash_removed.split("-", 1)
                idx = int(idx_part.strip())
                name = name_part.strip().rstrip(":")
            except Exception:
                idx = -1
                name = stripped

            current_soil = TuflowSoil(index=idx, name=name)
            summary.soils.append(current_soil)
            continue

        # Inside Material block
        if current_material is not None:
            if "Fixed Manning's n" in stripped and "=" in stripped:
                val = _extract_first_float(stripped)
                if val is not None:
                    current_material.manning_n = val
            continue

        # Inside Soil block
        if current_soil is not None:
            if stripped.startswith("Soil Approach"):
                parts = stripped.split(":", 1)
                if len(parts) > 1:
                    current_soil.approach = parts[1].strip()
            elif stripped.startswith("Initial Loss") and "=" in stripped:
                val = _extract_first_float(stripped)
                if val is not None:
                    current_soil.initial_loss_mm = val
            elif stripped.startswith("Continuing Loss") and "=" in stripped:
                val = _extract_first_float(stripped)
                if val is not None:
                    current_soil.continuing_loss_mm_per_hr = val
            continue

    return summary


def parse_hpc_tlf_summary(hpc_tlf_path: Optional[Path]) -> Optional[TuflowHpcSummary]:
    """
    Parse a TUFLOW .hpc.tlf log file into a structured summary.

    If hpc_tlf_path is None or does not exist, returns None.
    """
    if not hpc_tlf_path or not hpc_tlf_path.exists():
        return None

    text = hpc_tlf_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    summary = TuflowHpcSummary(path=hpc_tlf_path)

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("Cell Size") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.cell_size_m = val

        if stripped.startswith("Timestep Minimum") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.timestep_min_s = val

        if stripped.startswith("Timestep Maximum") and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                summary.timestep_max_s = val

        upper = stripped.upper()
        if "CUDA" in upper and "DEVICE" in upper and "FOUND" in upper:
            summary.gpu_found = True
        if "CUDA" in upper and any(w in upper for w in ("FAILED", "ERROR", "NOT FOUND", "UNABLE")):
            summary.gpu_error_messages.append(stripped)
            if summary.gpu_found is None:
                summary.gpu_found = False

    return summary


# Thresholds for 5.x / 6.x checks
MAX_DURATION_HOURS_MAJOR = 200.0
MAX_DURATION_HOURS_MINOR = 100.0

MIN_HPC_TIMESTEP_TINY = 1e-4  # seconds
HPC_DTMAX_FACTOR_WARN = 0.5   # ~0.5 * dx (seconds) heuristic

COURANT_C_ASSUMED = 3.0       # m/s for Classic pre-check
COURANT_MAJOR = 1.5
COURANT_MINOR = 1.0

MAX_OUTPUTS_MAJOR = 10000.0
MIN_OUTPUTS_MINOR = 2.0

MANNING_MIN_ACCEPTABLE = 0.01
MANNING_MAX_ACCEPTABLE = 0.25
MANNING_CRITICAL_HIGH = 0.5

IL_MAJOR_THRESHOLD = 200.0    # mm
IL_CRITICAL_THRESHOLD = 500.0
CL_MAJOR_THRESHOLD = 50.0     # mm/hr
CL_CRITICAL_THRESHOLD = 200.0


def _normalise_solution_scheme(raw: Optional[str]) -> Optional[str]:
    """Normalise solution scheme string to 'HPC', 'Classic', or raw."""
    if not raw:
        return None
    u = raw.upper()
    if "HPC" in u:
        return "HPC"
    if "CLASSIC" in u:
        return "CLASSIC"
    return raw.strip()


def _make_issue(
    issue_id: str,
    severity: Severity,
    category: str,
    message: str,
    suggestion: str = "",
    file: Optional[Path] = None,
    line: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Issue:
    return Issue(
        id=issue_id,
        severity=severity,
        category=category,
        message=message,
        suggestion=suggestion,
        file=file,
        line=line,
        details=details or {},
    )


# ---- 5.x time control & timestep checks ----

def _check_run_test_success(
    tlf_summary: Optional[TuflowTlfSummary],
    test_result: TuflowTestResult,
) -> List[Issue]:
    issues: List[Issue] = []

    if test_result.error_count > 0:
        issues.append(
            _make_issue(
                "TIME00",
                Severity.CRITICAL,
                "TimeControl",
                f"Run test reported {test_result.error_count} error(s) in _messages.csv.",
                suggestion="Review the error messages above and the linked TUFLOW wiki pages, then fix the model setup.",
                file=test_result.logs.messages_csv,
            )
        )

    if not tlf_summary:
        issues.append(
            _make_issue(
                "TIME01",
                Severity.CRITICAL,
                "TimeControl",
                "No .tlf log file found; cannot confirm run-test success.",
                suggestion="Check Log Folder settings and that the TUFLOW run completed to the log-writing stage.",
                file=test_result.logs.tlf,
            )
        )
        return issues

    if not tlf_summary.has_running_line:
        issues.append(
            _make_issue(
                "TIME02",
                Severity.CRITICAL,
                "TimeControl",
                "Run test did not reach 'Running TUFLOW...' message in .tlf.",
                suggestion="Review messages.csv for errors and ensure the model passes all TUFLOW QC checks.",
                file=tlf_summary.path,
            )
        )

    return issues


def _check_time_window(
    tlf_summary: Optional[TuflowTlfSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    st = tlf_summary.start_time_h
    et = tlf_summary.end_time_h
    dur = tlf_summary.duration_h

    if st is None or et is None:
        issues.append(
            _make_issue(
                "TIME10",
                Severity.CRITICAL,
                "TimeControl",
                "Start Time (h) or End Time (h) not reported in .tlf.",
                suggestion="Check that Start Time and End Time are defined in the control files.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur is None:
        issues.append(
            _make_issue(
                "TIME11",
                Severity.CRITICAL,
                "TimeControl",
                "Simulation duration could not be computed from Start/End times.",
                suggestion="Check Start Time and End Time definitions in the control files.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur <= 0:
        issues.append(
            _make_issue(
                "TIME12",
                Severity.CRITICAL,
                "TimeControl",
                f"Simulation duration is non-positive (Start={st} h, End={et} h).",
                suggestion="Confirm Start Time and End Time are correct and in hours.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur > MAX_DURATION_HOURS_MAJOR:
        issues.append(
            _make_issue(
                "TIME13",
                Severity.MAJOR,
                "TimeControl",
                f"Simulation duration is {dur:.1f} h, which exceeds {MAX_DURATION_HOURS_MAJOR} h.",
                suggestion="Confirm that the End Time is correct and that the long duration is intentional.",
                file=tlf_summary.path,
            )
        )
    elif dur > MAX_DURATION_HOURS_MINOR:
        issues.append(
            _make_issue(
                "TIME14",
                Severity.MINOR,
                "TimeControl",
                f"Simulation duration is {dur:.1f} h (above {MAX_DURATION_HOURS_MINOR} h).",
                suggestion="Check that the simulation duration is appropriate for the event being modelled.",
                file=tlf_summary.path,
            )
        )

    return issues


def _check_output_intervals(
    tlf_summary: Optional[TuflowTlfSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    dur = tlf_summary.duration_h
    map_int = tlf_summary.map_output_interval_s
    ts_int = tlf_summary.ts_output_interval_s

    # Map outputs
    if map_int is None:
        issues.append(
            _make_issue(
                "OUT01",
                Severity.MINOR,
                "OutputInterval",
                "ASC Map Output Interval (s) not reported in .tlf (TUFLOW defaults may apply).",
                suggestion="Consider explicitly setting Map Output Interval in the control files for clarity.",
                file=tlf_summary.path,
            )
        )
    elif map_int <= 0:
        issues.append(
            _make_issue(
                "OUT02",
                Severity.CRITICAL,
                "OutputInterval",
                f"ASC Map Output Interval (s) is non-positive: {map_int}.",
                suggestion="Set a positive Map Output Interval in seconds.",
                file=tlf_summary.path,
            )
        )
    elif dur is not None and dur > 0:
        n = dur * 3600.0 / map_int
        if n > MAX_OUTPUTS_MAJOR:
            issues.append(
                _make_issue(
                    "OUT03",
                    Severity.MAJOR,
                    "OutputInterval",
                    f"Map outputs count ~{n:.0f}, which exceeds {MAX_OUTPUTS_MAJOR:.0f}.",
                    suggestion="Increase Map Output Interval to reduce output volume and improve performance.",
                    file=tlf_summary.path,
                )
            )
        elif n < MIN_OUTPUTS_MINOR:
            issues.append(
                _make_issue(
                    "OUT04",
                    Severity.MINOR,
                    "OutputInterval",
                    f"Map outputs count ~{n:.1f} (very few; may miss temporal behaviour).",
                    suggestion="Decrease Map Output Interval if more temporal detail is required.",
                    file=tlf_summary.path,
                )
            )

    # Time series outputs
    if ts_int is None:
        issues.append(
            _make_issue(
                "OUT05",
                Severity.MINOR,
                "OutputInterval",
                "Time Series Output Interval (s) not reported in .tlf (TUFLOW defaults may apply).",
                suggestion="Consider explicitly setting Time Series Output Interval in the control files.",
                file=tlf_summary.path,
            )
        )
    elif ts_int <= 0:
        issues.append(
            _make_issue(
                "OUT06",
                Severity.CRITICAL,
                "OutputInterval",
                f"Time Series Output Interval (s) is non-positive: {ts_int}.",
                suggestion="Set a positive Time Series Output Interval in seconds.",
                file=tlf_summary.path,
            )
        )
    elif dur is not None and dur > 0:
        n = dur * 3600.0 / ts_int
        if n > MAX_OUTPUTS_MAJOR:
            issues.append(
                _make_issue(
                    "OUT07",
                    Severity.MAJOR,
                    "OutputInterval",
                    f"Time series outputs count ~{n:.0f}, which exceeds {MAX_OUTPUTS_MAJOR:.0f}.",
                    suggestion="Increase Time Series Output Interval to reduce output volume and improve performance.",
                    file=tlf_summary.path,
                )
            )
        elif n < MIN_OUTPUTS_MINOR:
            issues.append(
                _make_issue(
                    "OUT08",
                    Severity.MINOR,
                    "OutputInterval",
                    f"Time series outputs count ~{n:.1f} (very few; may miss hydrograph shape).",
                    suggestion="Decrease Time Series Output Interval if more temporal detail is required.",
                    file=tlf_summary.path,
                )
            )

    return issues


def _check_solution_scheme_and_logs(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)

    if scheme == "HPC":
        if hpc_summary is None:
            issues.append(
                _make_issue(
                    "SCHEME01",
                    Severity.MAJOR,
                    "SolverScheme",
                    "2D Solution Scheme == HPC but .hpc.tlf log file is missing.",
                    suggestion="Check Log Folder settings and ensure the HPC solver is executed.",
                    file=tlf_summary.path,
                )
            )

    return issues


def _check_timestep_hpc(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme != "HPC":
        return issues

    if hpc_summary is None:
        return issues  # already flagged in scheme check

    dt_min = hpc_summary.timestep_min_s
    dt_max = hpc_summary.timestep_max_s
    dx = hpc_summary.cell_size_m

    if dt_min is not None and dt_min <= 0:
        issues.append(
            _make_issue(
                "HPC_TS01",
                Severity.CRITICAL,
                "TimestepHPC",
                f"HPC minimum timestep is non-positive: {dt_min} s.",
                suggestion="Review the model stability and timestep controls.",
                file=hpc_summary.path,
            )
        )
    elif dt_min is not None and dt_min < MIN_HPC_TIMESTEP_TINY:
        issues.append(
            _make_issue(
                "HPC_TS02",
                Severity.MAJOR,
                "TimestepHPC",
                f"HPC minimum timestep is extremely small: {dt_min} s.",
                suggestion="Investigate local instabilities or highly restrictive conditions in the model.",
                file=hpc_summary.path,
            )
        )

    if dx is not None and dt_max is not None:
        if dt_max > HPC_DTMAX_FACTOR_WARN * dx:
            issues.append(
                _make_issue(
                    "HPC_TS03",
                    Severity.MINOR,
                    "TimestepHPC",
                    f"HPC maximum timestep ({dt_max} s) is large relative to cell size ({dx} m).",
                    suggestion="Consider capping Timestep Maximum to around 0.5 * cell size (in seconds) if stability issues occur.",
                    file=hpc_summary.path,
                )
            )

    return issues


def _check_timestep_classic(
    tlf_summary: Optional[TuflowTlfSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme == "HPC":
        return issues  # handled by HPC checks

    dx = tlf_summary.cell_size_m
    dt: Optional[float] = None

    # Try to find "Time Step (s) ==" line in the .tlf
    text = tlf_summary.path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        stripped = line.strip()
        if ("Time Step" in stripped or "TimeStep" in stripped) and "(s)" in stripped and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                dt = val
                break

    if dx is None or dt is None:
        return issues  # cannot compute Courant estimate

    c = COURANT_C_ASSUMED
    C = dt * c / dx

    if C > COURANT_MAJOR:
        issues.append(
            _make_issue(
                "CLASSIC_TS01",
                Severity.MAJOR,
                "TimestepClassic",
                f"Estimated Courant number C ≈ {C:.2f} (dx={dx} m, dt={dt} s) exceeds {COURANT_MAJOR}.",
                suggestion="Reduce the timestep or increase cell size to improve numerical stability.",
                file=tlf_summary.path,
            )
        )
    elif C > COURANT_MINOR:
        issues.append(
            _make_issue(
                "CLASSIC_TS02",
                Severity.MINOR,
                "TimestepClassic",
                f"Estimated Courant number C ≈ {C:.2f} (dx={dx} m, dt={dt} s) exceeds {COURANT_MINOR}.",
                suggestion="Consider reducing timestep if the model shows signs of instability.",
                file=tlf_summary.path,
            )
        )

    return issues


def run_time_and_timestep_checks(
    tcf_path: Path,
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
    test_result: TuflowTestResult,
) -> List[Issue]:
    """
    Aggregate all 5.x checks into a single list of Issues.
    """
    issues: List[Issue] = []

    issues.extend(_check_run_test_success(tlf_summary, test_result))
    issues.extend(_check_time_window(tlf_summary))
    issues.extend(_check_output_intervals(tlf_summary))
    issues.extend(_check_solution_scheme_and_logs(tlf_summary, hpc_summary))
    issues.extend(_check_timestep_hpc(tlf_summary, hpc_summary))
    issues.extend(_check_timestep_classic(tlf_summary))

    return issues


# ---- 6.x parameter sanity checks ----

def _check_manning_n(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    if not tlf_summary.materials:
        issues.append(
            _make_issue(
                "N00",
                Severity.MINOR,
                "ManningN",
                "No material values reported in .tlf; Manning's n sanity check skipped.",
                suggestion="Confirm that materials are defined and that the .tlf contains material values.",
                file=tlf_summary.path,
            )
        )
        return issues

    ns: List[float] = []
    out_of_range_materials: List[str] = []
    critical_materials: List[str] = []

    for mat in tlf_summary.materials:
        if mat.manning_n is None:
            continue
        n = mat.manning_n
        ns.append(n)
        label = f"{mat.name} (index {mat.index})"

        if n <= 0.0 or n >= MANNING_CRITICAL_HIGH:
            critical_materials.append(f"{label}: n={n}")
        elif n < MANNING_MIN_ACCEPTABLE or n > MANNING_MAX_ACCEPTABLE:
            out_of_range_materials.append(f"{label}: n={n}")

    if not ns:
        issues.append(
            _make_issue(
                "N01",
                Severity.MINOR,
                "ManningN",
                "No Manning's n values could be read from Material Values block.",
                suggestion="Check the material definitions in the control files.",
                file=tlf_summary.path,
            )
        )
        return issues

    min_n = min(ns)
    max_n = max(ns)

    if critical_materials:
        issues.append(
            _make_issue(
                "N02",
                Severity.CRITICAL,
                "ManningN",
                f"Manning's n has non-physical or extreme values (min={min_n:.3f}, max={max_n:.3f}).",
                suggestion="Review material roughness values; correct any non-physical entries.",
                file=tlf_summary.path,
                details={"materials": critical_materials},
            )
        )
    elif out_of_range_materials:
        issues.append(
            _make_issue(
                "N03",
                Severity.MAJOR,
                "ManningN",
                f"Manning's n values outside [{MANNING_MIN_ACCEPTABLE}, {MANNING_MAX_ACCEPTABLE}] "
                f"(min={min_n:.3f}, max={max_n:.3f}).",
                suggestion="Confirm that high or low roughness values are intentional and documented.",
                file=tlf_summary.path,
                details={"materials": out_of_range_materials},
            )
        )

    return issues


def _check_soil_ilcl(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    soils = [
        s
        for s in tlf_summary.soils
        if s.approach.strip().lower().startswith("initial loss/continuing loss".lower())
    ]

    if not soils:
        return issues  # no IL/CL soils to check

    il_values: List[float] = []
    cl_values: List[float] = []
    major_list: List[str] = []
    critical_list: List[str] = []

    for soil in soils:
        label = f"{soil.name} (index {soil.index})"
        il = soil.initial_loss_mm
        cl = soil.continuing_loss_mm_per_hr

        if il is not None:
            il_values.append(il)
            if il < 0:
                critical_list.append(f"{label}: IL={il} mm (negative)")
            elif il > IL_CRITICAL_THRESHOLD:
                critical_list.append(f"{label}: IL={il} mm (> {IL_CRITICAL_THRESHOLD} mm)")
            elif il > IL_MAJOR_THRESHOLD:
                major_list.append(f"{label}: IL={il} mm (> {IL_MAJOR_THRESHOLD} mm)")

        if cl is not None:
            cl_values.append(cl)
            if cl < 0:
                critical_list.append(f"{label}: CL={cl} mm/hr (negative)")
            elif cl > CL_CRITICAL_THRESHOLD:
                critical_list.append(f"{label}: CL={cl} mm/hr (> {CL_CRITICAL_THRESHOLD} mm/hr)")
            elif cl > CL_MAJOR_THRESHOLD:
                major_list.append(f"{label}: CL={cl} mm/hr (> {CL_MAJOR_THRESHOLD} mm/hr)")

    if critical_list:
        issues.append(
            _make_issue(
                "ILCL01",
                Severity.CRITICAL,
                "SoilILCL",
                "Soil IL/CL parameters have critical or non-physical values.",
                suggestion="Check soil loss parameters and correct any non-physical or extreme values.",
                file=tlf_summary.path,
                details={"soils": critical_list},
            )
        )
    elif major_list:
        issues.append(
            _make_issue(
                "ILCL02",
                Severity.MAJOR,
                "SoilILCL",
                "Soil IL/CL parameters have values outside recommended ranges.",
                suggestion="Confirm that large IL/CL values are intentional and justified.",
                file=tlf_summary.path,
                details={"soils": major_list},
            )
        )

    return issues


def _check_solver_hardware(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme != "HPC":
        return issues

    if hpc_summary is None:
        return issues  # missing .hpc.tlf already covered elsewhere

    if hpc_summary.gpu_found is False or hpc_summary.gpu_error_messages:
        details: Dict[str, Any] = {}
        if hpc_summary.gpu_error_messages:
            details["gpu_errors"] = hpc_summary.gpu_error_messages

        issues.append(
            _make_issue(
                "SOLV01",
                Severity.MAJOR,
                "SolverHardware",
                "HPC solver encountered GPU/driver issues; check CUDA / GPU configuration.",
                suggestion="Review .hpc.tlf for CUDA / GPU errors and confirm the correct GPU drivers are installed.",
                file=hpc_summary.path,
                details=details,
            )
        )

    return issues


def run_parameter_sanity_checks(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    """
    Aggregate all 6.x parameter sanity checks into a single list of Issues.
    """
    issues: List[Issue] = []

    issues.extend(_check_manning_n(tlf_summary))
    issues.extend(_check_soil_ilcl(tlf_summary))
    issues.extend(_check_solver_hardware(tlf_summary, hpc_summary))

    return issues


# ---------- CLI helpers for printing ----------

def _print_control_tree(tree: ControlTree) -> None:
    """Print control file tree using ASCII-only characters (for Windows cp1252)."""

    def recurse(node: Path, prefix: str = "") -> None:
        children = tree.edges.get(node, [])
        for idx, child in enumerate(children):
            is_last = idx == len(children) - 1
            connector = "+-- " if is_last else "|-- "
            print(f"{prefix}{connector}{child.name}")
            next_prefix = prefix + ("    " if is_last else "|   ")
            recurse(child, next_prefix)

    print(tree.root_tcf.name)
    recurse(tree.root_tcf)


def _print_input_scan(result: InputScanResult) -> None:
    print("\nInput files (GIS & Databases):")
    if not result.inputs:
        print("  (none found)")
        return

    for inp in sorted(result.inputs, key=lambda x: (x.kind, str(x.path))):
        status = "OK" if inp.exists else "MISSING"
        status_tag = "[OK]     " if inp.exists else "[MISSING]"
        print(
            f"  {status_tag} {inp.kind:9s} {inp.path} "
            f"(from {inp.from_control.name}, line {inp.line})"
        )


# ---------- Main entry point ----------

def main(argv: List[str]) -> None:
    """
    CLI entry point.

    Positional args:
      1) TCF path
      2+) wildcard args: -e1 00100Y -e2 0060m -s1 5m ...

    Options:
      --run-test         Run TUFLOW in test mode (-t) after static checks.
      --tuflow-exe PATH  Path to the TUFLOW executable (overrides default).
    """
    if not argv:
        print(
            "Usage:\n"
            "  python -m tuflow_qaqc.pre_run [options] path/to/model.tcf [wildcard args]\n\n"
            "Options:\n"
            "  --run-test           Run TUFLOW in test mode (-t) after static checks.\n"
            "  --tuflow-exe PATH    Path to TUFLOW executable (e.g. TUFLOW_iSP_w64.exe).\n\n"
            "Wildcard args example:\n"
            "  -e1 00100Y -e2 0060m -e3 tp01 -s1 5m -s2 CL0\n"
        )
        raise SystemExit(1)

    # Simple manual parsing for options:
    run_test = False
    tuflow_exe: Optional[Path] = None
    positional: List[str] = []

    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--run-test":
            run_test = True
            i += 1
        elif token == "--tuflow-exe" and i + 1 < len(argv):
            tuflow_exe = Path(argv[i + 1]).resolve()
            i += 2
        else:
            positional.append(token)
            i += 1

    if not positional:
        print("Error: No TCF path provided.\n")
        raise SystemExit(1)

    tcf_str = positional[0]
    tcf_path = Path(tcf_str).resolve()

    # Stage 0: find required wildcards from TCF filename
    filename_wildcards = find_wildcards_in_filename(tcf_path)
    # Build wildcard map from remaining positional args (wildcard args)
    wildcard_args = positional[1:]
    wildcard_map = build_wildcard_map_from_args(filename_wildcards, wildcard_args)

    # Stage 1: scan control files & inputs
    result = scan_all_inputs(tcf_path, wildcard_map)

    # Report control file tree
    print(f"TCF: {result.tcf_path}")
    print("\nControl file tree:")
    _print_control_tree(result.control_tree)

    # Report any control-file issues (missing/unreadable)
    if result.control_tree.issues:
        print("\nControl file issues:")
        for iss in result.control_tree.issues:
            print(
                f"  [{iss.severity.value}] {iss.id}: {iss.message} "
                f"(file: {iss.file})"
            )
    else:
        print("\nControl file issues: (none)")

    # Report inputs
    _print_input_scan(result)

    # Stage 2: optional TUFLOW run test (-t) and log parsing
    if run_test:
        exe_to_use = tuflow_exe or DEFAULT_TUFLOW_EXE
        if not exe_to_use.exists():
            print(
                f"\n[ERROR] TUFLOW executable not found: {exe_to_use}\n"
                "        Use --tuflow-exe to specify the correct path."
            )
            return

        print(f"\nRunning TUFLOW test (-t) using: {exe_to_use}")
        test_result = run_tuflow_test_and_analyse(
            tcf_path=tcf_path,
            wildcards=wildcard_map,
            control_tree=result.control_tree,
            tuflow_exe=exe_to_use,
        )

        print(f"\nTUFLOW test return code: {test_result.return_code}")
        print(f"Log folder: {test_result.logs.log_dir}")
        print(f"  .tlf:     {test_result.logs.tlf or 'NOT FOUND'}")
        print(f"  .hpc.tlf: {test_result.logs.hpc_tlf or 'NOT FOUND'}")
        print(f"  messages: {test_result.logs.messages_csv or 'NOT FOUND'}")

        print(
            f"\nMessages summary (from _messages.csv): "
            f"{test_result.error_count} errors, "
            f"{test_result.warning_count} warnings, "
            f"{test_result.check_count} checks"
        )

        # Detailed listing ONLY for ERROR messages
        if test_result.errors:
            print("\nError messages (from _messages.csv):")
            for line in test_result.errors[:50]:
                print(f"  {line}")
            if len(test_result.errors) > 50:
                print(f"  ... ({len(test_result.errors) - 50} more)")
        else:
            print("\nError messages (from _messages.csv): (none)")
        if test_result.message_number_counts:
            print("\nMessage number frequencies (from _messages.csv):")
            for msg_no, count in sorted(test_result.message_number_counts.items()):
                print(f"  {msg_no}: {count} occurrence(s)")
        else:
            print("\nMessage number frequencies: (none)")

        # Stage 3: QA checks based on .tlf / .hpc.tlf (5.x and 6.x)
        tlf_summary = parse_tlf_summary(test_result.logs.tlf)
        hpc_summary = parse_hpc_tlf_summary(test_result.logs.hpc_tlf)

        time_issues = run_time_and_timestep_checks(
            tcf_path=tcf_path,
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
            test_result=test_result,
        )

        param_issues = run_parameter_sanity_checks(
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
        )

        all_issues = time_issues + param_issues

        if all_issues:
            print("\nModel QA checks (5.x Time / 6.x Parameters):")
            for iss in all_issues:
                print(f"  [{iss.severity.value}] {iss.id} ({iss.category}): {iss.message}")
                if iss.suggestion:
                    print(f"      Suggestion: {iss.suggestion}")
        else:
            print("\nModel QA checks (5.x/6.x): no issues flagged.")


if __name__ == "__main__":
    main(sys.argv[1:])
