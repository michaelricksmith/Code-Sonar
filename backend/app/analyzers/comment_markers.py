"""Comment markers analyzer — detects TODO, FIXME, HACK comments."""

import re
import uuid
from pathlib import Path

from app.analyzers.base import Analyzer
from app.models.finding import Finding, FindingCategory, FindingSeverity


class CommentMarkersAnalyzer(Analyzer):
    """Detects technical debt markers in code comments.
    
    Finds:
    - TODO: Low priority items (1 debt point, info severity)
    - FIXME: Known issues needing fixes (3 debt points, warning severity)
    - HACK: Workarounds requiring proper solutions (5 debt points, error severity)
    """

    # Patterns to match comment markers
    PATTERNS = {
        "TODO": {
            "regex": re.compile(r"(?://|#|/\*|\*|<!--|--)\s*(TODO:?\s*.+)", re.IGNORECASE),
            "severity": FindingSeverity.INFO,
            "debt_points": 1,
            "message_template": "TODO comment found: {comment}",
        },
        "FIXME": {
            "regex": re.compile(r"(?://|#|/\*|\*|<!--|--)\s*(FIXME:?\s*.+)", re.IGNORECASE),
            "severity": FindingSeverity.WARNING,
            "debt_points": 3,
            "message_template": "FIXME comment indicates a known issue: {comment}",
        },
        "HACK": {
            "regex": re.compile(r"(?://|#|/\*|\*|<!--|--)\s*(HACK:?\s*.+)", re.IGNORECASE),
            "severity": FindingSeverity.ERROR,
            "debt_points": 5,
            "message_template": "HACK comment indicates a workaround: {comment}",
        },
    }

    # Binary file extensions to skip
    BINARY_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
        ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib",
        ".pyc", ".pyo", ".class", ".jar",
        ".mp3", ".mp4", ".avi", ".mov",
        ".ttf", ".woff", ".woff2", ".eot",
    }

    # Directories to skip
    SKIP_DIRS = {
        ".git", ".svn", ".hg",
        "node_modules", "__pycache__", ".pytest_cache",
        "venv", "env", ".venv",
        "dist", "build", "target",
        ".next", ".nuxt",
    }

    @property
    def name(self) -> str:
        """Return analyzer name."""
        return "comment_markers"

    def analyze(self, repo_path: Path) -> list[Finding]:
        """Analyze repository for TODO, FIXME, HACK comments.
        
        Args:
            repo_path: Path to repository root
            
        Returns:
            List of findings for each detected comment marker
        """
        findings: list[Finding] = []
        
        # Resolve to absolute path and verify it's a directory
        repo_path = repo_path.resolve()
        if not repo_path.is_dir():
            return findings

        # Load .gitignore patterns if available
        gitignore_patterns = self._load_gitignore(repo_path)

        # Walk repository
        for file_path in self._walk_files(repo_path):
            # Skip if matches .gitignore
            rel_path = file_path.relative_to(repo_path)
            if self._matches_gitignore(rel_path, gitignore_patterns):
                continue

            # Skip binary files
            if file_path.suffix.lower() in self.BINARY_EXTENSIONS:
                continue

            # Scan file
            file_findings = self._scan_file(file_path, repo_path)
            findings.extend(file_findings)

        return findings

    def _walk_files(self, repo_path: Path) -> list[Path]:
        """Walk repository and collect files, skipping ignored directories."""
        files: list[Path] = []
        
        def walk(path: Path) -> None:
            try:
                for entry in path.iterdir():
                    if entry.is_dir():
                        if entry.name not in self.SKIP_DIRS:
                            walk(entry)
                    elif entry.is_file():
                        files.append(entry)
            except PermissionError:
                pass  # Skip inaccessible directories
        
        walk(repo_path)
        return files

    def _load_gitignore(self, repo_path: Path) -> list[str]:
        """Load .gitignore patterns."""
        patterns: list[str] = []
        gitignore_path = repo_path / ".gitignore"
        
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass  # Ignore gitignore read errors
        
        return patterns

    def _matches_gitignore(self, rel_path: Path, patterns: list[str]) -> bool:
        """Check if path matches any .gitignore pattern (simplified)."""
        path_str = str(rel_path).replace("\\", "/")
        
        for pattern in patterns:
            # Simple pattern matching (exact match or prefix match for directories)
            if pattern.endswith("/"):
                # Directory pattern
                if path_str.startswith(pattern.rstrip("/")):
                    return True
            elif pattern in path_str:
                return True
        
        return False

    def _scan_file(self, file_path: Path, repo_path: Path) -> list[Finding]:
        """Scan a single file for comment markers."""
        findings: list[Finding] = []
        
        try:
            # Try reading with UTF-8, fallback to latin-1 for encoding errors
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                with open(file_path, "r", encoding="latin-1") as f:
                    lines = f.readlines()
            
            # Scan each line
            for line_num, line in enumerate(lines, start=1):
                for marker_type, config in self.PATTERNS.items():
                    match = config["regex"].search(line)
                    if match:
                        comment_text = match.group(1).strip()
                        
                        # Create finding
                        finding = Finding(
                            id=f"finding_{marker_type.lower()}_{hash((file_path.as_posix(), line_num)) & 0xFFFFFFFF:08x}",
                            rule_id=f"comment_markers:{marker_type.lower()}",
                            category=FindingCategory.MAINTAINABILITY,
                            severity=config["severity"],
                            confidence=1.0,
                            file_path=str(file_path.relative_to(repo_path)),
                            line_start=line_num,
                            line_end=line_num,
                            symbol=None,
                            evidence=comment_text,
                            message=config["message_template"].format(comment=comment_text),
                            suggestion=f"Address this {marker_type} comment to reduce technical debt",
                            debt_points=config["debt_points"],
                            remediation_effort=None,
                            analyzer=self.name,
                            metadata={"marker_type": marker_type},
                        )
                        findings.append(finding)
        
        except Exception:
            # Silently skip files that can't be read
            pass
        
        return findings
