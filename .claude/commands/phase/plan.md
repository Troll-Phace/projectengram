---
description: Plan the current development phase
allowed-tools: Read, Bash(git status), Bash(git log *)
---

# Plan Phase

Review the current development phase and create an implementation plan.

## Instructions

1. Read `docs/INSTRUCTIONS.md` to identify the current phase
2. Read `docs/ARCHITECTURE.md` sections referenced by the phase
3. If the phase involves UI, read `docs/DESIGN_SYSTEM.md` and reference the wireframe
4. List all tasks in the phase
5. For each task, identify:
   - Which subagent handles it
   - What files will be created/modified
   - Dependencies on other tasks
   - Specific architecture sections to reference
6. Present the plan for approval

## Output Format

### Phase [N]: [Title]
**Mode**: [Subagent Orchestration / Agent Team]

| Task | Assignee | Files | Dependencies | Reference |
|------|----------|-------|-------------|-----------|
| ... | ... | ... | ... | ... |

**Estimated delegation prompts**: [count]
**Risk areas**: [any concerns]
