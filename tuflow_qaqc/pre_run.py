"""
TUFLOW Model QA/QC Pre-Run Validator

A comprehensive validation tool for TUFLOW hydraulic models that checks:
- Stage 0: Control file structure and dependencies
- Stage 1: Input file references (GIS, databases)
- Stage 2: TUFLOW test mode (-t) execution and log parsing
- Stage 3: Time control, timestep, and parameter sanity checks
"""

import argparse
from pathlib import Path
from typing import List, Optional
import sys

from .api import run_qaqc
from .config import DEFAULT_TUFLOW_EXE
from .parsing import find_wildcards_in_filename, build_wildcard_map_from_args


def main(argv: Optional[List[str]] = None) -> None:
    r"""
    CLI entry point using argparse.

    Validates a TUFLOW model through multiple stages:
    - Stage 0: Control file structure
    - Stage 1: Input file references
    - Stage 2 (optional): TUFLOW test mode (-t) execution
    - Stage 3 (optional): QA checks (time/timestep/parameters)
    """
    parser = argparse.ArgumentParser(
        prog="tuflow-qaqc-pre-run",
        description="TUFLOW Model QA/QC Pre-Run Validator",
        epilog=(
            "Examples:\n"
            "  python -m tuflow_qaqc.pre_run model.tcf\n"
            "  python -m tuflow_qaqc.pre_run model~e1~.tcf -e1 00100Y -e2 0060m --run-test\n"
            "  python -m tuflow_qaqc.pre_run model.tcf --tuflow-exe /path/to/TUFLOW_iSP_w64.exe --run-test"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional arguments
    parser.add_argument(
        "tcf_path",
        type=Path,
        help="Path to main TUFLOW control file (.tcf)",
    )

    # Optional flags
    parser.add_argument(
        "--run-test",
        action="store_true",
        default=False,
        help="Run TUFLOW in test mode (-t) after static checks [default: False]",
    )

    parser.add_argument(
        "--tuflow-exe",
        type=Path,
        default=None,
        help="Path to TUFLOW executable (e.g., TUFLOW_iSP_w64.exe) [default: TUFLOW_iSP_w64.exe]",
    )

    # Wildcard arguments (catch-all remaining args in key=value format)
    parser.add_argument(
        "wildcards",
        nargs="*",
        help="Wildcard arguments for parameterized models (e.g., e1=VALUE e2=VALUE s1=VALUE or use -- -e1 VALUE -e2 VALUE after flags)",
    )

    # Parse arguments
    args = parser.parse_args(argv)

    # Extract arguments
    tcf_path: Path = args.tcf_path.resolve()
    run_test: bool = args.run_test
    tuflow_exe: Optional[Path] = args.tuflow_exe.resolve() if args.tuflow_exe else None
    wildcard_args: List[str] = args.wildcards
    
    # Handle wildcard args in -key value format (convert to list for build_wildcard_map_from_args)
    # This function already handles both formats

    # Stage 0: find required wildcards from TCF filename
    filename_wildcards = find_wildcards_in_filename(tcf_path)
    # Build wildcard map from CLI args (and prompt for missing)
    wildcard_map = build_wildcard_map_from_args(filename_wildcards, wildcard_args)

    result = run_qaqc(
        str(tcf_path),
        run_test=run_test,
        tuflow_exe=str(tuflow_exe) if tuflow_exe else None,
        wildcards=wildcard_map,
        output_format="text",
    )

    print(result.report_text)

    # Preserve the documented exit code when the requested TUFLOW executable is
    # missing.
    exe_to_check = Path(tuflow_exe) if tuflow_exe else DEFAULT_TUFLOW_EXE
    if run_test and not exe_to_check.exists():
        sys.exit(-1)


if __name__ == "__main__":
    main(sys.argv[1:])
