# Code Sonar

**Credit report for your codebase.**

Code Sonar analyzes your repository and provides a simple 0-100 score measuring technical debt across:
- Complexity
- Staleness
- Security
- Duplication
- Testing

## Project Status

**Current:** MVP development in progress
**Phase:** Phase 2 — Architecture & Implementation
**Progress:** ~10%

See [`DEVELOPMENT_STATUS.md`](./DEVELOPMENT_STATUS.md) for detailed sprint status.

## Repository Structure

```
code-sonar/
├── backend/          # Python + FastAPI backend
│   ├── app/
│   │   ├── analyzers/    # Code analysis engines
│   │   ├── api/          # API endpoints
│   │   ├── models/       # Data models
│   │   ├── scoring/      # Scoring engine
│   │   └── main.py       # FastAPI app
│   ├── tests/        # pytest test suite
│   └── pyproject.toml
├── frontend/         # React + TypeScript dashboard
│   ├── src/
│   └── package.json
├── fixtures/         # Test fixtures and sample repos
├── specs/            # Product specifications
└── strategy/         # Market analysis and positioning
```

## Quick Start (Development)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Backend runs at: http://localhost:8000

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: http://localhost:3000

## Architecture

- **Backend:** Python 3.11+, FastAPI, SQLite (MVP)
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Analysis:** Deterministic static analysis (radon, AST parsing, git mining)
- **Scoring:** Pure deterministic calculation (NO LLM)

## Testing

```bash
# Backend
cd backend
pytest

# Frontend
cd frontend
npm test
```

## Documentation

- [Technical Specification](./specs/technical-spec-v1.md)
- [UI/UX Specification](./specs/credit-report-ui-ux.md)
- [Market Analysis](./strategy/market-analysis.md)
- [Development Status](./DEVELOPMENT_STATUS.md)

## License

TBD
