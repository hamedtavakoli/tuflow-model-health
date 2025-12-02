from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Set
import re


# ---------- Core types ----------

class Severity(str, Enum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"


@dataclass
class Issue:
    id: str                     # e.g. "PR001_TCF_MISSING"
    severity: Severity
    category: str               # e.g. "Structure", "ControlFiles", "Paths"
    message: str                # human-readable description
    suggestion: str             # recommended fix
    file: Optional[Path] = None # file this relates to (if any)
    line: Optional[int] = None  # line number in file (if applicable)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreRunSettings:
    """Settings for pre-run checks."""
    tuflow_exe: Optional[Path] = None  # for later test-run integration

    # Expected subfolders under the TCF folder (you can expand this later)
    check_expected_folders: bool = True
    expected_folders: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "Structure": ["log", "check", "results"],
        }
    )


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
class ModelConfig:
    """Minimal model configuration gleaned from TCF/TGC/ECF for pre-run checks."""
    tcf: ControlFile
    control_files: Dict[Path, ControlFile] = field(default_factory=dict)
    # Paths referenced in control files, grouped loosely by type
    referenced_files: Dict[str, Set[Path]] = field(
        default_factory=lambda: {
            "control": set(),   # .tgc, .ecf, etc.
            "gis": set(),       # GIS layers
            "bc": set(),        # boundary condition time-series
            "tables": set(),    # tables, lookup CSVs
            "other": set(),
        }
    )


# ---------- Parsing utilities ----------

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


def parse_control_file(path: Path) -> ControlFile:
    """Parse a TUFLOW control file (TCF/TGC/ECF) into directives."""
    directives: List[ControlDirective] = []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to read control file {path}: {e}") from e

    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if COMMENT_RE.match(line):
            continue

        m = DIRECTIVE_RE.match(line)
        if not m:
            # Not a standard directive; keep raw if you want later
            continue

        key = m.group("key").strip()
        value = m.group("value").strip()
        directives.append(
            ControlDirective(keyword=key, value=value, line=i, raw=line)
        )

    return ControlFile(path=path, directives=directives)


# Keywords that indicate other control files
CONTROL_KEYWORDS = {
    "Geometry Control",
    "BC Control",
    "GIS Control",
    "Parameter Control",
    "Output Control",
    "1D Control",
    "2D Control",
    "Event Control",
    "Read File",
    "Read Control File",
}

# Heuristics to categorise paths
GIS_HINTS = ("2d_", "1d_", "Read GIS", "Read MI", "Read GRID")
BC_HINTS = ("BC Database", "bc_dbase", "bcdb", "Rainfall", "Inflow", "Hydrograph")
TABLE_HINTS = ("Read Table", "Read Materials", "Manning Table")


def _extract_candidate_paths(value: str) -> List[str]:
    """
    Very simple heuristic to pull path-like tokens from a directive value.
    We just look for tokens with a '.' that don't look like numbers.
    """
    tokens = re.split(r"[\s,;]+", value.strip('"'))
    paths: List[str] = []
    for token in tokens:
        if "." in token and not re.fullmatch(r"[+-]?\d+(\.\d+)?", token):
            paths.append(token.strip('"'))
    return paths


def _categorise_path(keyword: str, path: Path) -> str:
    k = keyword.lower()
    if any(h.lower() in k for h in GIS_HINTS):
        return "gis"
    if any(h.lower() in k for h in BC_HINTS):
        return "bc"
    if any(h.lower() in k for h in TABLE_HINTS):
        return "tables"
    if "control" in k:
        return "control"
    return "other"


