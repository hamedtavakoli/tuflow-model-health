"""
Parsing utilities for TUFLOW control files and log files.
"""

from pathlib import Path
from typing import List, Dict, Optional, Tuple
import csv

from .config import (
    COMMENT_RE, DIRECTIVE_RE, INLINE_COMMENT_SPLIT_RE, WILDCARD_RE,
    FLOAT_RE, CONTROL_EXTS, GIS_EXTS, DB_EXTS, CONTROL_KEY_HINTS,
    INPUT_KEY_HINTS, SOIL_EXTS
)
from .core import (
    ControlDirective, ControlFile, ControlTree, InputRef, InputScanResult,
    TuflowTlfSummary, TuflowHpcSummary, TuflowMaterial, TuflowSoil, Issue, Severity
)


# ---- Control file parsing ----

def _strip_inline_comment(line: str) -> str:
    """Remove inline comments starting with ! or // or #."""
    parts = INLINE_COMMENT_SPLIT_RE.split(line, maxsplit=1)
    return parts[0]


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


# ---- Wildcard utilities ----

def find_wildcards_in_filename(path: Path) -> List[str]:
    """Return wildcard names (without tildes) from a filename."""
    return [m.group("var") for m in WILDCARD_RE.finditer(path.name)]


def substitute_wildcards(value: str, wildcards: Dict[str, str]) -> str:
    """Replace ~var~ tokens in a string with provided wildcard values (if available)."""
    def repl(m):
        var = m.group("var")
        return wildcards.get(var, m.group(0))  # leave as-is if not provided

    return WILDCARD_RE.sub(repl, value)


def build_wildcard_map_from_args(
    filename_wildcards: List[str],
    argv: List[str],
) -> Dict[str, str]:
    """
    Build a wildcard->value map from CLI args.
    Supports args like: -e1 00100Y -e2 0060m -s1 5m -s2 CL0

    The function no longer prompts; it simply returns the values supplied by
    the user so that callers can perform validation/handling as needed.
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

    return supplied


# ---- Control file tree building ----

def is_control_file_path(p: Path) -> bool:
    """Check if a path looks like a TUFLOW control file."""
    return p.suffix.lower() in CONTROL_EXTS


def _collect_control_children(
    cf: ControlFile,
    wildcards: Dict[str, str],
) -> List[Path]:
    """
    From a parsed control file, find all referenced control files,
    substituting wildcards in the values.
    """
    import re
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
    all_files: set[Path] = set()
    issues: List[Issue] = []
    visited: set[Path] = set()

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


# ---- Input scanning ----

def _categorise_input_path(p: Path, keyword: str) -> str:
    """Roughly categorise an input file as gis/database/soil/other."""
    ext = p.suffix.lower()
    if ext in SOIL_EXTS:
        return "soil"
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
    *,
    debug: bool = False,
    debug_log: List[str],
) -> List[InputRef]:
    """Scan a single control file for input file references (GIS, CSV, soils, etc.)."""
    import re
    inputs: List[InputRef] = []

    def _log(msg: str) -> None:
        if debug:
            debug_log.append(msg)

    if not path.exists():
        _log(f"{path}: skipped (file missing)")
        return inputs

    base_dir = path.parent
    text = path.read_text(encoding="utf-8", errors="ignore")
    _log(f"Scanning {path}")

    for i, raw_line in enumerate(text.splitlines(), start=1):
        no_comment = _strip_inline_comment(raw_line)
        line = no_comment.strip()
        if not line or COMMENT_RE.match(line):
            if debug:
                reason = "empty" if not line else "comment"
                _log(f"{path}:{i}: skipped ({reason}) -> {raw_line}")
            continue

        m = DIRECTIVE_RE.match(line)
        if not m:
            _log(f"{path}:{i}: no directive match -> {raw_line}")
            continue

        key = m.group("key").strip()
        val_raw = m.group("value").strip()
        key_lower = key.lower()

        # Substitute wildcards in the value
        val = substitute_wildcards(val_raw, wildcards)

        is_known_input_key = any(h.lower() in key_lower for h in INPUT_KEY_HINTS)
        tokens = re.split(r"[\s,;]+", val.strip('"').strip("'"))
        _log(f"{path}:{i}: directive '{key}' -> tokens {tokens}")

        for tok in tokens:
            cleaned = tok.strip().strip('"').strip("'")
            if not cleaned:
                _log(f"{path}:{i}: empty token skipped")
                continue

            # Only treat tokens with a dot as file-like
            if "." not in cleaned:
                if is_known_input_key:
                    _log(f"{path}:{i}: token '{cleaned}' skipped (no dot) despite keyword match")
                continue

            normalised = cleaned.replace("\\", "/")
            p = (base_dir / normalised).resolve()
            kind = _categorise_input_path(p, key)
            ext = p.suffix.lower()

            keep = (
                kind in {"gis", "database", "soil"}
                or is_known_input_key
                or ext in SOIL_EXTS
            )

            if not keep:
                _log(f"{path}:{i}: token '{cleaned}' skipped (unrecognised kind '{kind}')")
                continue

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
            _log(
                f"{path}:{i}: matched '{key}' -> {p} (exists={exists}, kind={kind})"
            )

    return inputs


def scan_all_inputs(
    tcf_path: Path,
    wildcards: Dict[str, str],
    *,
    debug: bool = False,
) -> InputScanResult:
    """
    Stage 1: given a TCF and wildcard values, build the control tree,
    then scan all control files for GIS and database inputs.
    """
    control_tree = build_control_tree(tcf_path, wildcards)
    debug_log: List[str] = []
    seen_paths: set[tuple[Path, str]] = set()
    all_inputs: List[InputRef] = []

    for cf_path in control_tree.all_files:
        inputs = _scan_inputs_in_control_file(
            cf_path,
            wildcards,
            debug=debug,
            debug_log=debug_log,
        )
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
        debug_log=debug_log,
    )


# ---- Log file utilities ----

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
    control_files: set[Path],
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


# ---- TLF / HPC.TLF parsing ----

def _extract_first_float(text: str) -> Optional[float]:
    """Extract first float-like value from text."""
    m = FLOAT_RE.search(text)
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
