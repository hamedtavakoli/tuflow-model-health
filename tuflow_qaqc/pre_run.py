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

from .config import DEFAULT_TUFLOW_EXE
from .parsing import scan_all_inputs, find_wildcards_in_filename, build_wildcard_map_from_args
from .tuflow_runner import run_tuflow_test_and_analyse
from .parsing import parse_tlf_summary, parse_hpc_tlf_summary
from .checks import run_time_and_timestep_checks, run_parameter_sanity_checks
from .cli import print_validation_report


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

    # Stage 1: scan control files & inputs
    result = scan_all_inputs(tcf_path, wildcard_map)

    # Print Stage 0 & 1 results
    print_validation_report(result)

    # Stage 2: optional TUFLOW run test (-t) and log parsing
    if run_test:
        exe_to_use = tuflow_exe or DEFAULT_TUFLOW_EXE
        if not exe_to_use.exists():
            print(
                f"\n[ERROR] TUFLOW executable not found: {exe_to_use}\n"
                "        Use --tuflow-exe to specify the correct path."
            )
            return

        print(f"\nRunning TUFLOW test (-t) using: {exe_to_use}")
        test_result = run_tuflow_test_and_analyse(
            tcf_path=tcf_path,
            wildcards=wildcard_map,
            control_tree=result.control_tree,
            tuflow_exe=exe_to_use,
        )

        # Stage 3: QA checks based on .tlf / .hpc.tlf (5.x and 6.x)
        tlf_summary = parse_tlf_summary(test_result.logs.tlf)
        hpc_summary = parse_hpc_tlf_summary(test_result.logs.hpc_tlf)

        time_issues = run_time_and_timestep_checks(
            tcf_path=tcf_path,
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
            test_result=test_result,
        )

        param_issues = run_parameter_sanity_checks(
            tlf_summary=tlf_summary,
            hpc_summary=hpc_summary,
        )

        all_issues = time_issues + param_issues

        # Print all results
        print_validation_report(result, test_result, all_issues)


if __name__ == "__main__":
    main(sys.argv[1:])
