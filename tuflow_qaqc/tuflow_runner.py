"""
TUFLOW execution and log collection utilities.
"""

from pathlib import Path
from typing import Dict, Tuple
import subprocess

from .config import DEFAULT_TUFLOW_EXE
from .core import TuflowRunLogs, TuflowTestResult, ControlTree
from .parsing import find_log_folder, build_log_stem, parse_messages_csv


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
    error_lines = []
    msg_number_counts = {}

    if logs.messages_csv:
        (
            error_count,
            warning_count,
            check_count,
            error_lines,
            msg_number_counts,
        ) = parse_messages_csv(logs.messages_csv)

    # For warnings/checks we keep short summary strings (for CLI display)
    warnings_summary = []
    checks_summary = []

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
