# Code Sonar — Security Documentation

**Last Updated:** 2026-08-22  
**Version:** 1.0 (MVP)  
**Scope:** Repository ingestion and analysis security

---

## 1. Threat Model

### 1.1 Attack Surface

Code Sonar processes untrusted input from multiple sources:
- User-provided repository paths (API, CLI)
- Cloned repository contents (webhooks, manual scans)
- File paths within repositories
- Webhook payloads from git providers

### 1.2 Assets to Protect

| Asset | Risk | Impact |
|-------|------|--------|
| **Host filesystem** | Path traversal, arbitrary file access | Critical |
| **Application availability** | DoS via resource exhaustion | High |
| **User secrets in repositories** | Exposure in findings/logs | Critical |
| **Worker processes** | Command injection, code execution | Critical |
| **API infrastructure** | DoS, abuse, quota exhaustion | High |

### 1.3 Trust Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                    UNTRUSTED ZONE                       │
│  • User-provided paths                                  │
│  • Webhook payloads                                     │
│  • Repository contents (code, configs, symlinks)        │
│  • File paths in findings                               │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼ VALIDATION LAYER ◄─ This document
┌─────────────────────────────────────────────────────────┐
│                    TRUSTED ZONE                         │
│  • Validated paths                                      │
│  • Sanitized findings                                   │
│  • Bounded operations                                   │
└─────────────────────────────────────────────────────────┘
```

### 1.4 Assumptions

- Workers run in isolated containers/VMs (future)
- For MVP: Workers run on same host, file system isolation via path validation
- Database credentials are securely stored (environment variables, secrets manager)
- GitHub/GitLab webhooks use HMAC signature verification
- Users cannot execute arbitrary code on workers (for MVP)

---

## 2. Identified Risks

### 2.1 Path Traversal

**Risk Level:** 🔴 **CRITICAL**

**Attack Vector:**
```python
# Malicious input
POST /api/scan
{
  "repo_path": "../../../etc/passwd"
}

# Or via symlink
repo/
  legit.py
  evil -> /etc/passwd  # Symlink to sensitive file
```

**Impact:**
- Read arbitrary files on host filesystem
- Access secrets, credentials, SSH keys
- Read other users' repositories

**Mitigation:**
1. ✅ **Validate and resolve all paths** before use
2. ✅ **Enforce repository root boundary** — reject paths outside designated scan directory
3. ✅ **Do not follow symlinks** by default (use `Path.resolve(strict=True)`)
4. ✅ **Allowlist approach** — only permit paths within `/tmp/code-sonar-scans/{job_id}/`

**Implementation:** See `security/validators.py::validate_repo_path()`

---

### 2.2 File Size Limits

**Risk Level:** 🟡 **HIGH**

**Attack Vector:**
```python
# Malicious repository with infinite file
repo/
  evil.log -> /dev/zero  # Infinite file
  giant.bin              # 10 GB binary
```

**Impact:**
- Memory exhaustion (OOM kill)
- Disk exhaustion (fill worker storage)
- Worker timeout/stall

**Mitigation:**
1. ✅ **Max file size:** 10 MB per file (configurable)
2. ✅ **Skip binary files** automatically
3. ✅ **Total scan size limit:** 500 MB per repository
4. ✅ **Timeout per file:** 5 seconds max read time

**Recommended Defaults:**
```python
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024      # 10 MB
MAX_REPO_SIZE_BYTES = 500 * 1024 * 1024     # 500 MB
MAX_FILE_READ_TIMEOUT = 5                   # seconds
```

**Implementation:** See `security/validators.py::is_safe_to_read()`

---

### 2.3 Denial of Service (File Count)

**Risk Level:** 🟡 **HIGH**

**Attack Vector:**
```bash
# Malicious repository with millions of files
repo/
  file_000001.py
  file_000002.py
  ...
  file_999999.py  # 1 million tiny files
```

**Impact:**
- Worker exhaustion (CPU, memory)
- Excessive analysis time
- Queue backlog

**Mitigation:**
1. ✅ **Max files scanned:** 10,000 files per repository
2. ✅ **Max scan time:** 5 minutes per repository
3. ✅ **Fail fast** — abort scan if limits exceeded
4. ✅ **File filtering** — skip node_modules, .git, build artifacts

**Recommended Defaults:**
```python
MAX_FILES_PER_SCAN = 10_000
MAX_SCAN_TIME_SECONDS = 300  # 5 minutes
```

**Implementation:** Repository scanner must count files before processing

---

### 2.4 Subprocess Execution

**Risk Level:** 🟠 **MEDIUM** (for MVP)

**Current Status:**
- MVP analyzers do NOT spawn subprocesses
- Pure Python AST parsing and file analysis
- Git operations use `subprocess` (limited attack surface)

**Future Risk (when adding linters):**
If integrating external tools (ESLint, radon, etc.), risk of command injection:

```python
# UNSAFE (do not do this)
subprocess.run(f"eslint {user_provided_path}")  # ❌ Command injection

