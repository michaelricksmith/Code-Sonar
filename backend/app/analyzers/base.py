"""Base analyzer interface for all code analyzers."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.finding import Finding


class Analyzer(ABC):
    """Abstract base class for all analyzers.
    
    All analyzers must inherit from this class and implement the analyze method.
    """

    @abstractmethod
    def analyze(self, repo_path: Path) -> list[Finding]:
        """Analyze a repository and return findings.
        
        Args:
            repo_path: Path to the repository root directory
            
        Returns:
            List of Finding objects with normalized schema
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the analyzer name for identification."""
        pass
