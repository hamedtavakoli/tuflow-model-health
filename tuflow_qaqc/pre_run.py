from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Iterable
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
class ControlNode:
    """A node in the control file tree for Stage 0 discovery."""

    path: Path
    children: List["ControlNode"] = field(default_factory=list)
    missing: bool = False


@dataclass
class DiscoveryResult:
    """Stage 0: resolved TCF and tree of referenced control files."""

    tcf_path: Path
    control_tree: ControlNode
    missing_control_files: List[Path] = field(default_factory=list)


@dataclass
class PreRunSettings:
    """Settings for potential pre-run checks (reserved for future use)."""

    tuflow_exe: Optional[Path] = None


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
    """Placeholder for legacy callers; not used in the new flow."""

    tcf: ControlFile
    control_files: Dict[Path, ControlFile] = field(default_factory=dict)
    referenced_files: Dict[str, Set[Path]] = field(default_factory=dict)


@dataclass
class InputReference:
    """An external input referenced by a control file."""

    path: Path
    category: str  # e.g. GIS or Database
    status: str    # OK or MISSING
    source_file: Path
    line: int
    keyword: str


@dataclass
class InputScanResult:
    """Stage 1 results summarising GIS/database inputs."""

    tcf_path: Path
    inputs: List[InputReference]


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

WILDCARD_RE = re.compile(r"~(?P<var>[A-Za-z0-9_]+)~")

INLINE_COMMENT_SPLIT_RE = re.compile(r"(!|//|#)")


def _strip_inline_comment(line: str) -> str:
    """
    Remove inline comments starting with ! or // or #.
    Example:
      'Event File == Event_File.tef  ! Reference' -> 'Event File == Event_File.tef'
    """

    parts = INLINE_COMMENT_SPLIT_RE.split(line, maxsplit=1)
    return parts[0]


def parse_control_file(path: Path) -> ControlFile:
    """Parse a TUFLOW control file (TCF/TGC/ECF/etc.) into directives."""

    directives: List[ControlDirective] = []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        raise
    except Exception as e:  # pragma: no cover - defensive
        raise RuntimeError(f"Failed to read control file {path}: {e}") from e

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = _strip_inline_comment(line)
        if not stripped.strip():
            continue
        if COMMENT_RE.match(stripped):
            continue

        m = DIRECTIVE_RE.match(stripped)
        if not m:
            # Not a standard directive; keep raw if needed later
            continue

        key = m.group("key").strip()
        value = m.group("value").strip()
        directives.append(ControlDirective(keyword=key, value=value, line=i, raw=line))

    return ControlFile(path=path, directives=directives)


# ---------- Stage 0: wildcard resolution + control file tree ----------

# Keywords that indicate other control files (case-insensitive)
CONTROL_FILE_KEYWORDS = {
    "geometry control",
    "geometry control file",
    "bc control",
    "bc control file",
    "estry control",
    "1d control",
    "2d control",
    "quadtree control",
    "rainfall control",
    "rainfall control file",
    "operations control",
    "event file",
    "read file",
    "read control file",
    "soils file",
}

# Heuristics to categorise external inputs
GIS_INPUT_HINTS = (
    "read gis",
    "read mi",
    "read grid",
    "z shape",
    "z line",
    "z pts",
    "mat",
    "code",
    "grid",
    "dem",
    "raster",
)

DATABASE_INPUT_HINTS = (
    "database",
    "dbase",
    "table",
    "materials",
    "bc table",
    "bc database",
    "rainfall database",
    "hydrograph",
)


def _extract_candidate_paths(value: str) -> List[str]:
    """Pull simple path-like tokens from a directive value."""

    tokens = re.split(r"[\s,;]+", value.strip('"'))
    paths: List[str] = []
    for token in tokens:
        if "." in token and not re.fullmatch(r"[+-]?\d+(\.\d+)?", token):
            paths.append(token.strip('"'))
    return paths


def _keyword_in_set(keyword: str, options: Iterable[str]) -> bool:
    key_norm = keyword.strip().lower()
    return any(key_norm == opt for opt in options)