# SAFE
subprocess.run(["eslint", validated_path], timeout=30)  # ✅ Array syntax
```

**Mitigation:**
1. ✅ **Always use array syntax** for `subprocess.run()`
2. ✅ **Never interpolate user input** into shell strings
3. ✅ **Timeout all subprocess calls** (30 seconds max)
4. ✅ **Run with minimal permissions** (non-root user)

**Implementation:** Use `security/subprocess.py::safe_subprocess_run()` wrapper

---

### 2.5 Secret Exposure in Findings

**Risk Level:** 🟠 **MEDIUM**

**Attack Vector:**
```python
# Repository with secrets in code
config.py:
  API_KEY = "sk_live_abc123xyz789"  # ← Hardcoded secret
  
# Analyzer creates finding with evidence field:
{
  "file_path": "config.py",
  "evidence": "API_KEY = 'sk_live_abc123xyz789'",  # ← Secret in database!
  ...
}
```

**Impact:**
- Secrets stored in database (findings table)
- Secrets visible in dashboard/API responses
- Accidental exposure to unauthorized users

**Mitigation:**
1. ⚠️ **Redact high-entropy strings** in evidence field (optional for MVP)
2. ✅ **Truncate evidence** to 500 characters max
3. ✅ **Never log evidence** in application logs
4. 🔮 **Future:** Integrate secret detection (truffleHog, detect-secrets)

**Recommended Approach (MVP):**
```python
# Simple high-entropy detection
import re

def redact_secrets(text: str) -> str:
    """Redact potential secrets (high-entropy strings > 20 chars)."""
    # Regex: continuous alphanumeric strings > 20 chars
    pattern = r'\b[A-Za-z0-9_\-]{20,}\b'
    return re.sub(pattern, '[REDACTED]', text)
```

**Implementation:** See `security/validators.py::redact_secrets()` (optional)

---

### 2.6 Binary File Parsing

**Risk Level:** 🟢 **LOW**

**Attack Vector:**
```python
# Malformed binary file causes parser crash
repo/
  malicious.wasm  # Crafted binary to trigger vulnerability
```

**Impact:**
- Worker crash
- Potential memory corruption (if using unsafe C extensions)

**Mitigation:**
1. ✅ **Detect and skip binary files** automatically
2. ✅ **Use safe binary detection** (file header magic bytes)
3. ✅ **Never parse binary formats** in MVP (only plain text source code)

**Implementation:**
```python
BINARY_EXTENSIONS = {'.exe', '.dll', '.so', '.dylib', '.bin', '.wasm', '.jpg', '.png', '.pdf'}

def is_binary_file(path: Path) -> bool:
    """Detect binary files by extension and content."""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    
    # Check for NULL bytes in first 8KB
    try:
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            return b'\x00' in chunk
    except Exception:
        return True  # Assume binary if unreadable
```

---

### 2.7 Symlink Following

**Risk Level:** 🟡 **HIGH**

**Attack Vector:**
```bash
# Malicious repository with symlinks
repo/
  legit.py
  evil -> /etc/passwd          # Absolute symlink
  tricky -> ../../other_repo/  # Relative symlink outside repo
```

**Impact:**
- Read files outside repository boundary
- Infinite loops (circular symlinks)
- DoS (symlink to large external directories)

**Mitigation:**
1. ✅ **Do not follow symlinks** during file walk
2. ✅ **Validate resolved paths** stay within repository root
3. ✅ **Skip symlinks** in file enumeration

**Implementation:**
```python
# Safe file walk (no symlink following)
for item in repo_path.rglob('*'):
    if item.is_symlink():
        continue  # Skip all symlinks
    if item.is_file():
        # Process file
```

---

## 3. Safe Defaults for MVP

### 3.1 Configuration Constants

```python
# File limits
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024      # 10 MB
MAX_REPO_SIZE_BYTES = 500 * 1024 * 1024     # 500 MB
MAX_FILES_PER_SCAN = 10_000

# Time limits
MAX_SCAN_TIME_SECONDS = 300                 # 5 minutes
MAX_FILE_READ_TIMEOUT = 5                   # 5 seconds

# Evidence truncation
MAX_EVIDENCE_LENGTH = 500                   # characters

# Repository path constraints
SCAN_ROOT_DIR = Path("/tmp/code-sonar-scans")  # All scans must be within this
```

### 3.2 File Exclusions

**Always skip these patterns:**
```python
EXCLUDED_DIRS = {
    'node_modules', '.git', '.svn', '.hg',
    '__pycache__', '.pytest_cache', '.mypy_cache',
    'venv', 'env', '.venv', 'virtualenv',
    'dist', 'build', 'target', 'out',
    '.next', '.nuxt', '.output'
}

