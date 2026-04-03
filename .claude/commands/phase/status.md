---
description: Show current project status
allowed-tools: Read, Bash(git log *), Bash(pytest *), Bash(vitest *), Bash(wc *), Bash(find *)
---

# Project Status

## Instructions

1. Read INSTRUCTIONS.md and determine current phase
2. Check git log for recent commits
3. Run test suites and report results
4. Count lines of code:
   - Python: `find sidecar -name "*.py" | xargs wc -l`
   - TypeScript: `find src -name "*.tsx" -o -name "*.ts" | xargs wc -l`
   - Rust: `find src-tauri -name "*.rs" | xargs wc -l`
5. Check for any TODO/FIXME comments
6. Report overall status

## Output Format

### Engram — Project Status Report
- **Current Phase**: [N] — [Title]
- **Completed Phases**: [list]
- **Backend Tests**: [X passing, Y failing, Z total]
- **Frontend Tests**: [X passing, Y failing, Z total]
- **Lines of Code**: Python [count] | TypeScript [count] | Rust [count]
- **Open TODOs**: [count and locations]
- **Last Commit**: [hash] — [message] — [date]
