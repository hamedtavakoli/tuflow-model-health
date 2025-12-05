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


def _print_input_scan(result: InputScanResult) -> None:
    """Print input files found during scan."""
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


def print_usage() -> None:
    """Print usage information."""
    print(
        "Usage:\n"
        "  python -m tuflow_qaqc.pre_run [options] path/to/model.tcf [wildcard args]\n\n"
        "Options:\n"
        "  --run-test           Run TUFLOW in test mode (-t) after static checks.\n"
        "  --tuflow-exe PATH    Path to TUFLOW executable (e.g. TUFLOW_iSP_w64.exe).\n\n"
        "Wildcard args example:\n"
        "  -e1 00100Y -e2 0060m -e3 tp01 -s1 5m -s2 CL0\n"
    )
