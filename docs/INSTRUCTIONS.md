# Development Instructions — Engram

> Personal coding project manager & neural graph visualizer.
> 28 development phases. Each phase is a tight, focused unit of work — typically 1-2 hours.
> **You are an orchestrator. Delegate every implementation task to the appropriate subagent.**

---

## Overview

Engram is a macOS desktop app built with Tauri v2 + React + Python sidecar. This document breaks the full build into 28 phases. Phases are sequential — complete one before starting the next. Every task specifies which subagent handles it.

### Subagent Roles

| Subagent | Responsibilities |
|----------|-----------------|
| `rust-shell-dev` | Tauri v2 Rust layer: IPC commands, sidecar lifecycle, window config, native dialogs, system tray |
| `frontend-dev` | React + TypeScript: components, Zustand stores, TanStack Query hooks, API integration |
| `graph-dev` | React Flow: custom nodes, custom edges, force layout, canvas interactions, particle animations |
| `ui-animation-dev` | Motion (framer-motion): spring animations, transitions, ambient mode, visual polish, CSS/SVG filters |
| `python-backend-dev` | FastAPI sidecar: API routes, scanner pipeline, WebSocket, file watcher, concurrency |
| `db-dev` | SQLite + SQLModel: schema, migrations, queries, engine config, data access layer |
| `test-engineer` | Tests across all layers: pytest (backend), vitest (frontend), integration tests |
| `code-reviewer` | Code review, design system compliance, quality gates between phases |

### Architecture Reference Requirement

**Every subagent MUST read the relevant sections of `docs/ARCHITECTURE.md` before implementing.** This is non-negotiable. The architecture document contains data models, API contracts, visual encoding specs, and performance budgets that inform every task.

### Design System Requirement

**For any UI work**, the subagent MUST also read `docs/DESIGN_SYSTEM.md` and reference the corresponding wireframe SVG. The design system defines colors, typography, spacing, elevation, and motion standards.

---

## Target Outcomes

When all phases are complete, Engram will:

- Auto-scan a configurable projects root directory and detect language, framework, git status, LOC, and README for each project
- Render all projects as a neural network graph with glowing nodes, weighted edges, and animated particles
- Map every visual property to project data (color=language, size=complexity, glow=activity, particles=recency)
- Display a rich detail panel on node click with live git data, quick actions, and connection info
- Support manual edges (draw connections), tags, and clusters (with collapse)
- Search and filter via ⌘K spotlight with smooth node fade animations
- Watch for file system changes and incrementally update the graph in real-time via WebSocket
- Bundle as a signed macOS .dmg with auto-update via GitHub Releases
- Include an ambient mode that makes the graph drift and pulse when idle

---

## Phase 1: Tauri v2 Project Initialization

### Objective
Initialize the Tauri v2 project with React + TypeScript frontend template.

### Prerequisites
- Node.js 18+, pnpm, Rust toolchain, Tauri CLI v2

### Reference Documents
- ARCHITECTURE.md §2 (System Architecture)

### Tasks

#### 1.1 Create Tauri v2 Project
**Delegate to**: `rust-shell-dev`

Initialize Tauri v2 with React + TypeScript template. Configure `tauri.conf.json`: app name "Engram", frameless window with custom titlebar, default 1200x800, min 800x600. Set up `src-tauri/` directory.

#### 1.2 Install Frontend Dependencies
**Delegate to**: `frontend-dev`

Install: React 19, TypeScript, Vite, Tailwind CSS, Motion (framer-motion), Zustand, TanStack Query, React Flow. Set up `tsconfig.json`, `tailwind.config.ts`, `vite.config.ts`. Create placeholder `App.tsx`.

### Success Criteria
- [ ] `pnpm tauri dev` launches the app with a React frontend
- [ ] Tailwind CSS processes classes correctly
- [ ] All dependencies install without errors
- [ ] Frameless window renders with correct dimensions

---

## Phase 2: Python Sidecar Skeleton

### Objective
Set up the Python sidecar directory structure and a minimal FastAPI server.

### Prerequisites
- Phase 1 complete
- Python 3.12+

### Reference Documents
- ARCHITECTURE.md §4.1 (Application Structure)

### Tasks

#### 2.1 Sidecar Directory Structure
**Delegate to**: `python-backend-dev`

Create the full `sidecar/` directory structure per ARCHITECTURE.md §4.1. Set up `pyproject.toml` with all dependencies: FastAPI, uvicorn, watchfiles, GitPython, SQLModel, python-ulid, pydantic, aiofiles.

#### 2.2 Minimal FastAPI App
**Delegate to**: `python-backend-dev`

Create `main.py` with FastAPI app, CORS middleware, and a `/api/health` endpoint returning `{"status": "ok", "version": "0.1.0"}`. Verify it starts on port 9721.

#### 2.3 Smoke Test
**Delegate to**: `test-engineer`

Write a smoke test verifying: sidecar starts, `/api/health` returns 200, all imports work. Document the dev workflow.

### Success Criteria
- [ ] `cd sidecar && uvicorn main:app --port 9721` starts successfully
- [ ] `/api/health` returns 200 with correct payload
- [ ] Directory structure matches ARCHITECTURE.md §4.1
- [ ] All Python dependencies install without errors

---

## Phase 3: SQLite Schema & Initial Migration

### Objective
Write the complete database schema as an SQL migration script.

### Prerequisites
- Phase 2 complete

### Reference Documents
- ARCHITECTURE.md §6 (Data Model & SQLite Schema)

### Tasks

#### 3.1 Initial Migration SQL
**Delegate to**: `db-dev`

Create `sidecar/db/migrations/0001_init.sql` with all 8 tables: `projects`, `edges`, `tags`, `project_tags`, `clusters`, `project_clusters`, `node_positions`, `config`. Include all constraints, indexes, foreign keys with `ON DELETE CASCADE`, and default config entries.