def _collect_control_files_and_paths(
    cf: ControlFile,
    model: ModelConfig,
    visited: Set[Path],
) -> None:
    """Recursive collection of control files and referenced paths."""
    if cf.path in visited:
        return
    visited.add(cf.path)
    model.control_files[cf.path] = cf

    base_dir = cf.path.parent

    for d in cf.directives:
        # 1) Control files
        if d.keyword.strip() in CONTROL_KEYWORDS:
            for token in _extract_candidate_paths(d.value):
                child_path = (base_dir / token).resolve()
                model.referenced_files["control"].add(child_path)
                if child_path.suffix.lower() in {".tcf", ".tgc", ".ecf"}:
                    if child_path not in model.control_files:
                        try:
                            child_cf = parse_control_file(child_path)
                        except FileNotFoundError:
                            # Missing control file; handled in static checks
                            continue
                        _collect_control_files_and_paths(
                            child_cf, model=model, visited=visited
                        )
            continue

        # 2) Other file references (GIS, BC, tables, etc.)
        for token in _extract_candidate_paths(d.value):
            p = (base_dir / token).resolve()
            category = _categorise_path(d.keyword, p)
            model.referenced_files.setdefault(category, set()).add(p)


def build_model_config(tcf_path: Path) -> ModelConfig:
    """Build ModelConfig from the main TCF and referenced control files."""
    tcf_path = tcf_path.resolve()
    tcf_cf = parse_control_file(tcf_path)
    model = ModelConfig(tcf=tcf_cf)

    visited: Set[Path] = set()
    _collect_control_files_and_paths(cf=tcf_cf, model=model, visited=visited)

    return model

# ---------- Helper utilities for checks ----------

def find_directives(cf: ControlFile, key: str) -> list[ControlDirective]:
    """Find all directives in a control file with a given keyword (case-insensitive)."""
    key_norm = key.strip().lower()
    return [
        d for d in cf.directives
        if d.keyword.strip().lower() == key_norm
    ]


def _parse_float(value: str) -> Optional[float]:
    """Try to parse a float from a directive value; return None if it fails."""
    # Take first token that looks like a number
    token = value.strip().split()[0]
    try:
        return float(token)
    except ValueError:
        return None


# ---------- Static checks ----------

@dataclass
class PreRunResult:
    tcf_path: Path
    issues: List[Issue]
    static_checks_ok: bool


def check_tcf_exists(tcf_path: Path) -> List[Issue]:
    issues: List[Issue] = []
    if not tcf_path.exists():
        issues.append(
            Issue(
                id="PR001_TCF_MISSING",
                severity=Severity.CRITICAL,
                category="Structure",
                message=f"TCF file not found: {tcf_path}",
                suggestion="Verify the selected TCF path. Ensure the model folder is accessible.",
                file=tcf_path,
            )
        )
    return issues


def check_expected_folders(tcf_path: Path, settings: PreRunSettings) -> List[Issue]:
    issues: List[Issue] = []
    if not settings.check_expected_folders:
        return issues

    root = tcf_path.parent
    for category, rel_names in settings.expected_folders.items():
        for rel in rel_names:
            folder = root / rel
            if not folder.exists():
                issues.append(
                    Issue(
                        id=f"PR010_FOLDER_MISSING_{rel.lower()}",
                        severity=Severity.MAJOR,
                        category="Structure",
                        message=f"Expected folder '{rel}' not found in model directory.",
                        suggestion=(
                            f"Create the '{rel}' folder under {root} "
                            f"to keep logs/check/results organised and consistent."
                        ),
                        file=folder,
                    )
                )
    return issues


def check_control_files_exist(model: ModelConfig) -> List[Issue]:
    issues: List[Issue] = []

    for p in model.referenced_files.get("control", set()):
        if not p.exists():
            issues.append(
                Issue(
                    id="PR020_CONTROL_FILE_MISSING",
                    severity=Severity.CRITICAL,
                    category="ControlFiles",
                    message=f"Referenced control file not found: {p}",
                    suggestion="Check 'Geometry Control', 'BC Control' and any 'Read File' "
                               "directives in the TCF/TGC to ensure paths are correct.",
                    file=p,
                )
            )
    return issues


