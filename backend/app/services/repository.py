"""Repository scanning service — orchestrates analyzers."""

from pathlib import Path

from app.analyzers.base import Analyzer
from app.analyzers.comment_markers import CommentMarkersAnalyzer
from app.models.finding import Finding


def get_registered_analyzers() -> list[Analyzer]:
    """Return list of all registered analyzers.
    
    To add a new analyzer:
    1. Create analyzer class inheriting from Analyzer
    2. Add instance to the list returned here
    """
    return [
        CommentMarkersAnalyzer(),
        # Add more analyzers here as they're built
    ]


def scan_repository(repo_path: Path) -> list[Finding]:
    """Scan repository with all registered analyzers.
    
    Args:
        repo_path: Path to repository root directory
        
    Returns:
        Aggregated findings from all analyzers
    """
    # Ensure path is resolved and exists
    repo_path = repo_path.resolve()
    if not repo_path.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    
    if not repo_path.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")
    
    # Run all analyzers
    all_findings: list[Finding] = []
    analyzers = get_registered_analyzers()
    
    for analyzer in analyzers:
        try:
            findings = analyzer.analyze(repo_path)
            all_findings.extend(findings)
        except Exception as e:
            # Log error but continue with other analyzers
            # In production, this should use proper logging
            print(f"Analyzer {analyzer.name} failed: {e}")
    
    return all_findings