#### 3.2 Schema Tests
**Delegate to**: `test-engineer`

Test the schema: all tables created, constraints enforced, cascades work, default config entries present. Use in-memory SQLite.

### Success Criteria
- [ ] `0001_init.sql` creates all 8 tables with correct constraints
- [ ] Foreign keys cascade correctly on delete
- [ ] Default config entries are inserted
- [ ] Schema tests pass with in-memory SQLite

---

## Phase 4: Migration Runner & Database Engine

### Objective
Implement the migration runner and SQLModel engine with proper PRAGMA configuration.

### Prerequisites
- Phase 3 complete

### Reference Documents
- ARCHITECTURE.md §6.5 (Critical SQLite Configuration), §6.6 (Migration System)

### Tasks

#### 4.1 Migration Runner
**Delegate to**: `db-dev`

Create `sidecar/db/migrations/migrator.py`. Reads `PRAGMA user_version`, finds scripts with version > current, executes in transactions, updates `user_version`. Raises clear error on failure. Integrate into FastAPI lifespan.

#### 4.2 Engine & Session
**Delegate to**: `db-dev`

Create `sidecar/db/engine.py` with SQLAlchemy event listener for `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`. Create `sidecar/db/session.py` with FastAPI dependency for session injection.

#### 4.3 Migration Tests
**Delegate to**: `test-engineer`

Test: fresh DB migration, idempotent re-run, version skipping, failed migration rollback.

### Success Criteria
- [ ] Migration runner applies scripts in order and tracks `user_version`
- [ ] `PRAGMA foreign_keys = ON` enforced on every connection
- [ ] `PRAGMA journal_mode = WAL` set on every connection
- [ ] Failed migrations roll back cleanly
- [ ] FastAPI lifespan runs migration on startup

---

## Phase 5: SQLModel ORM Models

### Objective
Create all SQLModel ORM models matching the database schema.

### Prerequisites
- Phase 4 complete

### Reference Documents
- ARCHITECTURE.md §6.2-6.4 (Table Schemas)

### Tasks

#### 5.1 Core Models
**Delegate to**: `db-dev`

Create SQLModel models: `Project`, `Edge`, `Tag`, `ProjectTag`, `Cluster`, `ProjectCluster`, `NodePosition`, `Config`. Proper type annotations, JSON column handling, ULID generation for PKs.

#### 5.2 CRUD Tests
**Delegate to**: `test-engineer`

Test all CRUD operations via SQLModel. Test JSON column read/write. Test ULID generation. Test cascade deletes propagate through ORM.

### Success Criteria
- [ ] All SQLModel models match schema exactly
- [ ] JSON columns serialize/deserialize correctly
- [ ] ULIDs generate as expected
- [ ] ORM cascade deletes work correctly

---

## Phase 6: Projects API

### Objective
Implement the projects REST API — the primary CRUD endpoint.

### Prerequisites
- Phase 5 complete

### Reference Documents
- ARCHITECTURE.md §4.3 (API Endpoints — projects section)

### Tasks

#### 6.1 Projects Router
**Delegate to**: `python-backend-dev`

Implement `sidecar/api/projects.py`: `GET /api/projects` (with status/language/tag filters), `GET /api/projects/{id}`, `POST /api/projects`, `PATCH /api/projects/{id}`, `DELETE /api/projects/{id}` (soft-delete via `deleted_at`).

#### 6.2 Projects API Tests
**Delegate to**: `test-engineer`

Test all endpoints, filtering, soft-delete behavior, validation (required fields, unique path constraint).

### Success Criteria
- [ ] All project CRUD endpoints work correctly
- [ ] Filtering by status, language, and tag works
- [ ] `DELETE` sets `deleted_at` instead of hard-deleting
- [ ] Validation rejects invalid data

---

## Phase 7: Edges, Tags, Clusters & Positions API

### Objective
Implement remaining entity APIs.

### Prerequisites
- Phase 6 complete

### Reference Documents
- ARCHITECTURE.md §4.3 (API Endpoints)

### Tasks

#### 7.1 Edges Router
**Delegate to**: `python-backend-dev`

Full CRUD for manual edges. Auto-edges are read-only (scanner creates them). Validate: source_id ≠ target_id, both projects exist.

#### 7.2 Tags & Clusters Routers
**Delegate to**: `python-backend-dev`

Tag CRUD + assignment to projects. Cluster CRUD + project membership (add/remove). Config get/set endpoints.

#### 7.3 Positions Router
**Delegate to**: `python-backend-dev`

`GET /api/positions`, `PATCH /api/positions/{project_id}`, `POST /api/positions/batch` (efficient batch update for layout persistence).

#### 7.4 API Tests
**Delegate to**: `test-engineer`

Test all endpoints, edge validation, tag/cluster assignment, batch position update.

### Success Criteria
- [ ] All endpoints from ARCHITECTURE.md §4.3 implemented
- [ ] Edge validation prevents self-referential edges
- [ ] Batch position update works efficiently
- [ ] All tests pass

---

## Phase 8: Scanner — Discovery Phase

### Objective
Implement the directory discovery stage of the scanning pipeline.

### Prerequisites
- Phase 7 complete

### Reference Documents
- ARCHITECTURE.md §5.2 (Discovery)

### Tasks

#### 8.1 Discovery Module
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/discovery.py`. Enumerate immediate children of `projects_root`. Diff against DB: categorize into new/missing/existing. Return structured results. Do NOT auto-add new projects — return events for frontend.

#### 8.2 Discovery Tests
**Delegate to**: `test-engineer`

Create fixture directories. Test discovery correctly identifies new, missing, and existing projects. Test hidden directories (`.hidden`) are excluded.

### Success Criteria
- [ ] Discovery correctly diffs disk vs DB
- [ ] New projects flagged but NOT auto-added
- [ ] Missing projects detected (directory removed/renamed)
- [ ] Hidden directories excluded
- [ ] Tests use fixture directories, not real projects

---

## Phase 9: Scanner — Project Type & Framework Detection

### Objective
Detect project types from manifest files and identify frameworks/tooling.

### Prerequisites
- Phase 8 complete

### Reference Documents
- ARCHITECTURE.md §5.3 Phase 2a-2b (Project Type, Framework Detection)

### Tasks

#### 9.1 Project Type Detector
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/project_type.py`. Detect from manifest files: `package.json`, `Cargo.toml`, `requirements.txt`, `pyproject.toml`, `go.mod`, etc. Parse manifests for name, description, dependency lists.

