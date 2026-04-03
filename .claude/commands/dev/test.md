---
description: Run tests with reporting
allowed-tools: Bash(pytest *), Bash(vitest *), Bash(python *), Bash(pnpm *)
---

# Run Tests

## Instructions

1. Run backend tests: `cd sidecar && pytest tests/ -v --tb=short`
2. Run frontend tests: `pnpm vitest run`
3. If specific module requested, run targeted tests only
4. Report results with pass/fail counts
5. For failures, show the traceback and suggest fixes