def check_referenced_files_exist(model: ModelConfig) -> List[Issue]:
    issues: List[Issue] = []
    for category, paths in model.referenced_files.items():
        if category == "control":
            continue  # handled separately

        for p in paths:
            if not p.exists():
                sev = Severity.CRITICAL if category in {"gis", "bc"} else Severity.MAJOR
                issues.append(
                    Issue(
                        id="PR030_REFERENCED_FILE_MISSING",
                        severity=sev,
                        category=f"Paths_{category}",
                        message=f"Referenced {category} file not found: {p}",
                        suggestion=(
                            f"Update the path in the control files or ensure the {category} file "
                            f"is placed at the expected location."
                        ),
                        file=p,
                        details={"ref_type": category},
                    )
                )
    return issues

def check_time_settings(model: ModelConfig) -> List[Issue]:
    """
    Check that Start Time, End Time and Time Step are present and sensible.
    This is a light sanity check, not a full physical consistency check.
    """
    issues: List[Issue] = []

    tcf = model.tcf

    # 1) Fetch directives from main TCF (not from included controls)
    start_dirs = find_directives(tcf, "Start Time")
    end_dirs = find_directives(tcf, "End Time")
    dt_dirs = find_directives(tcf, "Time Step")

    # 2) Presence checks
    if not start_dirs:
        issues.append(
            Issue(
                id="PR040_START_TIME_MISSING",
                severity=Severity.CRITICAL,
                category="Time",
                message="Start Time directive is missing from the TCF.",
                suggestion="Add a 'Start Time' directive to the TCF (e.g. 'Start Time == 0').",
                file=tcf.path,
            )
        )
    if not end_dirs:
        issues.append(
            Issue(
                id="PR041_END_TIME_MISSING",
                severity=Severity.CRITICAL,
                category="Time",
                message="End Time directive is missing from the TCF.",
                suggestion="Add an 'End Time' directive to the TCF (e.g. 'End Time == 72').",
                file=tcf.path,
            )
        )
    if not dt_dirs:
        issues.append(
            Issue(
                id="PR042_TIME_STEP_MISSING",
                severity=Severity.CRITICAL,
                category="Time",
                message="Time Step directive is missing from the TCF.",
                suggestion="Add a 'Time Step' directive to the TCF (e.g. 'Time Step == 1').",
                file=tcf.path,
            )
        )

    # If any are totally missing, don't try to parse values
    if not start_dirs or not end_dirs or not dt_dirs:
        return issues

    # 3) Value checks (use the FIRST occurrence for now)
    start_val = _parse_float(start_dirs[0].value)
    end_val = _parse_float(end_dirs[0].value)
    dt_val = _parse_float(dt_dirs[0].value)

    # If parsing fails, treat as Major issues
    if start_val is None:
        issues.append(
            Issue(
                id="PR043_START_TIME_NOT_NUMERIC",
                severity=Severity.MAJOR,
                category="Time",
                message=f"Could not parse Start Time as a number: '{start_dirs[0].value}'.",
                suggestion="Ensure Start Time is specified as a numeric value (e.g. 'Start Time == 0').",
                file=tcf.path,
                line=start_dirs[0].line,
            )
        )
    if end_val is None:
        issues.append(
            Issue(
                id="PR044_END_TIME_NOT_NUMERIC",
                severity=Severity.MAJOR,
                category="Time",
                message=f"Could not parse End Time as a number: '{end_dirs[0].value}'.",
                suggestion="Ensure End Time is specified as a numeric value (e.g. 'End Time == 72').",
                file=tcf.path,
                line=end_dirs[0].line,
            )
        )
    if dt_val is None:
        issues.append(
            Issue(
                id="PR045_TIME_STEP_NOT_NUMERIC",
                severity=Severity.MAJOR,
                category="Time",
                message=f"Could not parse Time Step as a number: '{dt_dirs[0].value}'.",
                suggestion="Ensure Time Step is specified as a numeric value (e.g. 'Time Step == 1').",
                file=tcf.path,
                line=dt_dirs[0].line,
            )
        )

    # If any of them are non-numeric, no more numeric checks
    if start_val is None or end_val is None or dt_val is None:
        return issues

    # 4) Basic numeric sanity
    if dt_val <= 0:
        issues.append(
            Issue(
                id="PR046_TIME_STEP_NONPOSITIVE",
                severity=Severity.CRITICAL,
                category="Time",
                message=f"Time Step is non-positive: {dt_val}.",
                suggestion="Use a positive Time Step (e.g. 0.5, 1.0).",
                file=tcf.path,
                line=dt_dirs[0].line,
            )
        )

    if end_val <= start_val:
        issues.append(
            Issue(
                id="PR047_END_NOT_AFTER_START",
                severity=Severity.MAJOR,
                category="Time",
                message=f"End Time ({end_val}) is not greater than Start Time ({start_val}).",
                suggestion="Ensure End Time is greater than Start Time to define a valid simulation duration.",
                file=tcf.path,
                line=end_dirs[0].line,
            )
        )

    # Optional: rough "too long" check (configurable later). For now, just warn if > 500 hrs.
    duration = end_val - start_val
    if duration > 500:
        issues.append(
            Issue(
                id="PR048_LONG_SIM_DURATION",
                severity=Severity.MINOR,
                category="Time",
                message=f"Simulation duration is very long ({duration} time units).",
                suggestion="Confirm that this long duration is intentional. "
                           "If using hours, consider whether a shorter simulation window would suffice.",
                file=tcf.path,
                line=end_dirs[0].line,
                details={"duration": duration},
            )
        )

    return issues