#### 9.2 Framework Detector
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/frameworks.py`. Detect frameworks from deps and config file presence per ARCHITECTURE.md detection table (React, Tauri, Tailwind, Vite, TypeScript, FastAPI, Docker, etc.).

#### 9.3 Detection Tests
**Delegate to**: `test-engineer`

Create test fixtures for at least 6 project types (React, Rust, Python/FastAPI, Go, multi-lang, non-standard). Test manifest parsing accuracy. Test framework detection coverage.

### Success Criteria
- [ ] All manifest formats from ARCHITECTURE.md are parsed
- [ ] Framework detection covers all signals in the table
- [ ] Dependency lists extracted from each manifest type
- [ ] Test fixtures cover 6+ project types

---

## Phase 10: Scanner — Language Analysis & Size Computation

### Objective
Count lines of code per language and compute directory sizes.

### Prerequisites
- Phase 9 complete

### Reference Documents
- ARCHITECTURE.md §5.3 Phase 2c, 2f (Language Breakdown, Size)

### Tasks

#### 10.1 Language Analyzer
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/languages.py`. Walk file tree excluding vendored dirs (`node_modules`, `.git`, `target`, etc.). Count lines per extension. Compute percentages. Set `primary_language` = highest LOC (excluding config formats).

#### 10.2 Size Computer
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/size.py`. Walk with excluded dirs pruned in-place. Sum file sizes. Count source files by extension.

#### 10.3 Tests
**Delegate to**: `test-engineer`

Test language counting accuracy. Test excluded dirs are properly skipped. Test size computation. Test edge case: empty project directory.

### Success Criteria
- [ ] Language breakdown matches manual inspection of fixtures
- [ ] Vendored dirs (`node_modules`, `.git`, etc.) excluded
- [ ] Primary language correctly determined
- [ ] Size computation accurate

---

## Phase 11: Scanner — Git Analysis

### Objective
Extract git metadata from project repositories.

### Prerequisites
- Phase 10 complete

### Reference Documents
- ARCHITECTURE.md §5.3 Phase 2d (Git Analysis)

### Tasks

#### 11.1 Git Analyzer
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/git_analyzer.py`. Use `asyncio.create_subprocess_exec` for: current branch, dirty status (`git status --porcelain`), last commit (hash + ISO date + message), branch count, remote URL. Handle non-git directories gracefully (all git fields → NULL).

#### 11.2 Git Tests
**Delegate to**: `test-engineer`

Create a temporary git repo in test setup (pytest `tmp_path`). Test all git data points. Test non-git directory handling. Test dirty vs clean detection. Test repo with no commits.

### Success Criteria
- [ ] All 5 git data points extracted correctly
- [ ] Non-git directories handled without errors (fields → NULL)
- [ ] All operations are async (no blocking)
- [ ] Dirty/clean detection is accurate

---

## Phase 12: Scanner — README Extraction

### Objective
Extract project descriptions from README files and manifest fallbacks.

### Prerequisites
- Phase 10 complete

### Reference Documents
- ARCHITECTURE.md §5.3 Phase 2e (README Extraction)

### Tasks

