"""Shared wildcard validation utilities."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Set

from .config import WILDCARD_RE


@dataclass
class WildcardValidationResult:
    detected: Set[str]
    missing: Set[str]
    required: bool
    message: str
    ok_to_proceed: bool
    severity: Literal["none", "warning", "error"]


def _format_missing(missing: Set[str]) -> str:
    return ", ".join(f"~{m}~" for m in sorted(missing))


def validate_wildcards(
    tcf_path: str,
    wildcard_values: Dict[str, str],
    *,
    run_test: bool,
    stages_enabled: Dict[str, bool],
    will_build_paths: bool,
) -> WildcardValidationResult:
    """Validate wildcard coverage for CLI and QGIS entry points."""

    # Detect all wildcard tokens in the provided path (including parent dirs)
    path_obj = Path(tcf_path)
    detected = {m.group("var") for m in WILDCARD_RE.finditer(str(path_obj))}

    provided = {k for k, v in wildcard_values.items() if str(v).strip() != ""}
    missing = detected - provided

    requires_values = run_test or will_build_paths

    if not missing:
        return WildcardValidationResult(
            detected=detected,
            missing=missing,
            required=requires_values,
            message="",
            ok_to_proceed=True,
            severity="none",
        )

    missing_fmt = _format_missing(missing)
    suggestion_values = " ".join(f"~{name}~=VALUE" for name in sorted(missing))
    suggestion = "Provide values after --, e.g. -- " + suggestion_values
    message = f"Missing wildcard values: {missing_fmt}\n\n{suggestion}" if suggestion_values else (
        f"Missing wildcard values: {missing_fmt}"
    )

    if run_test or (missing and will_build_paths):
        severity: Literal["error", "warning"] = "error"
        ok = False
    else:
        severity = "warning"
        ok = True
        message += "\nProceeding without substituting these values."

    return WildcardValidationResult(
        detected=detected,
        missing=missing,
        required=requires_values,
        message=message,
        ok_to_proceed=ok,
        severity=severity,
    )


__all__ = ["WildcardValidationResult", "validate_wildcards"]
