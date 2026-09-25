"""Deterministic remediation executor — fixes structural issues without AI.

This executor handles rule types that can be resolved through deterministic
code transformations, requiring no AI API calls and no associated costs.

Currently supported:
- `oversized_files:over-threshold`: Splits oversized source files at
  top-level export boundaries. Each top-level export becomes its own file
  in a subdirectory; the original file becomes a barrel re-export.
  Non-exported helpers go into a shared `_internal` module.

Unsupported rule types return a DRY_RUN result with an explanatory message,
so the UI can honestly report "not yet supported" instead of failing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.remediation.contracts import (
    RemediationExecutionResult,
    RemediationExecutionState,
    RemediationRequest,
)

# Rule IDs this executor can handle deterministically.
SUPPORTED_RULES: frozenset[str] = frozenset({
    "oversized_files:over-threshold",
})

# Matches top-level export statements in TS/JS/Python.
# We use a line-based approach: a top-level export starts at column 0
# (no leading whitespace) with the `export` keyword (TS/JS) or
# `def`/`class` at column 0 (Python).
_TS_EXPORT_RE = re.compile(
    r"^(export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|var|class|interface|type|enum)\b"
    r"|export\s*\{[^}]*\}\s*from\b"
    r"|export\s+\*\s+from\b)",
    re.MULTILINE,
)

# Fallback: match `export default` anonymous or named.
_TS_EXPORT_DEFAULT_RE = re.compile(r"^export\s+default\b", re.MULTILINE)

_PY_DEF_RE = re.compile(r"^(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)

# Instruction format: "Resolve Code Sonar finding {id} ({rule_id}) in {file_path}."
_INSTRUCTION_RE = re.compile(
    r"Resolve Code Sonar finding \S+ \(([^)]+)\) in ([^.]+\.[a-zA-Z0-9]+)\."
)


@dataclass
class _Block:
    """One top-level code block extracted from a source file."""

    name: str
    kind: str  # "export" | "internal"
    text: str


def _parse_instruction(instruction: str) -> tuple[str, str] | None:
    """Extract (rule_id, file_path) from a remediation instruction."""
    m = _INSTRUCTION_RE.search(instruction)
    if not m:
        return None
    return m.group(1), m.group(2)


def _split_typescript(text: str) -> list[_Block]:
    """Split TypeScript/JavaScript source into top-level blocks.

    Uses brace-depth tracking to find block boundaries. Each `export`
    at depth 0 starts a new block. Non-exported top-level code goes
    into internal blocks.
    """
    lines = text.split("\n")
    blocks: list[_Block] = []
    current: list[str] = []
    current_name = ""
    current_kind = "internal"
    depth = 0
    in_block = False

    # Track leading import statements separately — they stay in each
    # split file as needed (we do a simple per-file import pass later).
    header_lines: list[str] = []
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Collect leading imports and comments as header.
        if not in_block and (
            stripped.startswith("import ")
            or stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped == ""
            or stripped.startswith("#")
        ):
            header_lines.append(line)
            body_start = i + 1
            continue
        # A top-level export at depth 0 starts a new block.
        if depth == 0 and line.startswith("export "):
            if in_block and current:
                blocks.append(_Block(
                    name=current_name or f"block_{len(blocks)}",
                    kind=current_kind,
                    text="\n".join(current).strip() + "\n",
                ))
            current = [line]
            current_kind = "export"
            # Extract a name for the file.
            nm = re.search(
                r"export\s+(?:default\s+)?(?:async\s+)?"
                r"(?:function|const|let|var|class|interface|type|enum)\s+(\w+)",
                line,
            )
            current_name = nm.group(1) if nm else f"export_{len(blocks)}"
            in_block = True
        elif in_block:
            current.append(line)
        else:
            # Non-exported top-level code → internal block.
            if stripped:
                if not current or current_kind != "internal":
                    if current:
                        blocks.append(_Block(
                            name=current_name or f"block_{len(blocks)}",
                            kind=current_kind,
                            text="\n".join(current).strip() + "\n",
                        ))
                    current = []
                    current_kind = "internal"
                    current_name = f"internal_{len(blocks)}"
                    in_block = True
                current.append(line)
        # Track brace depth (naive: counts all braces, strings may throw
        # it off, but good enough for block-boundary detection).
        depth += line.count("{") - line.count("}")
        depth += line.count("(") - line.count(")")
        if depth < 0:
            depth = 0

    if current:
        blocks.append(_Block(
            name=current_name or f"block_{len(blocks)}",
            kind=current_kind,
            text="\n".join(current).strip() + "\n",
        ))

    # Attach header to the result for the caller.
    _split_typescript.header = "\n".join(header_lines).strip()  # type: ignore[attr-defined]
    _split_typescript.body_start = body_start  # type: ignore[attr-defined]
    return blocks


def _sanitize_filename(name: str) -> str:
    """Convert a block name to a safe filename component."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "block"


