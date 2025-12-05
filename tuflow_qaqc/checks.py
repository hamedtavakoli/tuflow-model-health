"""
QA check functions for TUFLOW models.

Includes Stage 5.x (time & timestep) and Stage 6.x (parameter sanity) checks.
"""

from pathlib import Path
from typing import List, Optional, Dict, Any

from .config import (
    MAX_DURATION_HOURS_MAJOR, MAX_DURATION_HOURS_MINOR,
    MIN_HPC_TIMESTEP_TINY, HPC_DTMAX_FACTOR_WARN,
    COURANT_C_ASSUMED, COURANT_MAJOR, COURANT_MINOR,
    MAX_OUTPUTS_MAJOR, MIN_OUTPUTS_MINOR,
)
from .core import (
    Issue, Severity, TuflowTlfSummary, TuflowHpcSummary, TuflowTestResult
)
from .parsing import _extract_first_float
from .validators import _make_issue, MANNING_N_CHECKER, SOIL_IL_CHECKER, SOIL_CL_CHECKER


def _normalise_solution_scheme(raw: Optional[str]) -> Optional[str]:
    """Normalise solution scheme string to 'HPC', 'CLASSIC', or raw."""
    if not raw:
        return None
    u = raw.upper()
    if "HPC" in u:
        return "HPC"
    if "CLASSIC" in u:
        return "CLASSIC"
    return raw.strip()


# ---- 5.x time control & timestep checks ----

def _check_run_test_success(
    tlf_summary: Optional[TuflowTlfSummary],
    test_result: TuflowTestResult,
) -> List[Issue]:
    """Check if TUFLOW run test completed successfully."""
    issues: List[Issue] = []

    if test_result.error_count > 0:
        issues.append(
            _make_issue(
                "TIME00",
                Severity.CRITICAL,
                "TimeControl",
                f"Run test reported {test_result.error_count} error(s) in _messages.csv.",
                suggestion="Review the error messages above and the linked TUFLOW wiki pages, then fix the model setup.",
                file=test_result.logs.messages_csv,
            )
        )

    if not tlf_summary:
        issues.append(
            _make_issue(
                "TIME01",
                Severity.CRITICAL,
                "TimeControl",
                "No .tlf log file found; cannot confirm run-test success.",
                suggestion="Check Log Folder settings and that the TUFLOW run completed to the log-writing stage.",
                file=test_result.logs.tlf,
            )
        )
        return issues

    if not tlf_summary.has_running_line:
        issues.append(
            _make_issue(
                "TIME02",
                Severity.CRITICAL,
                "TimeControl",
                "Run test did not reach 'Running TUFLOW...' message in .tlf.",
                suggestion="Review messages.csv for errors and ensure the model passes all TUFLOW QC checks.",
                file=tlf_summary.path,
            )
        )

    return issues


