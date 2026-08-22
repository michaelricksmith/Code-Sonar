"""Finding model — normalized issue detected by analyzers."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FindingCategory(str, Enum):
    """Finding category types."""

    COMPLEXITY = "complexity"
    STALENESS = "staleness"
    SECURITY = "security"
    DUPLICATION = "duplication"
    TESTING = "testing"
    MAINTAINABILITY = "maintainability"


class FindingSeverity(str, Enum):
    """Finding severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Finding(BaseModel):
    """Normalized finding from any analyzer.

    All analyzers must produce findings in this schema.
    """

    id: str = Field(description="Unique finding identifier")
    rule_id: str = Field(description="Rule identifier (e.g., 'complexity:high-cc')")
    category: FindingCategory = Field(description="Primary category")
    severity: FindingSeverity = Field(description="Severity level")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")

    # Location
    file_path: str = Field(description="Relative file path from repo root")
    line_start: int | None = Field(default=None, description="Start line number (1-indexed)")
    line_end: int | None = Field(default=None, description="End line number (1-indexed)")
    symbol: str | None = Field(default=None, description="Function/class/symbol name")

    # Evidence
    evidence: str = Field(description="What was detected (e.g., 'CC=28, MI=32')")
    message: str = Field(description="Human-readable explanation")
    suggestion: str | None = Field(default=None, description="How to fix or improve")

    # Debt
    debt_points: int = Field(ge=0, description="Points contributed to debt score")
    remediation_effort: str | None = Field(
        default=None, description="Estimated effort (e.g., '2 hours', '1 day')"
    )

    # Metadata
    analyzer: str = Field(description="Analyzer that generated this finding")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Analyzer-specific data")
    detected_at: datetime = Field(default_factory=datetime.utcnow, description="Detection timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "finding_abc123",
                "rule_id": "complexity:high-cc",
                "category": "complexity",
                "severity": "warning",
                "confidence": 0.95,
                "file_path": "src/legacy/auth.ts",
                "line_start": 1,
                "line_end": 342,
                "symbol": "authenticateUser",
                "evidence": "CC=28, MI=32, LOC=342",
                "message": "Function 'authenticateUser' has high cyclomatic complexity (28)",
                "suggestion": "Consider refactoring into smaller functions",
                "debt_points": 12,
                "remediation_effort": "4 hours",
                "analyzer": "complexity_analyzer",
                "metadata": {"cc": 28, "mi": 32, "loc": 342},
                "detected_at": "2026-08-22T17:13:00Z",
            }
        }
