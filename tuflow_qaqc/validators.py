"""
Generic validators for parameter bounds checking.

Consolidates repeated parameter validation logic into reusable checkers.
"""

from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from .core import Issue, Severity


def _make_issue(
    issue_id: str,
    severity: Severity,
    category: str,
    message: str,
    suggestion: str = "",
    file: Optional[Path] = None,
    line: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Issue:
    """Factory function for creating Issue objects."""
    return Issue(
        id=issue_id,
        severity=severity,
        category=category,
        message=message,
        suggestion=suggestion,
        file=file,
        line=line,
        details=details or {},
    )


class ParameterChecker:
    """Generic validator for parameter bounds checking.
    
    Consolidates common validation patterns for parameters with:
    - Acceptable range (min/max)
    - Critical thresholds (for extreme values)
    - Formatted issue reporting
    """
    
    def __init__(
        self,
        issue_id_prefix: str,
        category: str,
        min_acceptable: float,
        max_acceptable: float,
        critical_min: Optional[float] = None,
        critical_max: Optional[float] = None,
    ):
        """
        Initialize parameter checker.
        
        Args:
            issue_id_prefix: Prefix for issue IDs (e.g., "N" → "N01", "N02")
            category: Issue category name
            min_acceptable: Lower bound of acceptable range
            max_acceptable: Upper bound of acceptable range
            critical_min: Lower threshold for CRITICAL severity (optional)
            critical_max: Upper threshold for CRITICAL severity (optional)
        """
        self.issue_id_prefix = issue_id_prefix
        self.category = category
        self.min_acceptable = min_acceptable
        self.max_acceptable = max_acceptable
        self.critical_min = critical_min
        self.critical_max = critical_max
    
    def check(
        self,
        parameters: List[Tuple[str, Optional[float], str]],
        source_file: Optional[Path] = None,
    ) -> List[Issue]:
        """
        Check parameter bounds.
        
        Args:
            parameters: List of (label, value, param_name) tuples.
                       Example: [("Material 1", 0.03, "Manning's n"), ...]
            source_file: Path to source file for issue tracking
        
        Returns:
            List of Issue objects for out-of-range values
        """
        issues: List[Issue] = []
        values: List[float] = []
        critical_items: List[str] = []
        major_items: List[str] = []
        
        # Collect values and classify by severity
        for label, value, param_name in parameters:
            if value is None:
                continue
            
            values.append(value)
            
            # Check critical bounds first (highest severity)
            if self.critical_min is not None and value < self.critical_min:
                critical_items.append(
                    f"{label}: {param_name}={value:.3f} (< {self.critical_min})"
                )
            elif self.critical_max is not None and value > self.critical_max:
                critical_items.append(
                    f"{label}: {param_name}={value:.3f} (> {self.critical_max})"
                )
            # Then check acceptable bounds (major severity)
            elif value < self.min_acceptable or value > self.max_acceptable:
                major_items.append(
                    f"{label}: {param_name}={value:.3f} "
                    f"(outside [{self.min_acceptable}, {self.max_acceptable}])"
                )
        
        if not values:
            return issues  # No values to check
        
        min_val = min(values)
        max_val = max(values)
        
        # Generate issues
        if critical_items:
            issues.append(_make_issue(
                f"{self.issue_id_prefix}01",
                Severity.CRITICAL,
                self.category,
                f"Critical values detected (range: {min_val:.3f}–{max_val:.3f}).",
                suggestion=f"Review and correct non-physical {self.category.lower()} values.",
                file=source_file,
                details={"values": critical_items},
            ))
        elif major_items:
            issues.append(_make_issue(
                f"{self.issue_id_prefix}02",
                Severity.MAJOR,
                self.category,
                f"Out-of-range values (range: {min_val:.3f}–{max_val:.3f}). "
                f"Acceptable: [{self.min_acceptable}, {self.max_acceptable}].",
                suggestion=f"Confirm that extreme {self.category.lower()} values are intentional and documented.",
                file=source_file,
                details={"values": major_items},
            ))
        
        return issues


# Pre-configured checkers for common parameters

MANNING_N_CHECKER = ParameterChecker(
    issue_id_prefix="N",
    category="ManningN",
    min_acceptable=0.01,
    max_acceptable=0.25,
    critical_max=0.5,  # Manning's n should not exceed 0.5
)

SOIL_IL_CHECKER = ParameterChecker(
    issue_id_prefix="IL",
    category="SoilInitialLoss",
    min_acceptable=0.0,
    max_acceptable=200.0,  # mm
    critical_min=0.0,      # IL cannot be negative
    critical_max=500.0,    # IL > 500 mm is extreme
)

SOIL_CL_CHECKER = ParameterChecker(
    issue_id_prefix="CL",
    category="SoilContinuingLoss",
    min_acceptable=0.0,
    max_acceptable=50.0,   # mm/hr
    critical_min=0.0,      # CL cannot be negative
    critical_max=200.0,    # CL > 200 mm/hr is extreme
)
