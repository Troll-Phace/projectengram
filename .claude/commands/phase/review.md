---
description: Review completed phase work
allowed-tools: Read, Bash(pytest *), Bash(vitest *), Bash(black --check *), Bash(isort --check *), Bash(tsc *), Bash(git diff *)
---

# Review Phase

Comprehensive review of the completed phase.

## Instructions

1. Read all files created/modified in this phase
2. Run the full test suite (backend + frontend)
3. Check code formatting compliance
4. Verify against INSTRUCTIONS.md success criteria
5. Check for:
   - Type hint coverage (Python) / TypeScript strict mode compliance
   - Docstring/JSDoc presence on public functions
   - No hardcoded values that should be configurable
   - Correct use of design system colors/fonts (UI phases)
   - Proper error handling
   - PRAGMA foreign_keys = ON enforced (DB phases)
   - Async correctness (no blocking I/O in async context)
6. Delegate to `code-reviewer` for detailed review if needed
7. Report pass/fail with specific issues

## Output Format

### Phase [N] Review: [PASS/FAIL]

**Backend Tests**: [X/Y passing]
**Frontend Tests**: [X/Y passing]
**Formatting**: [pass/fail]
**Type Check**: [pass/fail]
**Success Criteria**: [checklist with pass/fail]
**Issues Found**: [list or "none"]
**Action Required**: [next steps or "ready for next phase"]