def detect_wildcards_in_name(name: str) -> Set[str]:
    """Return wildcard tokens (e.g. e1, s2) found in a filename."""

    return {m.group("var").lower() for m in WILDCARD_RE.finditer(name)}


def resolve_tcf_template(tcf_template: Path, wildcard_values: Dict[str, str]) -> Path:
    """
    Resolve a TCF template filename by substituting ~eN~/~sN~ wildcards.

    The resolved name may not exist on disk; callers should decide whether to enforce
    presence. This keeps the template path usable without requiring a specific
    resolved file name.
    """

    tcf_template = tcf_template.resolve()
    required = detect_wildcards_in_name(tcf_template.name)
    missing = {w for w in required if w not in {k.lower() for k in wildcard_values}}
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing values for wildcards: {missing_list}")

    resolved_name = tcf_template.name
    for key, val in wildcard_values.items():
        resolved_name = resolved_name.replace(f"~{key}~", val)
        resolved_name = resolved_name.replace(f"~{key.lower()}~", val)
        resolved_name = resolved_name.replace(f"~{key.upper()}~", val)

    return tcf_template.with_name(resolved_name)


def _find_control_children(cf: ControlFile) -> List[Path]:
    """Return referenced control files from a parsed control file."""

    base_dir = cf.path.parent
    children: List[Path] = []
    for d in cf.directives:
        if _keyword_in_set(d.keyword, CONTROL_FILE_KEYWORDS):
            for token in _extract_candidate_paths(d.value):
                children.append((base_dir / token).resolve())
    return children


def _build_control_node(
    path: Path,
    missing: list[Path],
    cache: Dict[Path, ControlNode],
) -> ControlNode:
    """Recursively build the control file tree starting from ``path``."""

    norm = path.resolve()
    if norm in cache:
        return cache[norm]

    if not norm.exists():
        node = ControlNode(path=norm, missing=True)
        cache[norm] = node
        missing.append(norm)
        return node

    try:
        cf = parse_control_file(norm)
    except Exception:
        node = ControlNode(path=norm, missing=True)
        cache[norm] = node
        missing.append(norm)
        return node

    node = ControlNode(path=norm)
    cache[norm] = node
    for child_path in _find_control_children(cf):
        node.children.append(_build_control_node(child_path, missing, cache))
    return node


def build_discovery(tcf_path: Path) -> DiscoveryResult:
    """Stage 0: resolve control file includes into a tree structure."""

    missing: list[Path] = []
    cache: Dict[Path, ControlNode] = {}
    root = _build_control_node(tcf_path, missing=missing, cache=cache)
    return DiscoveryResult(tcf_path=tcf_path, control_tree=root, missing_control_files=missing)


# ---------- Stage 1: external input listing ----------


def _categorise_input(keyword: str) -> Optional[str]:
    k = keyword.lower()
    if any(h in k for h in GIS_INPUT_HINTS):
        return "GIS"
    if any(h in k for h in DATABASE_INPUT_HINTS):
        return "Database"
    return None


def _scan_inputs_in_control_file(cf: ControlFile) -> List[InputReference]:
    """Extract GIS/database input references from a control file."""

    refs: List[InputReference] = []
    base_dir = cf.path.parent
    for d in cf.directives:
        if _keyword_in_set(d.keyword, CONTROL_FILE_KEYWORDS):
            continue

        category = _categorise_input(d.keyword)
        if category is None:
            continue

        for token in _extract_candidate_paths(d.value):
            p = (base_dir / token).resolve()
            status = "OK" if p.exists() else "MISSING"
            refs.append(
                InputReference(
                    path=p,
                    category=category,
                    status=status,
                    source_file=cf.path,
                    line=d.line,
                    keyword=d.keyword,
                )
            )

    return refs


def _iter_control_nodes(node: ControlNode) -> Iterable[ControlNode]:
    yield node
    for child in node.children:
        yield from _iter_control_nodes(child)