EXCLUDED_EXTENSIONS = {
    # Binaries
    '.exe', '.dll', '.so', '.dylib', '.bin', '.wasm',
    # Media
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
    '.mp4', '.mov', '.avi', '.mkv',
    '.mp3', '.wav', '.flac',
    # Archives
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    # Documents
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    # Other
    '.lock', '.log', '.tmp', '.swp', '.bak'
}
```

---

## 4. Implementation Guidelines

### 4.1 Path Validation Flow

```python
from pathlib import Path
from security.validators import validate_repo_path, is_safe_to_read

def scan_repository(repo_path_input: str) -> list[Finding]:
    """Scan repository with security checks."""
    
    # Step 1: Validate repository path
    try:
        repo_path = validate_repo_path(repo_path_input)
    except ValueError as e:
        raise HTTPException(400, f"Invalid repository path: {e}")
    
    # Step 2: Walk files safely
    findings = []
    file_count = 0
    total_size = 0
    
    for file_path in repo_path.rglob('*'):
        # Security checks
        if file_path.is_symlink():
            continue  # Skip symlinks
        
        if not file_path.is_file():
            continue
        
        if not is_safe_to_read(file_path, repo_path):
            continue  # Skip unsafe files
        
        # Enforce limits
        file_count += 1
        if file_count > MAX_FILES_PER_SCAN:
            raise ValueError(f"Repository exceeds file limit ({MAX_FILES_PER_SCAN})")
        
        file_size = file_path.stat().st_size
        total_size += file_size
        if total_size > MAX_REPO_SIZE_BYTES:
            raise ValueError(f"Repository exceeds size limit ({MAX_REPO_SIZE_BYTES} bytes)")
        
        # Analyze file
        findings.extend(analyze_file(file_path))
    
    return findings
```

### 4.2 Evidence Sanitization

```python
from security.validators import redact_secrets

def create_finding(..., evidence: str) -> Finding:
    """Create finding with sanitized evidence."""
    
    # Truncate evidence
    if len(evidence) > MAX_EVIDENCE_LENGTH:
        evidence = evidence[:MAX_EVIDENCE_LENGTH] + "..."
    
    # Optional: Redact secrets
    evidence = redact_secrets(evidence)
    
    return Finding(
        ...,
        evidence=evidence,
        ...
    )
```

---

## 5. Testing Requirements

### 5.1 Security Test Cases

All security validators MUST have tests:

```python
# tests/security/test_validators.py

def test_path_traversal_blocked():
    """Verify path traversal attacks are blocked."""
    assert_raises(ValueError, validate_repo_path, "../../../etc/passwd")
    assert_raises(ValueError, validate_repo_path, "/etc/passwd")

def test_symlinks_rejected():
    """Verify symlinks are not followed."""
    # Create test repo with symlink
    # Verify symlink is skipped

def test_large_files_rejected():
    """Verify oversized files are skipped."""
    # Create 20 MB file
    # Verify is_safe_to_read() returns False

def test_binary_files_detected():
    """Verify binary files are detected and skipped."""
    # Test various binary formats
    
def test_file_count_limit():
    """Verify scan aborts if file count exceeded."""
    # Create repo with 15,000 files
    # Verify scan raises error

def test_secret_redaction():
    """Verify high-entropy strings are redacted."""
    evidence = "API_KEY=sk_live_abc123xyz789secret"
    redacted = redact_secrets(evidence)
    assert "sk_live_abc123xyz789secret" not in redacted
```

---

## 6. Deployment Considerations

### 6.1 Worker Isolation (Future)

For production deployment, workers should run in isolated environments:
- **Containers:** Docker with read-only filesystem, no network access
- **VMs:** Separate VM per worker, destroy after scan
- **Sandbox:** Use gVisor, Firecracker, or similar sandboxing

### 6.2 Monitoring & Alerts

Monitor for security-related events:
- Path validation failures (potential attacks)
- File size limit exceeded
- Scan time exceeded
- Subprocess failures
- Abnormal resource usage

---

## 7. Security Checklist (MVP Launch)

**Before going live, verify:**

- [ ] Path validation enforced on all repository inputs
- [ ] Symlinks are not followed
- [ ] File size limits implemented
- [ ] File count limits implemented
- [ ] Scan timeout enforced
- [ ] Binary files automatically skipped
- [ ] Evidence truncated to 500 chars
- [ ] No secrets in application logs
- [ ] Subprocess calls use array syntax (when added)
- [ ] Security tests pass (100% coverage)
- [ ] Rate limiting on API endpoints
- [ ] HMAC signature verification for webhooks

---

## 8. Vulnerability Disclosure

**Report security issues to:** security@codesonar.dev

**Do not** open public GitHub issues for security vulnerabilities.

---

## 9. References

- [OWASP Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal)
- [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html)
- [CWE-78: OS Command Injection](https://cwe.mitre.org/data/definitions/78.html)
- [Python subprocess security](https://docs.python.org/3/library/subprocess.html#security-considerations)

---

*Last updated: 2026-08-22 by CISO Security Review*
