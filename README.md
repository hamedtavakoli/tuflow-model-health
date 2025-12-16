# TUFLOW Model Health QA/QC

Tools for automated pre-run and test-run quality checks for TUFLOW hydraulic models.

## Installation

No external dependencies required beyond Python 3.7+. Uses only standard library modules:
- `pathlib`, `dataclasses`, `enum`, `re`, `subprocess`, `csv`, `argparse`

### QGIS plugin bundle

The QGIS plugin ships the QA/QC engine inside `tuflow_model_health_qgis/vendor/tuflow_qaqc` so it always uses the bundled version. If you previously installed a separate `tuflow_qaqc` folder under your QGIS `python/plugins` directory, remove it to avoid conflicts.

## Quick Start

### Basic usage (Stage 0 & 1: Control files & inputs)

```bash
python -m tuflow_qaqc.pre_run path/to/model.tcf
```

### With wildcards (parameterized models)

```bash
python -m tuflow_qaqc.pre_run "model~e1~_~e2~.tcf" -- -e1 00100Y -e2 0060m
```

**Note:** Use `--` before wildcard arguments to tell argparse to stop processing flags.

### With TUFLOW test mode (Stage 2 & 3: Full validation)

```bash
python -m tuflow_qaqc.pre_run "model.tcf" --run-test --tuflow-exe "C:\TUFLOW\Exe\TUFLOW_iSP_w64.exe"
```

### With wildcards AND test mode

```bash
python -m tuflow_qaqc.pre_run "model~e1~_~e2~.tcf" --tuflow-exe "C:\TUFLOW\Exe\TUFLOW_iSP_w64.exe" --run-test -- -e1 00100Y -e2 0060m
```

**Note:** The `--` separates argparse flags (`--run-test`, `--tuflow-exe`) from wildcard arguments (`-e1`, `-e2`).

## CLI Reference

### Help

```bash
python -m tuflow_qaqc.pre_run --help
```

Output:
```
usage: tuflow-qaqc-pre-run [-h] [--run-test] [--tuflow-exe TUFLOW_EXE] tcf_path [wildcards ...]

TUFLOW Model QA/QC Pre-Run Validator

positional arguments:
  tcf_path              Path to main TUFLOW control file (.tcf)
  wildcards             Wildcard arguments for parameterized models (must come after --)

options:
  -h, --help            show this help message and exit
  --run-test            Run TUFLOW in test mode (-t) after static checks [default: False]
  --tuflow-exe TUFLOW_EXE
                        Path to TUFLOW executable (e.g., TUFLOW_iSP_w64.exe) [default: TUFLOW_iSP_w64.exe]

Examples:
  python -m tuflow_qaqc.pre_run model.tcf
  python -m tuflow_qaqc.pre_run "model~e1~_~e2~.tcf" --run-test -- -e1 00100Y -e2 0060m
  python -m tuflow_qaqc.pre_run model.tcf --tuflow-exe /path/to/TUFLOW_iSP_w64.exe --run-test
```

### Options

#### `tcf_path` (required)
Path to the main TUFLOW control file (.tcf). Can be absolute or relative.

#### `--run-test` (optional)
Run TUFLOW in test mode (`-t -b`) after static checks. Generates log files for further analysis.

Default: `False`

#### `--tuflow-exe PATH` (optional)
Path to TUFLOW executable. If not provided, defaults to `TUFLOW_iSP_w64.exe` in current PATH.

### Wildcard arguments (optional)
Arguments in the form `-NAME VALUE` for template substitution. Must come **after `--`** separator:

```bash
python -m tuflow_qaqc.pre_run "model.tcf" -- -e1 00100Y -e2 0060m
```

Examples:
- `-e1 00100Y` replaces `~e1~` in filenames
- `-e2 0060m` replaces `~e2~` in filenames
- `-s1 5m` replaces `~s1~` in filenames

## Examples

### Example 1: Basic validation

```bash
python -m tuflow_qaqc.pre_run C:\Models\project\Model_001.tcf
```

Output: Lists control file tree and input references.

### Example 2: Parameterized model

```bash
python -m tuflow_qaqc.pre_run "C:\Models\project\Model_~event~_~scenario~.tcf" -- -event rain01 -scenario high
```

### Example 3: With TUFLOW test run