def scan_inputs(control_tree: ControlNode) -> InputScanResult:
    """Stage 1: list GIS/database inputs from all control files in the tree."""

    inputs: List[InputReference] = []
    parsed_cache: Dict[Path, ControlFile] = {}
    for node in _iter_control_nodes(control_tree):
        if node.missing:
            continue
        if node.path in parsed_cache:
            cf = parsed_cache[node.path]
        else:
            try:
                cf = parse_control_file(node.path)
            except Exception:
                continue
            parsed_cache[node.path] = cf
        inputs.extend(_scan_inputs_in_control_file(cf))

    return InputScanResult(tcf_path=control_tree.path, inputs=inputs)


def pretty_print_control_tree(node: ControlNode, prefix: str = "") -> None:
    """Print a simple text tree of control file references."""

    marker = "[MISSING] " if node.missing else ""
    print(f"{prefix}{marker}{node.path.name}")
    for i, child in enumerate(node.children):
        is_last = i == len(node.children) - 1
        new_prefix = prefix + ("    " if is_last else "│   ")
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}", end="")
        pretty_print_control_tree(child, prefix=new_prefix)


def _parse_wildcard_args(args: List[str]) -> Dict[str, str]:
    """
    Parse wildcard assignments from leftover CLI args (e.g. ``--e1 001`` or
    ``--e1=001``).

    Accepts both space-separated pairs and inline ``=`` forms so Windows users can
    avoid multi-line quoting issues.
    """

    values: Dict[str, str] = {}
    i = 0
    while i < len(args):
        key = args[i]

        if key.startswith("-") and "=" in key:
            name, value = key.split("=", 1)
            name = name.lstrip("-")
            i += 1
        else:
            if not key.startswith("-"):
                raise ValueError(f"Unexpected argument: {key}")
            name = key.lstrip("-")
            if i + 1 >= len(args):
                raise ValueError(f"Missing value for wildcard {key}")
            value = args[i + 1]
            i += 2

        if not re.fullmatch(r"[es]\d+", name, flags=re.IGNORECASE):
            raise ValueError(f"Wildcard arguments must look like --e1/--s1, got {key}")

        values[name] = value

    return values


def _print_input_summary(inputs: List[InputReference]) -> None:
    if not inputs:
        print("No external inputs found in control files.")
        return

    by_category: Dict[str, List[InputReference]] = {}
    for ref in inputs:
        by_category.setdefault(ref.category, []).append(ref)

    for category, refs in by_category.items():
        print(f"\n{category} Inputs:")
        seen: Set[Path] = set()
        for ref in refs:
            if ref.path in seen:
                continue
            seen.add(ref.path)
            status = "[OK]" if ref.status == "OK" else "[MISSING]"
            print(f"  {status} {ref.path} (from {ref.source_file.name} line {ref.line})")


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point implementing wildcard-driven Stage 0 + Stage 1."""

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Resolve TUFLOW TCF templates, build control file trees, and list GIS/"
            "database inputs."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "tcf_template",
        help="Path to the TCF template filename (may contain ~eN~/~sN~ wildcards)",
    )
    args, unknown = parser.parse_known_args(argv)

    try:
        wildcard_values = _parse_wildcard_args(unknown)
    except ValueError as exc:  # pragma: no cover - CLI guard
        parser.error(str(exc))

    tcf_template = Path(args.tcf_template)

    try:
        resolved_tcf = resolve_tcf_template(tcf_template, wildcard_values)
    except ValueError as exc:  # pragma: no cover - CLI guard
        parser.error(str(exc))

    print(f"TCF (template name retained): {resolved_tcf}")

    discovery = build_discovery(resolved_tcf)
    print("\nControl file tree:")
    pretty_print_control_tree(discovery.control_tree)

    if discovery.missing_control_files:
        print("\nMissing control files:")
        for m in discovery.missing_control_files:
            print(f"  {m}")

    scan_result = scan_inputs(discovery.control_tree)
    print("\nExternal inputs (Stage 1):")
    _print_input_summary(scan_result.inputs)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
