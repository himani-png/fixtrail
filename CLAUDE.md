# Notes for AI coding assistants

- Read [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) first: working rules, phases, and progress. The developer is new
  to Python, MCP, and AWS, so explain each step in plain language.
- Read [docs/DESIGN_REVIEW.md](docs/DESIGN_REVIEW.md) before changing trust features: honest labels, the
  append-only hash chain, and fingerprints in every email. Don't remove or weaken them.
- Run the server: `.venv\Scripts\python -m uvicorn app.main:app --reload` (always use the project's `.venv`).
- Run tests: `.venv\Scripts\python -m pytest -q`. Keep them passing.
- Never commit secrets (`.env` is git-ignored). Ask before creating AWS resources or spending money.
- Log confusing or broken tools in [docs/FRICTION_LOG.md](docs/FRICTION_LOG.md).
- `mcp` is pinned below 2.2 because `strands-agents` requires it (friction log entry 7).
