"""
CLI interface and output formatting for TUFLOW QA/QC validator.
"""

from pathlib import Path
from typing import List

from .core import ControlTree, InputScanResult, TuflowTestResult, Issue


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


def _print_input_group(title: str, items: list[tuple[str, str]]) -> None:
    print(f"  {title}:")
    if not items:
        print("    (none)")
        return
    for status_tag, line in items:
        print(f"    {status_tag} {line}")


def _print_input_scan(result: InputScanResult) -> None:
    """Print input files found during scan, grouped by type."""
    print("\nInput files:")

    control_items: list[tuple[str, str]] = []
    for path in sorted(result.control_tree.all_files):
        exists = path.exists()
        status_tag = "[OK]     " if exists else "[MISSING]"
        control_items.append((status_tag, f"control   {path}"))

    gis_items: list[tuple[str, str]] = []
    db_items: list[tuple[str, str]] = []
    other_items: list[tuple[str, str]] = []

    for inp in sorted(result.inputs, key=lambda x: (x.kind, str(x.path))):
        status_tag = "[OK]     " if inp.exists else "[MISSING]"
        line = (
            f"{inp.kind:9s} {inp.path} "
            f"(from {inp.from_control.name}, line {inp.line})"
        )
        if inp.kind == "gis":
            gis_items.append((status_tag, line))
        elif inp.kind == "database":
            db_items.append((status_tag, line))
        else:
            other_items.append((status_tag, line))

    _print_input_group("Control files", control_items)
    _print_input_group("GIS layers", gis_items)
    _print_input_group("Databases", db_items)
    _print_input_group("Other inputs", other_items)


def print_validation_report(
    result: InputScanResult,
    test_result: TuflowTestResult = None,
    qa_issues: List[Issue] = None,
) -> None:
    """Print a complete validation report."""
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

    # Report TUFLOW test results if available
    if test_result:
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

    # Report QA check issues if available
    if qa_issues:
        print("\nModel QA checks (5.x Time / 6.x Parameters):")
        for iss in qa_issues:
            print(f"  [{iss.severity.value}] {iss.id} ({iss.category}): {iss.message}")
            if iss.suggestion:
                print(f"      Suggestion: {iss.suggestion}")
    elif test_result is not None:
        print("\nModel QA checks (5.x/6.x): no issues flagged.")