def _check_time_window(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    """Check simulation time window for validity and reasonableness."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    st = tlf_summary.start_time_h
    et = tlf_summary.end_time_h
    dur = tlf_summary.duration_h

    if st is None or et is None:
        issues.append(
            _make_issue(
                "TIME10",
                Severity.CRITICAL,
                "TimeControl",
                "Start Time (h) or End Time (h) not reported in .tlf.",
                suggestion="Check that Start Time and End Time are defined in the control files.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur is None:
        issues.append(
            _make_issue(
                "TIME11",
                Severity.CRITICAL,
                "TimeControl",
                "Simulation duration could not be computed from Start/End times.",
                suggestion="Check Start Time and End Time definitions in the control files.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur <= 0:
        issues.append(
            _make_issue(
                "TIME12",
                Severity.CRITICAL,
                "TimeControl",
                f"Simulation duration is non-positive (Start={st} h, End={et} h).",
                suggestion="Confirm Start Time and End Time are correct and in hours.",
                file=tlf_summary.path,
            )
        )
        return issues

    if dur > MAX_DURATION_HOURS_MAJOR:
        issues.append(
            _make_issue(
                "TIME13",
                Severity.MAJOR,
                "TimeControl",
                f"Simulation duration is {dur:.1f} h, which exceeds {MAX_DURATION_HOURS_MAJOR} h.",
                suggestion="Confirm that the End Time is correct and that the long duration is intentional.",
                file=tlf_summary.path,
            )
        )
    elif dur > MAX_DURATION_HOURS_MINOR:
        issues.append(
            _make_issue(
                "TIME14",
                Severity.MINOR,
                "TimeControl",
                f"Simulation duration is {dur:.1f} h (above {MAX_DURATION_HOURS_MINOR} h).",
                suggestion="Check that the simulation duration is appropriate for the event being modelled.",
                file=tlf_summary.path,
            )
        )

    return issues


def _check_output_intervals(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    """Check map and time-series output intervals for reasonableness."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    dur = tlf_summary.duration_h
    map_int = tlf_summary.map_output_interval_s
    ts_int = tlf_summary.ts_output_interval_s

    # Map outputs
    if map_int is None:
        issues.append(
            _make_issue(
                "OUT01",
                Severity.MINOR,
                "OutputInterval",
                "ASC Map Output Interval (s) not reported in .tlf (TUFLOW defaults may apply).",
                suggestion="Consider explicitly setting Map Output Interval in the control files for clarity.",
                file=tlf_summary.path,
            )
        )
    elif map_int <= 0:
        issues.append(
            _make_issue(
                "OUT02",
                Severity.CRITICAL,
                "OutputInterval",
                f"ASC Map Output Interval (s) is non-positive: {map_int}.",
                suggestion="Set a positive Map Output Interval in seconds.",
                file=tlf_summary.path,
            )
        )
    elif dur is not None and dur > 0:
        n = dur * 3600.0 / map_int
        if n > MAX_OUTPUTS_MAJOR:
            issues.append(
                _make_issue(
                    "OUT03",
                    Severity.MAJOR,
                    "OutputInterval",
                    f"Map outputs count ~{n:.0f}, which exceeds {MAX_OUTPUTS_MAJOR:.0f}.",
                    suggestion="Increase Map Output Interval to reduce output volume and improve performance.",
                    file=tlf_summary.path,
                )
            )
        elif n < MIN_OUTPUTS_MINOR:
            issues.append(
                _make_issue(
                    "OUT04",
                    Severity.MINOR,
                    "OutputInterval",
                    f"Map outputs count ~{n:.1f} (very few; may miss temporal behaviour).",
                    suggestion="Decrease Map Output Interval if more temporal detail is required.",
                    file=tlf_summary.path,
                )
            )

    # Time series outputs
    if ts_int is None:
        issues.append(
            _make_issue(
                "OUT05",
                Severity.MINOR,
                "OutputInterval",
                "Time Series Output Interval (s) not reported in .tlf (TUFLOW defaults may apply).",
                suggestion="Consider explicitly setting Time Series Output Interval in the control files.",
                file=tlf_summary.path,
            )
        )
    elif ts_int <= 0:
        issues.append(
            _make_issue(
                "OUT06",
                Severity.CRITICAL,
                "OutputInterval",
                f"Time Series Output Interval (s) is non-positive: {ts_int}.",
                suggestion="Set a positive Time Series Output Interval in seconds.",
                file=tlf_summary.path,
            )
        )
    elif dur is not None and dur > 0:
        n = dur * 3600.0 / ts_int
        if n > MAX_OUTPUTS_MAJOR:
            issues.append(
                _make_issue(
                    "OUT07",
                    Severity.MAJOR,
                    "OutputInterval",
                    f"Time series outputs count ~{n:.0f}, which exceeds {MAX_OUTPUTS_MAJOR:.0f}.",
                    suggestion="Increase Time Series Output Interval to reduce output volume and improve performance.",
                    file=tlf_summary.path,
                )
            )
        elif n < MIN_OUTPUTS_MINOR:
            issues.append(
                _make_issue(
                    "OUT08",
                    Severity.MINOR,
                    "OutputInterval",
                    f"Time series outputs count ~{n:.1f} (very few; may miss hydrograph shape).",
                    suggestion="Decrease Time Series Output Interval if more temporal detail is required.",
                    file=tlf_summary.path,
                )
            )

    return issues


def _check_solution_scheme_and_logs(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    """Check that .hpc.tlf exists when HPC scheme is used."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)

    if scheme == "HPC":
        if hpc_summary is None:
            issues.append(
                _make_issue(
                    "SCHEME01",
                    Severity.MAJOR,
                    "SolverScheme",
                    "2D Solution Scheme == HPC but .hpc.tlf log file is missing.",
                    suggestion="Check Log Folder settings and ensure the HPC solver is executed.",
                    file=tlf_summary.path,
                )
            )

    return issues


def _check_timestep_hpc(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    """Check HPC timestep constraints."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme != "HPC":
        return issues

    if hpc_summary is None:
        return issues  # already flagged in scheme check

    dt_min = hpc_summary.timestep_min_s
    dt_max = hpc_summary.timestep_max_s
    dx = hpc_summary.cell_size_m

    if dt_min is not None and dt_min <= 0:
        issues.append(
            _make_issue(
                "HPC_TS01",
                Severity.CRITICAL,
                "TimestepHPC",
                f"HPC minimum timestep is non-positive: {dt_min} s.",
                suggestion="Review the model stability and timestep controls.",
                file=hpc_summary.path,
            )
        )
    elif dt_min is not None and dt_min < MIN_HPC_TIMESTEP_TINY:
        issues.append(
            _make_issue(
                "HPC_TS02",
                Severity.MAJOR,
                "TimestepHPC",
                f"HPC minimum timestep is extremely small: {dt_min} s.",
                suggestion="Investigate local instabilities or highly restrictive conditions in the model.",
                file=hpc_summary.path,
            )
        )

    if dx is not None and dt_max is not None:
        if dt_max > HPC_DTMAX_FACTOR_WARN * dx:
            issues.append(
                _make_issue(
                    "HPC_TS03",
                    Severity.MINOR,
                    "TimestepHPC",
                    f"HPC maximum timestep ({dt_max} s) is large relative to cell size ({dx} m).",
                    suggestion="Consider capping Timestep Maximum to around 0.5 * cell size (in seconds) if stability issues occur.",
                    file=hpc_summary.path,
                )
            )

    return issues


def _check_timestep_classic(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    """Check Classic solver timestep via Courant number estimate."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme == "HPC":
        return issues  # handled by HPC checks

    dx = tlf_summary.cell_size_m
    dt: Optional[float] = None

    # Try to find "Time Step (s) ==" line in the .tlf
    text = tlf_summary.path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        stripped = line.strip()
        if ("Time Step" in stripped or "TimeStep" in stripped) and "(s)" in stripped and "==" in stripped:
            val = _extract_first_float(stripped)
            if val is not None:
                dt = val
                break

    if dx is None or dt is None:
        return issues  # cannot compute Courant estimate

    c = COURANT_C_ASSUMED
    C = dt * c / dx

    if C > COURANT_MAJOR:
        issues.append(
            _make_issue(
                "CLASSIC_TS01",
                Severity.MAJOR,
                "TimestepClassic",
                f"Estimated Courant number C ≈ {C:.2f} (dx={dx} m, dt={dt} s) exceeds {COURANT_MAJOR}.",
                suggestion="Reduce the timestep or increase cell size to improve numerical stability.",
                file=tlf_summary.path,
            )
        )
    elif C > COURANT_MINOR:
        issues.append(
            _make_issue(
                "CLASSIC_TS02",
                Severity.MINOR,
                "TimestepClassic",
                f"Estimated Courant number C ≈ {C:.2f} (dx={dx} m, dt={dt} s) exceeds {COURANT_MINOR}.",
                suggestion="Consider reducing timestep if the model shows signs of instability.",
                file=tlf_summary.path,
            )
        )

    return issues


def run_time_and_timestep_checks(
    tcf_path: Path,
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
    test_result: TuflowTestResult,
) -> List[Issue]:
    """Aggregate all 5.x checks into a single list of Issues."""
    issues: List[Issue] = []

    issues.extend(_check_run_test_success(tlf_summary, test_result))
    issues.extend(_check_time_window(tlf_summary))
    issues.extend(_check_output_intervals(tlf_summary))
    issues.extend(_check_solution_scheme_and_logs(tlf_summary, hpc_summary))
    issues.extend(_check_timestep_hpc(tlf_summary, hpc_summary))
    issues.extend(_check_timestep_classic(tlf_summary))

    return issues


# ---- 6.x parameter sanity checks ----

def _check_manning_n(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    """Check Manning's roughness values using generic ParameterChecker."""
    if not tlf_summary or not tlf_summary.materials:
        issues: List[Issue] = []
        issues.append(
            _make_issue(
                "N00",
                Severity.MINOR,
                "ManningN",
                "No material values reported in .tlf; Manning's n sanity check skipped.",
                suggestion="Confirm that materials are defined and that the .tlf contains material values.",
                file=tlf_summary.path if tlf_summary else None,
            )
        )
        return issues if tlf_summary else []
    
    # Collect Manning's n values for checking
    manning_params = [
        (mat.name, mat.manning_n, f"Manning's n")
        for mat in tlf_summary.materials
        if mat.manning_n is not None
    ]
    
    if not manning_params:
        return [
            _make_issue(
                "N01",
                Severity.MINOR,
                "ManningN",
                "No Manning's n values could be read from Material Values block.",
                suggestion="Check the material definitions in the control files.",
                file=tlf_summary.path,
            )
        ]
    
    # Use generic checker
    return MANNING_N_CHECKER.check(manning_params, source_file=tlf_summary.path)


def _check_soil_ilcl(tlf_summary: Optional[TuflowTlfSummary]) -> List[Issue]:
    """Check soil Initial Loss / Continuing Loss parameters using generic ParameterChecker."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    soils = [
        s
        for s in tlf_summary.soils
        if s.approach.strip().lower().startswith("initial loss/continuing loss".lower())
    ]

    if not soils:
        return issues  # no IL/CL soils to check

    # Check Initial Loss values
    il_params = [
        (soil.name, soil.initial_loss_mm, "Initial Loss (mm)")
        for soil in soils
        if soil.initial_loss_mm is not None
    ]
    if il_params:
        issues.extend(SOIL_IL_CHECKER.check(il_params, source_file=tlf_summary.path))

    # Check Continuing Loss values
    cl_params = [
        (soil.name, soil.continuing_loss_mm_per_hr, "Continuing Loss (mm/hr)")
        for soil in soils
        if soil.continuing_loss_mm_per_hr is not None
    ]
    if cl_params:
        issues.extend(SOIL_CL_CHECKER.check(cl_params, source_file=tlf_summary.path))

    return issues


def _check_solver_hardware(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    """Check for GPU/CUDA errors in HPC runs."""
    issues: List[Issue] = []
    if not tlf_summary:
        return issues

    scheme = _normalise_solution_scheme(tlf_summary.solution_scheme)
    if scheme != "HPC":
        return issues

    if hpc_summary is None:
        return issues  # missing .hpc.tlf already covered elsewhere

    if hpc_summary.gpu_found is False or hpc_summary.gpu_error_messages:
        details: Dict[str, Any] = {}
        if hpc_summary.gpu_error_messages:
            details["gpu_errors"] = hpc_summary.gpu_error_messages

        issues.append(
            _make_issue(
                "SOLV01",
                Severity.MAJOR,
                "SolverHardware",
                "HPC solver encountered GPU/driver issues; check CUDA / GPU configuration.",
                suggestion="Review .hpc.tlf for CUDA / GPU errors and confirm the correct GPU drivers are installed.",
                file=hpc_summary.path,
                details=details,
            )
        )

    return issues


def run_parameter_sanity_checks(
    tlf_summary: Optional[TuflowTlfSummary],
    hpc_summary: Optional[TuflowHpcSummary],
) -> List[Issue]:
    """Aggregate all 6.x parameter sanity checks into a single list of Issues."""
    issues: List[Issue] = []

    issues.extend(_check_manning_n(tlf_summary))
    issues.extend(_check_soil_ilcl(tlf_summary))
    issues.extend(_check_solver_hardware(tlf_summary, hpc_summary))

    return issues