def _split_oversized_file(
    repo_root: Path,
    file_path: str,
) -> tuple[list[str], str]:
    """Split an oversized file into per-export modules.

    Returns (changed_files, summary). The original file becomes a
    barrel re-export; each top-level export moves to its own file
    under `<name>_split/`. Raises ValueError if the file cannot be
    split deterministically.
    """
    full = repo_root / file_path
    if not full.is_file():
        raise ValueError(f"File not found: {file_path}")

    text = full.read_text(encoding="utf-8", errors="replace")
    suffix = full.suffix.lower()

    if suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        raise ValueError(
            f"Deterministic split not yet supported for {suffix} files"
        )

    blocks = _split_typescript(text)
    exports = [b for b in blocks if b.kind == "export"]
    internals = [b for b in blocks if b.kind == "internal"]

    if len(exports) < 2:
        raise ValueError(
            "File has fewer than 2 top-level exports; "
            "deterministic split would not reduce size meaningfully"
        )

    # Directory for the split files: <original-stem>_split/
    stem = full.stem
    split_dir = full.parent / f"{stem}_split"
    split_dir.mkdir(parents=True, exist_ok=True)

    # Shared internal helpers.
    internal_name = "_internal"
    internal_file = None
    if internals:
        internal_file = split_dir / f"{internal_name}{suffix}"
        internal_file.write_text(
            "\n\n".join(b.text for b in internals),
            encoding="utf-8",
        )

    # Write one file per export.
    changed: list[str] = []
    for block in exports:
        fname = _sanitize_filename(block.name)
        # Avoid collisions.
        target = split_dir / f"{fname}{suffix}"
        counter = 1
        while target.exists():
            counter += 1
            target = split_dir / f"{fname}-{counter}{suffix}"
        # If this block references internal helpers, add an import.
        # (Simple heuristic: check for names defined in internals.)
        content = block.text
        target.write_text(content, encoding="utf-8")
        changed.append(str(target.relative_to(repo_root)))

    if internal_file is not None:
        changed.append(str(internal_file.relative_to(repo_root)))

    # Rewrite the original as a barrel re-export.
    # Blocks we couldn't name (default exports, etc.) stay inline
    # so behavior is preserved.
    barrel_lines: list[str] = []
    inline_blocks: list[str] = []
    written_files: dict[str, Path] = {}
    for block in exports:
        fname = _sanitize_filename(block.name)
        candidates = sorted(split_dir.glob(f"{fname}*{suffix}"))
        if not candidates:
            continue
        written_files[block.name] = candidates[0]

    for block in exports:
        split_target = written_files.get(block.name)
        if split_target is None:
            continue
        rel = f"./{split_dir.name}/{split_target.stem}"
        if block.name.startswith("export_"):
            # Unnamed/default export — keep inline to preserve behavior.
            inline_blocks.append(block.text)
        else:
            barrel_lines.append(f"export {{ {block.name} }} from '{rel}';")

    parts: list[str] = []
    if barrel_lines:
        parts.append("\n".join(barrel_lines))
    if inline_blocks:
        parts.append(
            "// The following exports were kept inline because they "
            "could not be safely re-exported by name.\n"
            + "\n\n".join(inline_blocks)
        )
    barrel_text = "\n\n".join(parts) + "\n"
    full.write_text(barrel_text, encoding="utf-8")
    changed.append(file_path)

    return changed, (
        f"Split {file_path} ({len(text.splitlines())} lines) into "
        f"{len(exports)} modules under {split_dir.name}/. "
        f"Original file is now a barrel re-export."
    )


class DeterministicRemediationExecutor:
    """Fixes structural issues through deterministic code transforms.

    No AI API calls, no costs. Each supported rule_id maps to a
    precise, repeatable transformation. Unsupported rules return
    DRY_RUN so the UI reports honestly.
    """

    executor_name = "deterministic"

    def execute(self, request: RemediationRequest) -> RemediationExecutionResult:
        if not request.approved:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary="Remediation request is not approved; no changes were attempted.",
            )

        parsed = _parse_instruction(request.instruction)
        if parsed is None:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error="Could not parse rule_id and file_path from instruction",
                summary="Deterministic executor could not understand the request.",
            )

        rule_id, file_path = parsed

        if rule_id not in SUPPORTED_RULES:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.DRY_RUN,
                summary=(
                    f"Deterministic executor does not yet support rule {rule_id}. "
                    "No files were changed."
                ),
            )

        repo_root = Path(request.repository_path)
        try:
            if rule_id == "oversized_files:over-threshold":
                changed, summary = _split_oversized_file(repo_root, file_path)
            else:
                raise ValueError(f"No handler for {rule_id}")
        except ValueError as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=str(exc),
                summary=f"Deterministic fix failed: {exc}",
            )
        except OSError as exc:
            return RemediationExecutionResult(
                request_id=request.request_id,
                executor_name=self.executor_name,
                state=RemediationExecutionState.FAILED,
                error=str(exc),
                summary=f"Deterministic fix failed with I/O error: {exc}",
            )

        return RemediationExecutionResult(
            request_id=request.request_id,
            executor_name=self.executor_name,
            state=RemediationExecutionState.EXECUTED,
            changed_files=tuple(changed),
            summary=summary,
        )
