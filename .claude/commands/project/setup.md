---
description: Initialize project from scratch
allowed-tools: Read, Write, Bash(pip install *), Bash(pnpm *), Bash(cargo *), Bash(mkdir *), Bash(git *), Bash(python *), Bash(node *)
---

# Project Setup

## Instructions

1. Create the project directory structure per ARCHITECTURE.md
2. Initialize Tauri v2 project with React + TypeScript template
3. Install frontend dependencies: `pnpm install`
4. Set up Python sidecar:
   a. Create sidecar/ directory structure
   b. Create pyproject.toml with all dependencies
   c. Create virtual environment: `python -m venv sidecar/.venv`
   d. Install: `pip install -e sidecar/`
5. Initialize SQLite database with migration 0001_init.sql
6. Create .gitignore (node_modules, target, __pycache__, .venv, *.db, dist)
7. Initialize git repository
8. Verify setup:
   a. `cd sidecar && uvicorn main:app --port 9721` starts successfully
   b. `pnpm tauri dev` builds the frontend
   c. `/api/health` returns OK