```bash
python -m tuflow_qaqc.pre_run "C:\Models\project\model.tcf" `
  --run-test `
  --tuflow-exe "C:\TUFLOW\Exe\TUFLOW_iSP_w64.exe"
```

Output: Control files, inputs, TUFLOW test results, and comprehensive QA checks.

### Example 4: On Windows PowerShell (multi-line)

```powershell
python -m tuflow_qaqc.pre_run `
  "T03_B155a_~e1~_~e2~_~s1~.tcf" `
  --tuflow-exe "C:\TUFLOW\Exe\TUFLOW_iSP_w64.exe" `
  --run-test `
  -- `
  -e1 00100Y `
  -e2 0060m `
  -s1 5m
```

## Validation Stages

### Stage 0: Control File Structure
- Parses the main TCF file
- Extracts all directive key==value pairs
- Identifies referenced control files (from keywords like "Geometry Control", "BC Control", etc.)

### Stage 1: Input File Scanning
- Builds a tree of all control files (recursively)
- Scans each control file for GIS and database file references
- Checks file existence and reports missing inputs

### Stage 2: TUFLOW Test Run (optional, with `--run-test`)
- Executes TUFLOW in test mode (`-t -b`) to check model validity
- Parses TUFLOW log files (`.tlf`, `.hpc.tlf`, `_messages.csv`)
- Reports TUFLOW errors, warnings, and checks

### Stage 3: QA Checks (optional, with `--run-test`)
- **5.x checks** (Time & Timestep):
  - Simulation duration reasonableness
  - Output intervals (map & time-series)
  - Timestep validation (HPC/Classic)
  - Courant number estimation (Classic solver)
  
- **6.x checks** (Parameter Sanity):
  - Manning's roughness values (0.01–0.25 m acceptable range)
  - Soil Initial Loss / Continuing Loss (IL/CL) parameters
  - GPU/CUDA availability for HPC models

## Project Structure

```
tuflow_qaqc/
├── __init__.py           # Package initialization
├── pre_run.py            # CLI entry point (argparse-based)
├── core.py               # Data types (Issue, ControlFile, etc.)
├── config.py             # Constants, regexes, thresholds
├── parsing.py            # Control file & log parsing
├── checks.py             # QA check functions (5.x & 6.x)
├── tuflow_runner.py      # TUFLOW execution & log collection
├── validators.py         # Generic ParameterChecker for consolidation
└── cli.py                # CLI reporting & formatting
```

## Exit Codes

- `0`: Success
- `1`: Missing or invalid arguments
- `-1`: TUFLOW executable not found (with `--run-test`)

## Performance

- **Stage 0–1**: <1 second for typical models
- **Stage 2**: Depends on TUFLOW test run duration (usually 10–60 seconds)
- **Stage 3**: <1 second (QA checks on parsed logs)

## Architecture

The codebase follows a modular design with separation of concerns:

| Module | Responsibility |
|--------|-----------------|
| `core.py` | Data structures (dataclasses, enums) |
| `config.py` | All constants, regex patterns, thresholds (easy to tune) |
| `parsing.py` | Control file & log parsing logic |
| `checks.py` | QA check functions using `validators.py` for consolidation |
| `validators.py` | Generic `ParameterChecker` for parameter bounds validation |
| `tuflow_runner.py` | TUFLOW subprocess execution & log collection |
| `cli.py` | Output formatting & CLI reporting |
| `pre_run.py` | argparse-based CLI entry point |

## Troubleshooting

### Issue: "TUFLOW executable not found"
**Solution**: Use `--tuflow-exe` to specify the full path to TUFLOW:
```bash
python -m tuflow_qaqc.pre_run model.tcf --run-test --tuflow-exe "C:\path\to\TUFLOW_iSP_w64.exe"
```

### Issue: Wildcards not being substituted
**Solution**: Ensure wildcard names match exactly. For example, if your TCF is named `model~e1~_~e2~.tcf`, use:
```bash
python -m tuflow_qaqc.pre_run "model~e1~_~e2~.tcf" -e1 VALUE -e2 VALUE
```

### Issue: Input files reported as missing
**Solution**: Check that paths in control files are relative to the control file's directory. Absolute paths must exist on your system.

## Contributing

When adding new checks:
1. Add thresholds to `config.py`
2. Create check function in `checks.py`
3. Use `validators.ParameterChecker` for parameter bounds checking (consolidation)
4. Register check in `run_*_checks()` function
