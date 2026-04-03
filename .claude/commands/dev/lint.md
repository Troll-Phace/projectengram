---
description: Run code formatting and linting
allowed-tools: Bash(black *), Bash(isort *), Bash(eslint *), Bash(rustfmt *), Bash(tsc *), Bash(pnpm *)
---

# Lint & Format

## Instructions

1. Python: `black sidecar/ --check && isort sidecar/ --check`
2. TypeScript: `pnpm eslint src/ --ext .ts,.tsx` and `pnpm tsc --noEmit`
3. Rust: `cd src-tauri && cargo fmt -- --check`
4. If issues found, ask user if they want to auto-fix
5. Auto-fix: `black sidecar/ && isort sidecar/ && pnpm eslint --fix && cd src-tauri && cargo fmt`
