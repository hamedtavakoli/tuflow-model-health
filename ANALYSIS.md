# Repository Analysis: TUFLOW Model Health QA/QC

This repository provides early-stage quality assurance and quality control helpers for TUFLOW models. The code currently focuses on static, pre-run validation to detect missing files, configuration issues, and available run options.

## Repository Layout
- `README.md` — brief project description.
- `tuflow_qaqc/` — package containing the pre-run checking logic.
  - `__init__.py` — package marker (currently empty).
  - `pre_run.py` — parsing utilities, data models, validation routines, and a simple CLI entry point.

## Key Concepts and Data Structures
- **Severity** (`Severity` enum): categorises issues as Critical, Major, or Minor.
- **Issue**: captures a validation finding with identifiers, severity, category, human-readable messaging, optional file/line references, and detail metadata.
- **DiscoveryResult**: summarises available scenarios, events, wildcard variables, and event files discovered across control files.
- **PreRunSettings**: toggles for structural checks (e.g., expected folders) with configurable expected subdirectories.
- **ControlDirective** / **ControlFile**: lightweight representations of parsed control-file directives and their source locations.
- **ModelConfig**: aggregates the main TCF, included control files, and categorised referenced paths (control/GIS/BC/tables/other).
- **PreRunResult**: wraps the final issue list and a boolean flag indicating whether critical errors were detected.

## Parsing and Discovery Flow
- `parse_control_file` reads a control file (TCF/TGC/ECF/etc.) and extracts directive key/value pairs using regex-based parsing while skipping empty lines and comments (`COMMENT_RE`).
- `_collect_control_files_and_paths` recursively follows referenced control files (`CONTROL_KEYWORDS`) and categorises other path-like tokens using simple heuristics (`_categorise_path`).
- `build_model_config` starts from a provided TCF and builds a `ModelConfig`, collecting both child control files and referenced paths.
- `_scan_control_file_for_discovery` and `_scan_tef_for_events` skim control and TEF files to identify scenarios, events, event files, and wildcard variables.
- `discover_run_options` compiles a `DiscoveryResult` from all control files and event files reachable via the main TCF.

## Validation Checks (Static Pre-run)
- `check_tcf_exists` confirms the supplied TCF path exists before further processing.
- `check_expected_folders` optionally verifies the presence of expected subdirectories (default: `log`, `check`, `results`).
- `check_control_files_exist` ensures all referenced control files were found during model configuration collection.
- `check_referenced_files_exist` validates GIS, boundary condition, table, and other referenced files, escalating severity for critical path categories.
- `check_time_settings` performs presence, numeric parsing, and basic sanity checks on `Start Time`, `End Time`, and `Time Step` directives, including a long-duration warning.
- `run_pre_run_checks` orchestrates the static validation pipeline: TCF existence, folder checks, model construction, control/path validation, and time checks, returning a `PreRunResult` with aggregated issues and a `static_checks_ok` flag.

## CLI Usage
The module exposes a simple CLI when executed directly:
- Discovery mode: `python -m tuflow_qaqc.pre_run --discover path/to/model.tcf` prints discovered control files, scenarios, events, wildcard variables, and event files.
- Static checks: `python -m tuflow_qaqc.pre_run path/to/model.tcf` runs the pre-run checks and prints issues and overall status.

## Notes and Potential Follow-ups
- Parsing uses permissive regex heuristics; non-standard directive formats may be skipped silently. Additional logging or error surfacing could help trace unusual lines.
- `_collect_control_files_and_paths` currently treats missing includes by skipping them; a dedicated issue (with path context) might aid debugging.
- The CLI is minimal and could be expanded with structured output (JSON) for integration into automated pipelines.
- Tests are absent; unit coverage for parsers, discovery, and validation logic would improve robustness.