#### 12.1 README Extractor
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/analyzers/readme.py`. Find README.md (case-insensitive), skip H1 title, skip badge lines (`[![`), extract first paragraph of prose, truncate to 300 chars. Fallback: `description` from `package.json` or `Cargo.toml [package]`.

#### 12.2 README Tests
**Delegate to**: `test-engineer`

Test: standard README, badges-only README, no README (fallback to manifest), empty README, README with only a title.

### Success Criteria
- [ ] First meaningful paragraph extracted
- [ ] Badges and title skipped
- [ ] Fallback to manifest description works
- [ ] All edge cases handled

---

## Phase 13: Edge Computation Engine

### Objective
Compute pairwise relationships between projects based on tech stack and dependency overlap.

### Prerequisites
- Phase 12 complete

### Reference Documents
- ARCHITECTURE.md §7 (Edge Computation Engine)

### Tasks

#### 13.1 Edge Computer
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/edge_computer.py`. Compute Jaccard similarity for tech stacks (`auto_tech` edges) and dependency overlap (`auto_dep` edges). Upsert edges above threshold, delete stale edges below threshold. Never touch manual edges.

#### 13.2 Edge Tests
**Delegate to**: `test-engineer`

Test Jaccard with known inputs. Test edge upsert lifecycle (create, update weight, drop below threshold → delete). Test manual edges remain untouched.

### Success Criteria
- [ ] Jaccard similarity computed correctly
- [ ] Edges created above threshold, deleted below
- [ ] Manual edges never modified
- [ ] Edge metadata stores shared deps/tech correctly

---

## Phase 14: Scan Orchestrator

### Objective
Build the orchestrator that coordinates all scan phases with proper concurrency control.

### Prerequisites
- Phase 13 complete

### Reference Documents
- ARCHITECTURE.md §9 (Scan Concurrency Architecture)

### Tasks

#### 14.1 Scan Orchestrator
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/orchestrator.py`. Three-layer concurrency: `asyncio.PriorityQueue` (full=0, manual=5, watcher=10), global `asyncio.Semaphore(4)`, per-project `asyncio.Lock`. Wire up all analyzers in sequence per project. Methods: `trigger_full_scan()`, `trigger_incremental_scan(project_id)`, `trigger_manual_rescan(project_id)`.

#### 14.2 Scan API Endpoints
**Delegate to**: `python-backend-dev`

Implement `sidecar/api/scan.py`: `GET /api/scan/status` (idle/scanning/progress), `POST /api/scan/full`, `POST /api/scan/project/{id}`.

#### 14.3 Orchestrator Tests
**Delegate to**: `test-engineer`

Test priority ordering. Test semaphore limits concurrency. Test per-project lock prevents double-writes. Test full scan runs all phases in order.

### Success Criteria
- [ ] Full scan runs discovery → analyzers → edge computation
- [ ] Concurrency correctly limited to 4 simultaneous projects
- [ ] Per-project locking prevents double-writes
- [ ] Priority queue orders full > manual > watcher scans
- [ ] Scan status endpoint reports accurate progress

---

## Phase 15: File Watcher & Debouncing

### Objective
Monitor the projects root for file changes and trigger incremental scans with debouncing.

### Prerequisites
- Phase 14 complete

### Reference Documents
- ARCHITECTURE.md §8 (File Watching & Incremental Updates)

### Tasks

#### 15.1 File Watcher
**Delegate to**: `python-backend-dev`

Implement `sidecar/scanner/watcher.py`. Use `watchfiles.awatch` for async monitoring. Resolve changed paths to project IDs. Trigger incremental scans via orchestrator.

#### 15.2 Debounce Utility
**Delegate to**: `python-backend-dev`

Implement `sidecar/utils/debounce.py`. Per-project async debouncing (5s) using `asyncio.Task` cancel/reschedule. An `npm install` generating thousands of events → 1 scan.

#### 15.3 Watcher Tests
**Delegate to**: `test-engineer`

Test debounce collapses rapid events. Test new directory detection. Test deleted directory detection.

### Success Criteria
- [ ] File changes trigger incremental scan after 5s debounce
- [ ] Rapid events collapsed into single scan
- [ ] New directories detected
- [ ] Deleted directories detected

---

## Phase 16: WebSocket Event Hub

### Objective
Implement real-time event broadcasting from backend to frontend.

### Prerequisites
- Phase 15 complete

### Reference Documents
- ARCHITECTURE.md §4.4 (WebSocket Event Protocol)

### Tasks

#### 16.1 WebSocket Hub
**Delegate to**: `python-backend-dev`

Implement `sidecar/api/websocket.py`. WebSocket endpoint at `/api/ws`. Connection manager for multi-client broadcasting. Events: `new_project_detected`, `project_updated`, `scan_progress`, `scan_completed`, `project_missing`. Integrate with scanner orchestrator.

#### 16.2 WebSocket Tests
**Delegate to**: `test-engineer`

Test connection lifecycle. Test event serialization matches protocol spec. Test multi-client broadcast.

### Success Criteria
- [ ] WebSocket connects at `/api/ws`
- [ ] All event types broadcast correctly
- [ ] Multi-client broadcasting works
- [ ] Scanner emits events at each stage

---

## Phase 17: Tauri Sidecar Lifecycle

### Objective
Configure Tauri to spawn, health-check, and manage the Python sidecar process.

### Prerequisites
- Phase 16 complete

### Reference Documents
- ARCHITECTURE.md §12.1-12.2 (Rust Layer Responsibilities, Sidecar Spawn)

### Tasks

#### 17.1 Sidecar Lifecycle
**Delegate to**: `rust-shell-dev`

Configure `tauri.conf.json` for external binary sidecar. Implement Rust code: spawn sidecar on app start with `--port 9721`, health-check retry loop (10 retries × 500ms), kill on quit, crash recovery (restart + re-check).

#### 17.2 Window Configuration
**Delegate to**: `rust-shell-dev`

Frameless window with custom titlebar area. Vibrancy/transparency for macOS native feel. Min/max sizes. App icon.

### Success Criteria
- [ ] `pnpm tauri dev` spawns sidecar automatically
- [ ] Health check succeeds within 5 seconds
- [ ] Sidecar killed cleanly on app quit
- [ ] Crash recovery restarts the sidecar

---

## Phase 18: Tauri IPC Commands

### Objective
Implement native IPC commands for quick actions and system integration.

### Prerequisites
- Phase 17 complete

### Reference Documents
- ARCHITECTURE.md §12.3 (IPC Commands)

### Tasks

#### 18.1 IPC Commands
**Delegate to**: `rust-shell-dev`

Implement: `open_in_vscode(path)`, `open_in_terminal(path)`, `open_in_finder(path)`, `pick_folder()` (native folder picker), `get_sidecar_port()`. Register all in Tauri builder.

#### 18.2 IPC Tests
**Delegate to**: `test-engineer`

Verify each command executes correctly. Verify folder picker returns valid path.

### Success Criteria
- [ ] All 5 IPC commands registered and functional
- [ ] VS Code, Terminal, Finder open at correct path
- [ ] Folder picker returns selected path

---

## Phase 19: Frontend Layout & State Management

### Objective
Build the React app shell with layout, Zustand stores, and dark theme.

### Prerequisites
- Phase 18 complete

### Reference Documents
- ARCHITECTURE.md §2 (System Architecture)
- DESIGN_SYSTEM.md (layout, typography, colors)

### Tasks

#### 19.1 App Layout Shell
**Delegate to**: `frontend-dev`

Main layout: full-screen canvas area, collapsible sidebar slot (left, ~280px), detail panel slot (right, ~420px), floating search bar slot (⌘K). Custom titlebar with window controls. Dark theme base via Tailwind.

#### 19.2 Zustand Stores
**Delegate to**: `frontend-dev`

Create stores: `useProjectStore` (projects, selected, filters), `useGraphStore` (viewport, zoom, hovered node), `useUIStore` (sidebar open, panel open, search active, ambient mode). Typed actions and selectors.

### Success Criteria
- [ ] App renders with dark theme and custom titlebar
- [ ] Layout has canvas, sidebar, detail panel, and search slots
- [ ] All Zustand stores typed and functional
- [ ] Sidebar collapses/expands

---

## Phase 20: API Integration Layer

### Objective
Connect the frontend to the sidecar API with TanStack Query and WebSocket.

### Prerequisites
- Phase 19 complete

### Reference Documents
- ARCHITECTURE.md §4.3 (API Endpoints), §4.4 (WebSocket Protocol)

### Tasks

#### 20.1 TanStack Query Hooks
**Delegate to**: `frontend-dev`

Create hooks: `useProjects()`, `useProject(id)`, `useProjectGitDetail(id)`, `useEdges()`, `useTags()`, `useClusters()`, `usePositions()`, `useScanStatus()`. Configure stale times (30s git detail, 5min project list).

#### 20.2 WebSocket Hook
**Delegate to**: `frontend-dev`

Create `useWebSocket()`. Connect to sidecar on mount. Parse events → dispatch to stores. Handle reconnection. Invalidate relevant TanStack Query caches on events.

#### 20.3 Sidebar Project List
**Delegate to**: `frontend-dev`

Populate sidebar: searchable, sortable flat list from `useProjects()`. Each item: name, language dot, status indicator, last commit date.

### Success Criteria
- [ ] All TanStack Query hooks fetch data from sidecar
- [ ] WebSocket connects, receives events, updates stores
- [ ] Cache invalidation on WebSocket events works
- [ ] Sidebar shows project list from API

---

## Phase 21: React Flow Canvas & Neural Nodes

### Objective
Implement the graph canvas with custom neural node components.

### Prerequisites
- Phase 20 complete

### Reference Documents
- ARCHITECTURE.md §3.1 (Visual Encoding), §3.2 (React Flow Integration)
- DESIGN_SYSTEM.md (node anatomy)
- Wireframe: `wireframes/node-anatomy.svg`, `wireframes/main-view.svg`

### Tasks

#### 21.1 Canvas Setup
**Delegate to**: `graph-dev`

Initialize React Flow: dark background, minimap, custom controls, smooth pan/zoom. Connect to Zustand graph store. Set up type registries.

#### 21.2 NeuralNode Component
**Delegate to**: `graph-dev`

Build `NeuralNode.tsx`: outer glow (language color, status intensity), ring (solid=clean, dashed=dirty), core circle (language color, LOC-based size 36-72px), satellite dots (branch count), label below.

#### 21.3 Node Interactions
**Delegate to**: `graph-dev`

Hover (highlight + dim others), click (open detail panel), drag (reposition + pin), right-click (placeholder).

#### 21.4 Node Animations
**Delegate to**: `ui-animation-dev`

Breathing pulse for active nodes (3s, `scale [1.0, 1.02, 1.0]`), hover scale-up (1.08x, spring 300ms), appear animation (`scale [0, 1.1, 1.0]`, spring 400ms), CSS glow.

### Success Criteria
- [ ] Canvas renders with pan/zoom/minimap
- [ ] Nodes encode: language (color), status (glow), complexity (size), git (ring)
- [ ] Hover highlights connected subgraph
- [ ] Active nodes breathe, new nodes animate in
- [ ] Drag repositions and pins via API

---

## Phase 22: Custom Edges & Particle System

### Objective
Build weighted edge rendering with animated particles flowing along connections.

### Prerequisites
- Phase 21 complete

### Reference Documents
- ARCHITECTURE.md §3.2 (Custom Edge), §3.3 (Animation System)
- Wireframe: `wireframes/main-view.svg`

### Tasks

#### 22.1 NeuralEdge Component
**Delegate to**: `graph-dev`

Build `NeuralEdge.tsx`: bezier path, stroke width = `1 + (weight * 4)`, auto edges = `rgba(255,255,255,0.15)`, manual = accent. Directed edges get arrowheads. Optional label at midpoint.

#### 22.2 Particle Animations
**Delegate to**: `graph-dev`

SVG `<circle>` elements animated via `<animateMotion>` along edge paths. Particle count = `Math.ceil(weight / 0.2)`. Speed = git recency function. No particles for stale projects.

#### 22.3 Edge Interactions
**Delegate to**: `graph-dev`

Hover (highlight + weight tooltip), click (select). Edge drawing mode: modifier + drag between nodes to create manual edge.

### Success Criteria
- [ ] Edge width visually represents weight
- [ ] Particles flow with speed proportional to git activity
- [ ] Directed edges show arrowheads
- [ ] Edge drawing creates manual connections

---

## Phase 23: Force-Directed Layout

### Objective
Implement the d3-force layout engine for automatic node positioning.

### Prerequisites
- Phase 22 complete

### Reference Documents
- ARCHITECTURE.md §3.2 (Layout Engine)

### Tasks

#### 23.1 Force Layout Hook
**Delegate to**: `graph-dev`

Implement `useForceLayout.ts`: `forceLink` (strength = `weight * 0.5`), `forceManyBody` (-200), `forceCenter`, `forceCollide` (nodeSize + 20). Exclude pinned nodes. Run on initial load and node add/remove. New nodes placed at viewport center.

#### 23.2 Layout Tests
**Delegate to**: `test-engineer`

Test layout settles within 1s for 30 nodes. Test pinned nodes excluded from simulation. Test new node placement.

### Success Criteria
- [ ] Nodes position naturally based on connections
- [ ] Pinned nodes stay fixed
- [ ] New nodes appear at viewport center, then settle
- [ ] Layout settles within 1 second for 30 nodes

---

## Phase 24: Detail Panel

### Objective
Build the slide-over drawer showing comprehensive project info with live git data.

### Prerequisites
- Phase 21 complete

### Reference Documents
- ARCHITECTURE.md §10 (Detail Panel & Live Data)
- DESIGN_SYSTEM.md (detail panel spec)
- Wireframe: `wireframes/detail-panel.svg`

### Tasks

#### 24.1 Panel Shell & Animation
**Delegate to**: `ui-animation-dev`

Slide-over drawer: 420px, spring animation (damping=25, stiffness=300), frosted glass (`backdrop-filter: blur(20px)`). Dismiss on click-outside/Escape. Crossfade on node switch. Sticky header.

#### 24.2 Header & Overview Sections
**Delegate to**: `frontend-dev`

Header: glow orb, editable name, subtitle (language + status badge), path (click to copy), quick action buttons (VS Code/Terminal/Finder/GitHub via IPC). Overview: description, tech stack pills, language bar chart, stats row, tag chips.

#### 24.3 Git Section
**Delegate to**: `frontend-dev`

Branch + clean/dirty indicator, recent commits (from live `/git-detail` endpoint), branch list, uncommitted changes (when dirty). TanStack Query with 30s TTL.

#### 24.4 Connections & Meta Sections
**Delegate to**: `frontend-dev`

Connections: linked projects with edge type + weight bar, "Draw connection" button, cluster pills. Meta: timestamps, Archive/Rescan/More actions. Empty states as invitations.

### Success Criteria
- [ ] Panel slides in with spring physics, crossfades on node switch
- [ ] Live git data loads on open (commits, branches, status)
- [ ] Quick actions work via Tauri IPC
- [ ] All empty states show helpful prompts
- [ ] Header sticky on scroll

---

## Phase 25: Spotlight Search (⌘K)

### Objective
Implement the spotlight-style search overlay.

### Prerequisites
- Phase 24 complete

### Reference Documents
- ARCHITECTURE.md §11.1 (Search)
- Wireframe: `wireframes/search-filter.svg`

### Tasks

#### 25.1 Search Overlay
**Delegate to**: `frontend-dev`

⌘K triggered modal with search input. Client-side search across names, descriptions, languages, frameworks, tags. Non-matching nodes → `opacity: 0.08`. Matching nodes glow brighter. Dropdown results list — click to navigate.

#### 25.2 Search Animations
**Delegate to**: `ui-animation-dev`

Smooth opacity transitions (spring 200ms) for node fade/highlight. Search result highlight pulse. Canvas pan-to-node with smooth zoom on result click.

### Success Criteria
- [ ] ⌘K opens search overlay
- [ ] Real-time client-side filtering
- [ ] Non-matching nodes fade, matching glow
- [ ] Click result navigates to node

---

## Phase 26: Filter Chips & Clusters

### Objective
Implement persistent filter chips and visual cluster regions.

### Prerequisites
- Phase 25 complete

### Reference Documents
- ARCHITECTURE.md §11.2-11.3 (Filters, Clusters)
- Wireframes: `wireframes/search-filter.svg`, `wireframes/clusters.svg`

### Tasks

#### 26.1 Filter Chips
**Delegate to**: `frontend-dev`

Filter bar: by language, tag, status, recency. Multiple filters combine with AND. Stored in Zustand + persisted to config. Smooth opacity transitions on non-matching nodes.

#### 26.2 Cluster Backgrounds
**Delegate to**: `graph-dev`

Render clusters as soft radial gradient backgrounds behind grouped nodes. Compute bounding box + padding. Support overlapping clusters.

#### 26.3 Cluster Management
**Delegate to**: `frontend-dev`

Create cluster: drag-select → "Create Group" → name + color picker. Collapse/expand (super-node). Add/remove projects from clusters.

### Success Criteria
- [ ] Filters combine with AND, persist across sessions
- [ ] Clusters render as soft gradient backgrounds
- [ ] Cluster collapse merges nodes into super-node
- [ ] Overlapping clusters render correctly

---

## Phase 27: Context Menu & Edge Drawing

### Objective
Implement the right-click context menu and edge drawing flow.

### Prerequisites
- Phase 26 complete

### Reference Documents
- Wireframe: `wireframes/context-edge-drawing.svg`

### Tasks

#### 27.1 Context Menu
**Delegate to**: `frontend-dev`

Right-click node: Open VS Code, Terminal, Change status, Color override, Add to cluster, Draw connection, Rescan, Archive, Remove. Right-click edge: Edit label, Change weight, Delete. Frosted glass style, keyboard navigable.

#### 27.2 Edge Drawing Flow
**Delegate to**: `graph-dev`

Click "Draw connection" → first node highlights → click second → edge creation dialog (label, directed toggle) → API call. Visual feedback during draw mode (highlight source, cursor change, preview line).

### Success Criteria
- [ ] Context menu covers all node/edge actions
- [ ] Edge drawing provides clear visual feedback
- [ ] Edge creation dialog validates input
- [ ] Keyboard navigation works

---

## Phase 28: Settings Panel & First-Run Onboarding

### Objective
Build settings management and the new-user onboarding experience.

### Prerequisites
- Phase 27 complete

### Reference Documents
- ARCHITECTURE.md §6.4 (config table)
- Wireframe: `wireframes/settings.svg`

### Tasks

#### 28.1 Settings Panel
**Delegate to**: `frontend-dev`

Modal with sections: General (projects root with folder picker, scan interval, auto-edge threshold), Appearance (ambient mode delay, show/hide auto-edges), About (version, update check). Wire to `PATCH /api/config/{key}` with optimistic updates.

#### 28.2 First-Run Onboarding
**Delegate to**: `ui-animation-dev`

If no `projects_root` configured: welcome screen with logo, explanation, folder picker CTA. Animate transition to main graph after first scan.

#### 28.3 Settings Integration Tests
**Delegate to**: `test-engineer`

Test: config changes persist, projects root change triggers re-scan, threshold change triggers edge recomputation.

### Success Criteria
- [ ] Settings panel allows all config options
- [ ] Config changes take effect immediately
- [ ] First-run guides user to select projects dir
- [ ] Onboarding → graph transition is smooth

---

## Phase 29: Empty State & Loading States

### Objective
Polish the zero-data experience and all loading/transition states.

### Prerequisites
- Phase 28 complete

### Reference Documents
- Wireframe: `wireframes/empty-state.svg`

### Tasks

#### 29.1 Empty State
**Delegate to**: `ui-animation-dev`

No projects loaded: animated neural particle background (generative, low-poly), centered prompt ("Your neural network awaits"), folder picker button. Feels alive — particle drift, occasional pulse.

#### 29.2 Loading States
**Delegate to**: `ui-animation-dev`

Sidecar boot loading animation, scan progress indicator ("Scanning 12/25..."), detail panel skeleton while git data loads, first-scan → graph transition.

### Success Criteria
- [ ] Empty state shows animated background with CTA
- [ ] All loading states provide visual feedback
- [ ] Transitions between states are smooth

---

## Phase 30: Ambient Mode

### Objective
Implement the idle screensaver mode.

### Prerequisites
- Phase 29 complete

### Reference Documents
- ARCHITECTURE.md §3.3 (Animation System — ambient mode)
- Wireframe: `wireframes/ambient-mode.svg`

### Tasks

#### 30.1 Ambient Mode
**Delegate to**: `ui-animation-dev`

After configurable idle time (default 60s): nodes drift slowly, particles continue, subtle viewport drift. Any input exits smoothly. Should feel like a living neural network screensaver.

### Success Criteria
- [ ] Activates after configurable idle time
- [ ] Exits smoothly on any interaction
- [ ] Nodes drift with particles still flowing
- [ ] Feels atmospheric, not distracting

---

## Phase 31: Integration Testing

### Objective
Full end-to-end testing across the entire stack.

### Prerequisites
- Phase 30 complete

### Reference Documents
- ARCHITECTURE.md §15 (Performance Budgets)

### Tasks

#### 31.1 End-to-End Flow Test
**Delegate to**: `test-engineer`

Test complete flow: app launch → sidecar boot → first scan → graph render → node click → detail panel → search → edge drawing → cluster → settings → re-scan. Verify WebSocket propagation through the full stack.

#### 31.2 Performance Audit
**Delegate to**: `test-engineer`

Measure against budgets: canvas fps (30 nodes), detail panel open time, scan duration (25 projects), memory usage. Profile and identify bottlenecks.

### Success Criteria
- [ ] Complete flow works end-to-end
- [ ] Performance meets all budgets in ARCHITECTURE.md §15
- [ ] No P0 bugs

---

## Phase 32: Design System Audit & Polish

### Objective
Audit every UI component against the design system and wireframes.

### Prerequisites
- Phase 31 complete

### Reference Documents
- DESIGN_SYSTEM.md (full document)
- All wireframes in `wireframes/`

### Tasks

#### 32.1 Visual Audit
**Delegate to**: `code-reviewer`

Compare every component against DESIGN_SYSTEM.md and wireframes: colors, typography, spacing (8px grid), spring configs, frosted glass consistency, language palette accuracy.

#### 32.2 Bug Fix Sprint
**Delegate to**: `frontend-dev` / `python-backend-dev` / `ui-animation-dev` (as needed)

Fix all issues from integration testing, performance audit, and design audit.

### Success Criteria
- [ ] All UI matches design system and wireframes
- [ ] App feels polished and native
- [ ] No P0/P1 bugs remaining

---

## Phase 33: PyInstaller Sidecar Bundling

### Objective
Bundle the Python backend with PyInstaller for distribution.

### Prerequisites
- Phase 32 complete

### Reference Documents
- ARCHITECTURE.md §13 (Sidecar Bundling)

### Tasks

#### 33.1 PyInstaller Config
**Delegate to**: `python-backend-dev`

Create spec file for `--onedir` build. Handle hidden imports (uvicorn, sqlmodel, watchfiles). Name: `engram-sidecar-{target-triple}`. Test on arm64.

#### 33.2 Bundle Verification
**Delegate to**: `test-engineer`

Verify binary starts, serves `/api/health`, and runs a scan. Check size < 60MB. Check cold start < 3s.

### Success Criteria
- [ ] PyInstaller produces working binary
- [ ] Binary < 60MB
- [ ] Cold start < 3 seconds
- [ ] All sidecar features work from bundled binary

---

## Phase 34: Tauri Production Build

### Objective
Configure and test the production Tauri build pipeline.

### Prerequisites
- Phase 33 complete

### Reference Documents
- ARCHITECTURE.md §13 (Distribution)

### Tasks

#### 34.1 Build Configuration
**Delegate to**: `rust-shell-dev`

Configure `tauri.conf.json` for production: external binary paths, app identifier, DMG configuration. Before-build script runs PyInstaller. Test `pnpm tauri build`.

#### 34.2 Build Verification
**Delegate to**: `test-engineer`

Test .app on clean macOS: launches, sidecar boots, scan works, all features function.

### Success Criteria
- [ ] `pnpm tauri build` produces .app and .dmg
- [ ] App works on clean macOS installation
- [ ] Sidecar embeds correctly in .app bundle

---

## Phase 35: GitHub Actions — CI Pipeline

### Objective
Set up continuous integration for linting, testing, and type checking.

### Prerequisites
- Phase 34 complete

### Reference Documents
- ARCHITECTURE.md §14.1 (Workflows)

### Tasks

#### 35.1 CI Workflow
**Delegate to**: `python-backend-dev`

Create `.github/workflows/ci.yml`: on PR + push to main. Steps: black, isort, mypy (Python), eslint, tsc (TypeScript), pytest, vitest.

#### 35.2 CI Verification
**Delegate to**: `test-engineer`

Trigger workflow, verify it catches intentional failures. Confirm all checks pass on clean code.

### Success Criteria
- [ ] CI runs on every PR
- [ ] All lint/test/type checks run
- [ ] Intentional failures are caught

---

## Phase 36: GitHub Actions — Release & Auto-Update

### Objective
Set up the build, sign, release, and auto-update pipeline.

### Prerequisites
- Phase 35 complete

### Reference Documents
- ARCHITECTURE.md §14.2-14.3 (Build Pipeline, Auto-Update)

### Tasks

#### 36.1 Release Workflow
**Delegate to**: `rust-shell-dev`

Create `.github/workflows/build-release.yml`: on tag push (`v*`). Build arm64 + x86_64 sidecars, Tauri Action for each arch, sign, notarize, upload to Releases, generate update manifest.

#### 36.2 Auto-Update Integration
**Delegate to**: `rust-shell-dev`

Configure `tauri-plugin-updater`: check Releases on launch, background download, prompt restart.

#### 36.3 Release Verification
**Delegate to**: `test-engineer`

Test release workflow produces artifacts. Test auto-update detects new version.

### Success Criteria
- [ ] Tag push produces signed .dmg on GitHub Releases
- [ ] Auto-update detects and installs new releases
- [ ] Workflows complete within 15 minutes

---

## Phase 37: Final Review & v0.1.0 Launch

### Objective
Final quality gate, documentation, and first release.

### Prerequisites
- Phase 36 complete

### Tasks

#### 37.1 Full Code Review
**Delegate to**: `code-reviewer`

Review all code: type coverage, docstrings, error handling, design compliance, security (no hardcoded secrets).

#### 37.2 README & Documentation
**Delegate to**: `frontend-dev`

Write README: description, screenshots, install instructions, dev setup, architecture overview. Update ARCHITECTURE.md with implementation changes.

#### 37.3 v0.1.0 Release
**Delegate to**: `rust-shell-dev`

Create v0.1.0 tag. Trigger release workflow. Verify .dmg. Create GitHub Release with changelog + screenshots.

#### 37.4 Dogfood Test
**Delegate to**: `test-engineer`

Point Engram at real `~/Documents/VSCode-Projects`. Verify it discovers ~25 projects, graph looks correct, edges make sense, detail panels show right data.

### Success Criteria
- [ ] All code passes review
- [ ] README is comprehensive with screenshots
- [ ] v0.1.0 published on GitHub Releases
- [ ] Auto-update verified
- [ ] Real project ecosystem visualized correctly
- [ ] The graph looks beautiful

---

## Checklist Summary

### Foundation (Phases 1-5)
- [ ] Phase 1: Tauri v2 project initialization
- [ ] Phase 2: Python sidecar skeleton
- [ ] Phase 3: SQLite schema & initial migration
- [ ] Phase 4: Migration runner & database engine
- [ ] Phase 5: SQLModel ORM models

### API Layer (Phases 6-7)
- [ ] Phase 6: Projects API (CRUD)
- [ ] Phase 7: Edges, tags, clusters, positions API

### Scanning Pipeline (Phases 8-16)
- [ ] Phase 8: Scanner — discovery
- [ ] Phase 9: Scanner — project type & framework detection
- [ ] Phase 10: Scanner — language analysis & size
- [ ] Phase 11: Scanner — git analysis
- [ ] Phase 12: Scanner — README extraction
- [ ] Phase 13: Edge computation engine
- [ ] Phase 14: Scan orchestrator
- [ ] Phase 15: File watcher & debouncing
- [ ] Phase 16: WebSocket event hub

### Desktop Shell (Phases 17-18)
- [ ] Phase 17: Tauri sidecar lifecycle
- [ ] Phase 18: Tauri IPC commands

### Frontend Core (Phases 19-23)
- [ ] Phase 19: Layout & state management
- [ ] Phase 20: API integration layer
- [ ] Phase 21: React Flow canvas & neural nodes
- [ ] Phase 22: Custom edges & particle system
- [ ] Phase 23: Force-directed layout

### Features (Phases 24-30)
- [ ] Phase 24: Detail panel
- [ ] Phase 25: Spotlight search (⌘K)
- [ ] Phase 26: Filter chips & clusters
- [ ] Phase 27: Context menu & edge drawing
- [ ] Phase 28: Settings & onboarding
- [ ] Phase 29: Empty state & loading states
- [ ] Phase 30: Ambient mode

### Ship (Phases 31-37)
- [ ] Phase 31: Integration testing
- [ ] Phase 32: Design system audit & polish
- [ ] Phase 33: PyInstaller sidecar bundling
- [ ] Phase 34: Tauri production build
- [ ] Phase 35: GitHub Actions — CI
- [ ] Phase 36: GitHub Actions — release & auto-update
- [ ] Phase 37: Final review & v0.1.0 launch

---

## Quick Reference

### Subagent Task Routing

| Task Type | Subagent |
|-----------|----------|
| Rust / Tauri config / sidecar | `rust-shell-dev` |
| React components / stores / hooks | `frontend-dev` |
| React Flow / nodes / edges / layout | `graph-dev` |
| Motion (framer-motion) / CSS / visual polish | `ui-animation-dev` |
| FastAPI / scanner / WebSocket | `python-backend-dev` |
| SQLite / SQLModel / migrations | `db-dev` |
| Any test writing | `test-engineer` |
| Quality gates / reviews | `code-reviewer` |

### Key Commands

```bash
# Development
pnpm tauri dev                    # Launch full app in dev mode
cd sidecar && uvicorn main:app    # Run sidecar standalone
pnpm vitest                      # Frontend tests
cd sidecar && pytest tests/ -v   # Backend tests

# Build
pnpm tauri build                 # Production build
cd sidecar && pyinstaller ...    # Build sidecar binary

# Formatting
black sidecar/ && isort sidecar/ # Python formatting
pnpm eslint --fix                 # TypeScript linting
```

### Performance Targets

| Metric | Target |
|--------|--------|
| App launch → interactive | < 3s |
| Full scan (25 projects) | < 5s |
| Canvas 60fps | 30 nodes, 100 edges |
| Detail panel open | < 200ms |
| Search filter apply | < 100ms |
