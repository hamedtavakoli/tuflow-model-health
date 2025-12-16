"""
CLI interface and output formatting for TUFLOW QA/QC validator.
"""

from typing import List

from .core import InputScanResult, ModelNode, TuflowTestResult, Issue


def _format_node_label(node: ModelNode) -> str:
    """Readable label for a model node with existence hints."""

    label = node.name
    if node.path:
        label = f"{label} ({node.path})"
        if not node.exists:
            label += " [MISSING]"
    return label


def _print_model_tree(node: ModelNode) -> None:
    """Print the unified model tree using ASCII-only characters."""

    def recurse(n: ModelNode, prefix: str = "") -> None:
        for idx, child in enumerate(n.children):
            is_last = idx == len(n.children) - 1
            connector = "+-- " if is_last else "|-- "
            print(f"{prefix}{connector}{_format_node_label(child)}")
            next_prefix = prefix + ("    " if is_last else "|   ")
            recurse(child, next_prefix)

    print(node.name)
    recurse(node)


def print_validation_report(
    result: InputScanResult,
    test_result: TuflowTestResult = None,
    qa_issues: List[Issue] = None,
) -> None:
    """Print a complete validation report."""
    # Report unified model structure
    print(f"TCF: {result.tcf_path}")
    print("\nModel structure:")
    if result.model_tree:
        _print_model_tree(result.model_tree)
    else:
        print("  (no model tree built)")

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



