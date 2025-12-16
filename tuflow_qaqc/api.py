"""Public API for running the TUFLOW QA/QC pipeline programmatically.

This exposes the same staged workflow used by the CLI entry point so it can
be reused by external callers (e.g. a QGIS plugin) without rewriting the
engine logic.
"""

from __future__ import annotations

import html
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .checks import run_parameter_sanity_checks, run_time_and_timestep_checks
from .cli import print_validation_report
from .config import DEFAULT_TUFLOW_EXE
from .core import Issue, ModelNode, Severity, TuflowTestResult
from .parsing import parse_hpc_tlf_summary, parse_tlf_summary, scan_all_inputs
from .tuflow_runner import run_tuflow_test_and_analyse


# Keep Finding as an alias to the existing Issue structure for compatibility.
Finding = Issue


@dataclass
class RunResult:
    """Structured result of a QA/QC run."""

    ok: bool
    report_text: str
    report_html: Optional[str]
    findings: List[Finding] = field(default_factory=list)
    inputs_missing: List[str] = field(default_factory=list)
    logs_used: List[str] = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)
    input_scan: Optional[object] = None
    model_tree: Optional[ModelNode] = None
    test_result: Optional[TuflowTestResult] = None
    qa_issues: List[Issue] = field(default_factory=list)
    debug_log: List[str] = field(default_factory=list)


def _generate_text_report(
    scan_result,
    test_result: Optional[TuflowTestResult],
    qa_issues: Optional[List[Issue]],
) -> str:
    buf = StringIO()
    with redirect_stdout(buf):
        print_validation_report(scan_result, test_result, qa_issues)
    return buf.getvalue()


def _count_leaf_nodes(node: Optional[ModelNode]) -> int:
    if not node:
        return 0
    if not node.children:
        return 1 if node.path else 0
    return sum(_count_leaf_nodes(child) for child in node.children)


def _render_model_node(node: ModelNode, *, open_branch: bool = True) -> str:
    """Render a ModelNode (and its children) as nested HTML lists."""

    label = html.escape(node.name)
    title_attr = f" title=\"Referenced from {html.escape(node.source_control)}\"" if node.source_control else ""

    if node.path:
        href = node.path.as_uri()
        label = f'<a href="{href}">{label}</a>'
        if not node.exists:
            label = f'<span style="color:#b00020;">⚠️ {label} (missing)</span>'

    if node.children:
        count = _count_leaf_nodes(node)
        summary = f"📁 {label}"
        if count:
            summary += f" ({count})"
        children_html = "".join(_render_model_node(ch, open_branch=False) for ch in node.children)
        open_attr = " open" if open_branch else ""
        return f"<details{open_attr}{title_attr}><summary>{summary}</summary><ul>{children_html}</ul></details>"

    return f"<li{title_attr}>{label}</li>"


def _render_model_tree(model_tree: Optional[ModelNode]) -> str:
    if not model_tree:
        return "<p>No model structure available.</p>"

    children_html = "".join(_render_model_node(child) for child in model_tree.children)
    return f"<h3>Model Structure</h3><div>{children_html}</div>"


def _build_html_report(
    run_text: str,
    findings: List[Issue],
    missing_inputs: List[str],
    model_tree: Optional[ModelNode],
) -> str:
    """Convert the plain-text report to a structured HTML representation."""

    def _count_by_severity(level: Severity) -> int:
        return sum(1 for f in findings if f.severity == level)

    errors = _count_by_severity(Severity.CRITICAL)
    warnings = _count_by_severity(Severity.MAJOR)
    infos = _count_by_severity(Severity.MINOR)

    if missing_inputs:
        errors += len(missing_inputs)

    escaped = html.escape(run_text)
    body = escaped.replace("\n", "<br>\n")

    summary = (
        "<div style=\"padding:6px 8px; border:1px solid #ccc; margin-bottom:8px;\">"
        f"<strong>Errors:</strong> {errors} &nbsp; "
        f"<strong>Warnings:</strong> {warnings} &nbsp; "
        f"<strong>Info:</strong> {infos}"
        "</div>"
    )

    missing_block = ""
    if missing_inputs:
        missing_items = "".join(
            f"<li>{html.escape(str(p))}</li>" for p in sorted(missing_inputs)
        )
        missing_block = f"<div><strong>Missing inputs:</strong><ul>{missing_items}</ul></div>"

    tree_html = _render_model_tree(model_tree)
    text_section = f"<details><summary>Full text report</summary><pre>{body}</pre></details>"

    return f"<html><body>{summary}{missing_block}{tree_html}{text_section}</body></html>"