def run_pre_run_checks(
    tcf: str | Path,
    settings: Optional[PreRunSettings] = None,
) -> PreRunResult:
    """Run Stage 1 static pre-run checks (no TUFLOW execution)."""
    if settings is None:
        settings = PreRunSettings()

    tcf_path = Path(tcf).resolve()
    all_issues: List[Issue] = []

    # 1) TCF exists
    all_issues.extend(check_tcf_exists(tcf_path))
    if any(i.severity == Severity.CRITICAL for i in all_issues):
        return PreRunResult(tcf_path=tcf_path, issues=all_issues, static_checks_ok=False)

    # 2) Folder structure
    all_issues.extend(check_expected_folders(tcf_path, settings))

    # 3) Build model config (parse TCF + referenced control files, collect paths)
    try:
        model = build_model_config(tcf_path)
    except Exception as e:
        all_issues.append(
            Issue(
                id="PR099_PARSE_ERROR",
                severity=Severity.CRITICAL,
                category="Parsing",
                message=f"Error while parsing control files: {e}",
                suggestion="Inspect the TCF and included control files for syntax issues "
                           "or unusual encoding.",
                file=tcf_path,
            )
        )
        return PreRunResult(tcf_path=tcf_path, issues=all_issues, static_checks_ok=False)

     # 4) Control file existence checks
    all_issues.extend(check_control_files_exist(model))

    # 5) Referenced paths (GIS / BC / tables)
    all_issues.extend(check_referenced_files_exist(model))

    # 6) Time control sanity (Start/End/Time Step)
    all_issues.extend(check_time_settings(model))

    static_ok = not any(i.severity == Severity.CRITICAL for i in all_issues)
    return PreRunResult(tcf_path=tcf_path, issues=all_issues, static_checks_ok=static_ok)


# ---------- Simple CLI for quick testing ----------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m tuflow_qaqc.pre_run path/to/model.tcf")
        raise SystemExit(1)

    tcf_arg = sys.argv[1]
    result = run_pre_run_checks(tcf_arg)

    print(f"TCF: {result.tcf_path}")
    print(f"Static checks OK: {result.static_checks_ok}")
    print("Issues:")
    for i in result.issues:
        print(
            f"- [{i.severity.value}] {i.id} / {i.category}\n"
            f"  {i.message}\n"
            f"  Suggestion: {i.suggestion}\n"
        )
