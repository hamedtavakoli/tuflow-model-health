from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple
import re
import sys


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


# ---------- CLI helpers for printing ----------

def _print_control_tree(tree: ControlTree) -> None:
    """Print control file tree like a directory structure."""

    def recurse(node: Path, prefix: str = "") -> None:
        children = tree.edges.get(node, [])
        for idx, child in enumerate(children):
            is_last = idx == len(children) - 1
            connector = "└── " if is_last else "├── "
            print(f"{prefix}{connector}{child.name}")
            next_prefix = prefix + ("    " if is_last else "│   ")
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
    if not argv:
        print(
            "Usage:\n"
            "  python -m tuflow_qaqc.pre_run path/to/model.tcf "
            "[wildcard args]\n\n"
            "Wildcard args example:\n"
            "  -e1 00100Y -e2 0060m -e3 tp01 -s1 5m -s2 CL0\n"
        )
        raise SystemExit(1)

    tcf_str = argv[0]
    tcf_path = Path(tcf_str).resolve()

    # Stage 0: find required wildcards from TCF filename
    filename_wildcards = find_wildcards_in_filename(tcf_path)
    # Build wildcard map from CLI args + prompt for any missing
    wildcard_map = build_wildcard_map_from_args(filename_wildcards, argv[1:])

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


if __name__ == "__main__":
    main(sys.argv[1:])