def run_qaqc(
    tcf_path: str,
    *,
    run_test: bool = False,
    tuflow_exe: Optional[str] = None,
    wildcards: Optional[Dict[str, str]] = None,
    output_format: str = "html",
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    debug: bool = False,
) -> RunResult:
    """
    Run the QA/QC pipeline programmatically.

    Args mirror the CLI flags; wildcards should be provided as a mapping rather
    than parsed from argv. A minimal HTML report is generated by default.
    """

    def _maybe_cancel(stage: str) -> None:
        if cancel_callback and cancel_callback():
            raise RuntimeError(f"Cancelled during {stage}")

    tcf = Path(tcf_path).expanduser().resolve()
    wildcard_map = dict(wildcards or {})
    timings: Dict[str, float] = {}
    t_start = time.perf_counter()

    _maybe_cancel("initialisation")
    if progress_callback:
        progress_callback(5.0, "Initialising")

    # Stage 0 + 1: control parsing + input scan
    s0_start = time.perf_counter()
    scan_result = scan_all_inputs(tcf, wildcard_map, debug=debug)
    timings["scan"] = time.perf_counter() - s0_start

    if progress_callback:
        progress_callback(35.0, "Scanned control files and inputs")
    _maybe_cancel("input scan")

    test_result: Optional[TuflowTestResult] = None
    qa_issues: List[Issue] = []

    exe_path = Path(tuflow_exe).expanduser().resolve() if tuflow_exe else DEFAULT_TUFLOW_EXE

    if run_test:
        if not exe_path.exists():
            # Produce a short message consistent with the CLI behaviour
            text_report = _generate_text_report(scan_result, None, None)
            text_report += (
                f"\n[ERROR] TUFLOW executable not found: {exe_path}\n"
                "        Use --tuflow-exe to specify the correct path.\n"
            )
            html_report = (
                _build_html_report(
                    text_report,
                    scan_result.control_tree.issues,
                    [],
                    scan_result.model_tree,
                )
                if output_format == "html"
                else None
            )
            return RunResult(
                ok=False,
                report_text=text_report,
                report_html=html_report,
                findings=list(scan_result.control_tree.issues),
                inputs_missing=[str(inp.path) for inp in scan_result.inputs if not inp.exists],
                logs_used=[],
                timings=timings,
                input_scan=scan_result,
                model_tree=scan_result.model_tree,
                test_result=None,
                qa_issues=[],
            )

        if progress_callback:
            progress_callback(45.0, "Running TUFLOW test (-t)")
        _maybe_cancel("TUFLOW test")

        s2_start = time.perf_counter()
        test_result = run_tuflow_test_and_analyse(
            tcf_path=tcf,
            wildcards=wildcard_map,
            control_tree=scan_result.control_tree,
            tuflow_exe=exe_path,
        )
        timings["tuflow_test"] = time.perf_counter() - s2_start

        if progress_callback:
            progress_callback(70.0, "Parsing TUFLOW logs")
        _maybe_cancel("log parsing")

        # Stage 3: QA checks
        tlf_summary = parse_tlf_summary(test_result.logs.tlf)
        hpc_summary = parse_hpc_tlf_summary(test_result.logs.hpc_tlf)

        qa_issues = run_time_and_timestep_checks(
            tcf_path=tcf,
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
            test_result=test_result,
        )
        qa_issues += run_parameter_sanity_checks(
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
        )

        if progress_callback:
            progress_callback(90.0, "QA checks complete")
        _maybe_cancel("QA checks")

    # Render reports
    text_report = _generate_text_report(scan_result, test_result, qa_issues)

    html_report = None
    if output_format == "html":
        missing_inputs = [str(inp.path) for inp in scan_result.inputs if not inp.exists]
        findings: List[Issue] = list(scan_result.control_tree.issues) + list(qa_issues)
        html_report = _build_html_report(
            text_report, findings, missing_inputs, scan_result.model_tree
        )

    ok = True
    if run_test and test_result and test_result.return_code not in (0, None):
        ok = False
    if any(not inp.exists for inp in scan_result.inputs):
        ok = False

    t_end = time.perf_counter()
    timings["total"] = t_end - t_start

    if progress_callback:
        progress_callback(100.0, "Finished")

    missing_inputs = [str(inp.path) for inp in scan_result.inputs if not inp.exists]
    findings = list(scan_result.control_tree.issues) + list(qa_issues)
    logs_used: List[str] = []
    if test_result:
        for p in [test_result.logs.tlf, test_result.logs.hpc_tlf, test_result.logs.messages_csv]:
            if p:
                logs_used.append(str(p))

    return RunResult(
        ok=ok,
        report_text=text_report,
        report_html=html_report,
        findings=findings,
        inputs_missing=missing_inputs,
        logs_used=logs_used,
        timings=timings,
        input_scan=scan_result,
        model_tree=scan_result.model_tree,
        test_result=test_result,
        qa_issues=qa_issues,
        debug_log=scan_result.debug_log,
    )


__all__ = ["run_qaqc", "RunResult", "Finding"]
