# Engram — Architecture Document

> Personal coding project manager that visualizes your project ecosystem as a neural network graph.
> This is the deep technical reference. Read this before implementing anything.

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [System Architecture](#2-system-architecture)
3. [Neural Graph Rendering](#3-neural-graph-rendering)
4. [Python Sidecar — FastAPI Backend](#4-python-sidecar--fastapi-backend)
5. [Scanning Pipeline](#5-scanning-pipeline)
6. [Data Model & SQLite Schema](#6-data-model--sqlite-schema)
7. [Edge Computation Engine](#7-edge-computation-engine)
8. [File Watching & Incremental Updates](#8-file-watching--incremental-updates)
9. [Scan Concurrency Architecture](#9-scan-concurrency-architecture)
10. [Detail Panel & Live Data](#10-detail-panel--live-data)
11. [Search, Filter & Clustering](#11-search-filter--clustering)
12. [Tauri Shell & IPC Layer](#12-tauri-shell--ipc-layer)
13. [Sidecar Bundling & Distribution](#13-sidecar-bundling--distribution)
14. [GitHub Actions & CI/CD](#14-github-actions--cicd)
15. [Performance Budgets](#15-performance-budgets)
16. [Design System Reference](#16-design-system-reference)

---

## 1. Design Philosophy

Engram is built on three principles:

**1. Luminosity as Information** — Every visual property encodes data. Node glow = activity. Edge thickness = relationship strength. Particle speed = git recency. Nothing is decorative without purpose.

**2. Calm Density** — Show 25+ projects without overwhelm. The neural graph is spatially organized so your eye can scan the whole landscape at a glance, then drill into any node for depth. Information through form, not through noise.

**3. Apple-Level Polish** — Spring-based animations, frosted glass panels, native-feeling typography (SF Pro/Mono), 8px grid spacing, and attention to every transition. This is a personal tool that should feel like a first-party macOS app.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     macOS Desktop                        │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │                   Tauri v2 Shell                   │  │
│  │  • Rust: IPC glue, window management              │  │
│  │  • Sidecar lifecycle (spawn/kill Python backend)   │  │
│  │  • Native dialogs (folder picker, notifications)   │  │
│  │  • System tray / menubar integration              │  │
│  │  • tauri-plugin-updater for auto-updates          │  │
│  └─────────────┬──────────────────────┬──────────────┘  │
│                │ WebView              │ Sidecar          │
│                ▼                      ▼                  │
│  ┌─────────────────────┐  ┌─────────────────────────┐   │
│  │     Frontend         │  │   Python Sidecar        │   │
│  │                      │  │                         │   │
│  │  Vite + React 19     │  │   FastAPI + Uvicorn     │   │
│  │  TypeScript           │  │   SQLModel ORM         │   │
│  │  React Flow           │◄─►  Scanner Pipeline      │   │
│  │  Motion (framer-motion)│HTTP│  watchfiles Watcher   │   │
│  │  Zustand              │+WS │  GitPython            │   │
│  │  TanStack Query       │  │   Edge Computation     │   │
│  │  Tailwind CSS         │  │                         │   │
│  └─────────────────────┘  │   Bundled via            │   │
│                            │   PyInstaller (--onedir) │   │
│                            └─────────────────────────┘   │
│                                       │                  │
│                                       ▼                  │
│                            ┌─────────────────┐           │
│                            │   SQLite DB     │           │
│                            │   engram.db     │           │
│                            └─────────────────┘           │
└──────────────────────────────────────────────────────────┘
```

**Communication flow**: The frontend (React in Tauri's WebView) communicates with the Python sidecar over HTTP (REST endpoints) and WebSocket (real-time events). Tauri's Rust layer manages the sidecar process lifecycle and provides native OS integrations (file dialogs, notifications, system tray). The Python backend owns all data — SQLite reads/writes, file system scanning, and git analysis.

**Why this split?**

| Layer | Responsibility | Why This Tech |
|-------|---------------|---------------|
| Tauri (Rust) | Window, sidecar, native APIs | Lean — just glue code. No business logic in Rust. |
| React (TS) | All UI rendering, graph interaction | React Flow ecosystem, Motion (framer-motion), comfort zone. |
| FastAPI (Python) | Data pipeline, scanning, API | Python excels at file analysis, git ops, rapid dev. |
| SQLite | Persistence | Single-file DB, zero config, perfect for desktop apps. |

---

## 3. Neural Graph Rendering

### 3.1 Visual Encoding Map

Every visual property on the graph canvas maps to a project attribute:

```
PROJECT PROPERTY            →  VISUAL ENCODING
──────────────────────────────────────────────────
Project status (active)     →  Node glow intensity / pulse animation
                               Active = bright, breathing pulse
                               Dormant = dim, static
                               Idea = dashed outline, lightbulb icon
                               Missing = amber dashed ring, caution icon
Tech stack / language       →  Node hue (curated palette)
                               Python = amber/gold (#F59E0B)
                               React/TS = electric blue (#3B82F6)
                               Rust = copper/orange (#EA580C)
                               Multi-lang = gradient blend
Project complexity          →  Node radius
(LOC + deps + files)           Bigger project = larger radius
Git activity (recency)      →  Edge particle animation speed
                               Recent commits = fast particles
                               Stale = slow or no particles
Shared tech/deps            →  Auto-generated edges (weighted)
                               Thickness ∝ Jaccard similarity score
User-defined relations      →  Manual edges (user draws)
                               Optionally directed (arrows)
Tags / categories           →  Cluster background regions
                               Soft radial gradients
Git branch count            →  Small satellite dots orbiting node
Dirty/clean git status      →  Node ring style
                               Clean = solid ring
                               Dirty = dashed/pulsing ring
```

### 3.2 React Flow Integration

React Flow provides the graph foundation. We extend it with custom components:

**Custom Node Component** (`NeuralNode.tsx`):
```
┌─────────────────────────────────────────────┐
│              NEURAL NODE ANATOMY            │
│                                             │
│         ╭── Outer glow (CSS box-shadow)     │
│    ╭────┤   Color = language palette        │
│    │    │   Intensity = status (active=100%, │
│    │    │   paused=40%, archived=10%)        │
│    │    ╰── Blur radius: 12-24px            │
│    │                                        │
│    │  ╭── Ring                              │
│    ├──┤   Solid = clean git status          │
│    │  │   Dashed + pulse = dirty            │
│    │  ╰── Width: 2px                        │
│    │                                        │
│    │  ╭── Core circle                       │
│    ├──┤   Fill: language color at 80%       │
│    │  │   Size: 36-72px (scaled by LOC)     │
│    │  ╰── Contains: language icon or letter │
│    │                                        │
│    │  ╭── Satellite dots (branches)         │
│    ├──┤   Small 4px dots orbiting at 120%   │
│    │  ╰── radius, count = branch count      │
│    │                                        │
│    ╰── Label (below)                        │
│        Project name, 12px, SF Pro           │
│        Secondary: primary language, 10px    │
└─────────────────────────────────────────────┘
```

**Custom Edge Component** (`NeuralEdge.tsx`):
- Base path: bezier curve via React Flow's built-in path calculation.
- Stroke width: `1 + (weight * 4)` px — so weight 0.3 = 2.2px, weight 1.0 = 5px.
- Stroke color: auto edges = `rgba(255,255,255,0.15)`, manual edges = accent color.
- Particles: SVG `<circle>` elements animated along the path via `<animateMotion>`. Speed = function of the more recently active project's `git_last_commit_date`. One particle per 0.2 weight (so weight 1.0 = 5 particles).
- Directed edges: `markerEnd` with arrow marker, applied only when `edge.data.directed === true`.

**Layout Engine** (`useForceLayout.ts`):
- d3-force simulation with custom forces:
  - `forceLink`: Edge attraction, strength = `edge.weight * 0.5`
  - `forceManyBody`: Node repulsion, strength = `-200`
  - `forceCenter`: Gentle pull toward canvas center
  - `forceCollide`: Prevent node overlap, radius = `nodeSize + 20`
- Pinned nodes (`pinned: true` in DB) are excluded from simulation — `node.fx = node.x, node.fy = node.y`.
- Simulation runs on initial load, then stops. Re-runs when nodes are added/removed.
- On node drag stop, pin the node: `UPDATE node_positions SET pinned = TRUE WHERE project_id = ?`.

### 3.3 Animation System

All animations use Motion (npm: `framer-motion`) with spring physics:

| Animation | Config | Trigger |
|-----------|--------|---------|
| Node breathing (active) | `scale: [1.0, 1.02, 1.0]`, duration 3s, repeat ∞ | Status = `active` |
| Node hover highlight | `scale: 1.08`, `filter: brightness(1.3)`, spring 300ms | Mouse enter |
| Edge particle flow | SVG `<animateMotion>`, duration = `10 / activityScore` seconds | Always running |
| Detail panel slide | `x: [420, 0]`, spring damping 25, stiffness 300 | Node click |
| Filter fade | `opacity: [1, 0.08]`, spring 200ms | Filter applied |
| New node appear | `scale: [0, 1.1, 1.0]`, spring 400ms | Project added |
| Cluster background | Radial gradient, `opacity` transition 300ms | Cluster toggle |
| Ambient mode drift | `x/y` += small random offset, duration 60s, repeat ∞ | Idle 60s |

**Spring defaults** (Motion): `{ type: "spring", damping: 20, stiffness: 250 }` — snappy but not jarring.

### 3.4 Performance Targets — Canvas

| Metric | Target | Strategy |
|--------|--------|----------|
| 60fps with 30 nodes | Required | React Flow's built-in virtualization |
| 60fps with 100 edges | Required | SVG path caching, particle count limits |
| First meaningful paint | < 500ms | Render nodes from DB cache, animate in |
| Force layout settle | < 1s for 30 nodes | d3-force with alpha decay 0.05 |
| Zoom/pan smoothness | No jank | React Flow handles natively |

**Escalation path**: If SVG particle animations cause frame drops above ~50 edges, migrate particles to a lightweight `<canvas>` overlay rendered on top of the React Flow SVG layer. React Flow supports this via its `<Background>` and custom panel slots.

---

## 4. Python Sidecar — FastAPI Backend

### 4.1 Application Structure

```
sidecar/
├── main.py                     # FastAPI app, lifespan, CORS
├── config.py                   # Config loading from DB + defaults
├── models/                     # SQLModel ORM models
│   ├── project.py              # Project model
│   ├── edge.py                 # Edge model
│   ├── tag.py                  # Tag + ProjectTag models
│   ├── cluster.py              # Cluster + ProjectCluster models
│   ├── node_position.py        # NodePosition model
│   └── config.py               # Config model
├── scanner/                    # Scanning pipeline
│   ├── orchestrator.py         # ScanOrchestrator (concurrency, queue)
│   ├── discovery.py            # Phase 1: directory enumeration
│   ├── analyzers/
│   │   ├── project_type.py     # Manifest file detection
│   │   ├── frameworks.py       # Framework/tooling detection
│   │   ├── languages.py        # LOC counting + language breakdown
│   │   ├── git_analyzer.py     # Git status, commits, branches
│   │   ├── readme.py           # README extraction
│   │   └── size.py             # Directory size computation
│   ├── edge_computer.py        # Pairwise edge computation
│   └── watcher.py              # watchfiles async watcher
├── api/                        # FastAPI routers
│   ├── projects.py             # CRUD + live git detail
│   ├── edges.py                # Edge management
│   ├── tags.py                 # Tag management
│   ├── clusters.py             # Cluster management
│   ├── scan.py                 # Scan trigger/status endpoints
│   ├── config_routes.py        # Config get/set
│   └── websocket.py            # WebSocket event hub
├── db/
│   ├── engine.py               # SQLModel engine + PRAGMA setup
│   ├── session.py              # Session dependency
│   └── migrations/
│       ├── migrator.py         # PRAGMA user_version migration runner
│       ├── 0001_init.sql       # Initial schema
│       └── 0002_*.sql          # Future migrations
└── utils/
    ├── ulid.py                 # ULID generation helper
    └── debounce.py             # Async debounce utility
```

### 4.2 FastAPI App Setup

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    migrator = DatabaseMigrator(db_path, migrations_dir)
    if not migrator.migrate():
        raise RuntimeError("Database migration failed — refusing to start.")

    # Start file watcher
    watcher_task = asyncio.create_task(watcher.watch())

    # Run initial full scan
    asyncio.create_task(orchestrator.trigger_full_scan())

    yield

    # Shutdown
    watcher_task.cancel()
    await orchestrator.shutdown()

app = FastAPI(title="Engram Sidecar", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```

### 4.3 API Endpoints

```
GET  /api/health                    → { "status": "ok", "version": "0.1.0" }
GET  /api/projects                  → List all projects (from DB)
GET  /api/projects/{id}             → Single project detail
GET  /api/projects/{id}/git-detail  → Live git data (commits, branches, status)
POST /api/projects                  → Create project (manual add / idea)
PATCH /api/projects/{id}            → Update project fields
DELETE /api/projects/{id}           → Soft-delete (sets deleted_at)

GET  /api/edges                     → All edges
POST /api/edges                     → Create manual edge
PATCH /api/edges/{id}               → Update edge (weight, label, directed)
DELETE /api/edges/{id}              → Delete edge

GET  /api/tags                      → All tags
POST /api/tags                      → Create tag
POST /api/projects/{id}/tags        → Assign tag to project
DELETE /api/projects/{id}/tags/{tid}→ Remove tag from project

GET  /api/clusters                  → All clusters
POST /api/clusters                  → Create cluster
PATCH /api/clusters/{id}            → Update cluster (name, color, collapsed)
POST /api/clusters/{id}/projects    → Add project to cluster
DELETE /api/clusters/{id}/projects/{pid} → Remove from cluster

GET  /api/positions                 → All node positions
PATCH /api/positions/{project_id}   → Update position (x, y, pinned)
POST /api/positions/batch           → Batch update positions (after layout)

GET  /api/scan/status               → Scan state (idle/scanning/progress %)
POST /api/scan/full                 → Trigger full scan
POST /api/scan/project/{id}         → Rescan single project

GET  /api/config                    → All config entries
PATCH /api/config/{key}             → Update config value

WS   /api/ws                        → WebSocket event stream
                                      Events: new_project_detected,
                                      project_updated, scan_progress,
                                      scan_completed, project_missing
```

### 4.4 WebSocket Event Protocol

```json
// Server → Client events
{ "event": "new_project_detected", "data": { "path": "/Users/.../newproject", "name": "newproject" } }
{ "event": "project_updated", "data": { "id": "01HX...", "fields": ["git_branch", "git_dirty"] } }
{ "event": "scan_progress", "data": { "phase": "analyzing", "current": 12, "total": 25 } }
{ "event": "scan_completed", "data": { "duration_ms": 3200, "projects_scanned": 25 } }
{ "event": "project_missing", "data": { "id": "01HX...", "path": "/Users/.../deleted-project" } }
```

---

## 5. Scanning Pipeline

### 5.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│                    SCAN ORCHESTRATOR                     │
│                                                         │
│  Triggers:                                              │
│  1. App launch → full scan                              │
│  2. watchfiles event → incremental scan (single project)│
│  3. Manual "Rescan" from UI → single project            │
│  4. Timer (every N min) → full scan                     │
│                                                         │
│  ┌───────────┐   ┌───────────┐   ┌──────────────────┐  │
│  │ Discovery │──►│ Per-Project│──►│  Edge Computation │  │
│  │   Phase   │   │  Analyzers│   │      Phase        │  │
│  └───────────┘   └───────────┘   └──────────────────┘  │
│                                                         │
│  Discovery: list dirs in root, diff against DB          │
│  Analyzers: run concurrently per project                │
│  Edge Comp: pairwise comparison after all analyses done │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Phase 1: Discovery

Enumerate immediate children of `projects_root`. Compare against known projects in DB.

```python
root = config["projects_root"]  # e.g. ~/Documents/VSCode-Projects
dirs_on_disk = {d.name: d for d in Path(root).iterdir()
                if d.is_dir() and not d.name.startswith('.')}
known = {p.path: p for p in db.query(Project).where(Project.path != None)}

new_dirs     = dirs_on_disk.keys() - known.keys()    # → WebSocket notification
missing_dirs = known.keys() - dirs_on_disk.keys()     # → mark missing=TRUE
existing     = dirs_on_disk.keys() & known.keys()     # → re-analyze
```

**New project handling**: New directories are NOT auto-added. The frontend receives a WebSocket event and shows a toast: *"New project detected: myproject. [Add to Engram] [Ignore]"*. If the user clicks "Add," a `POST /api/projects` creates the row with `status=active`.

**Missing project handling**: If a known project's directory vanishes, set `missing=TRUE` in the DB. The graph node renders with an amber warning indicator. The detail panel shows: *"Directory not found. [Re-link] [Remove from Engram]"*. Re-link opens Tauri's native folder picker.

### 5.3 Phase 2: Per-Project Analysis

Six analyzers run for each project. For a single project scan, they execute sequentially. For a full scan, projects are processed concurrently (up to `Semaphore(4)` limit).

**2a. Project Type Detection** — Scan for manifest files (`package.json`, `Cargo.toml`, `requirements.txt`, `pyproject.toml`, `go.mod`, etc.). First match determines primary classification, but all are checked for completeness. Parse manifest for: name, description, dependencies list.

**2b. Framework & Tooling Detection** — Go deeper than language. Detect frameworks from dependency lists and config file presence:

| Signal | Framework |
|--------|-----------|
| `"react"` in package.json deps | React |
| `"@tauri-apps/api"` in deps | Tauri |
| `"tailwindcss"` in devDeps | Tailwind CSS |
| `vite.config.*` exists | Vite |
| `tsconfig.json` exists | TypeScript |
| `.github/workflows/` exists | GitHub Actions |
| `"fastapi"` in requirements.txt | FastAPI |
| `Dockerfile` exists | Docker |

**2c. Language Breakdown** — Walk the file tree (excluding `node_modules`, `.git`, `target`, `dist`, `build`, `__pycache__`, `venv`, etc.). Count lines per file extension. Compute percentages. Primary language = highest LOC (excluding config formats).

**2d. Git Analysis** — Run git commands via `asyncio.create_subprocess_exec`:

```
git rev-parse --abbrev-ref HEAD          → current branch
git status --porcelain                   → dirty status
git log -1 --format="%H|%aI|%s"         → last commit
git branch --list | wc -l               → branch count
git remote get-url origin               → remote URL (if any)
```

Non-git directories: all git fields set to `NULL`. Node renders without ring indicator.

**2e. README Extraction** — Find `README.md` (case-insensitive). Skip the H1 title line, skip badge lines (`[![`), take the first paragraph of prose, truncate to 300 chars. Fallback: check `description` in `package.json` or `Cargo.toml [package]`.

**2f. Size Computation** — `os.walk` with excluded dirs pruned in-place. Sum file sizes, count source files by extension.

### 5.4 Phase 3: Edge Computation

After all per-project analyses complete, compute pairwise relationships. Runs once per full scan.

**Tech Stack Similarity** (`auto_tech` edges): Jaccard similarity over the union of languages + frameworks. `score = |intersection| / |union|`. Edges created when score ≥ `auto_edge_min_weight` (default 0.3). Edges removed when score drops below threshold.

**Dependency Overlap** (`auto_dep` edges): Intersection of parsed dependency lists. Weight = `|shared| / |smaller_set|`. Same threshold applies.

Manual edges are NEVER modified by the scanner.

---

## 6. Data Model & SQLite Schema

### 6.1 Entity Relationship

```
┌──────────┐       ┌──────────────┐       ┌──────────┐
│   Tag    │◄─M:M──│   Project    │──M:M─►│  Cluster │
└──────────┘       └──────┬───────┘       └──────────┘
                          │ 1
                          │ M (source or target)
                          ▼
                   ┌──────────────┐
                   │     Edge     │
                   └──────────────┘

┌──────────────┐   ┌──────────────┐
│ NodePosition │   │    Config    │
│  (per project)│   │  (singleton) │
└──────────────┘   └──────────────┘
```

8 tables total: `projects`, `edges`, `tags`, `project_tags`, `clusters`, `project_clusters`, `node_positions`, `config`.

### 6.2 projects Table

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT (ULID) | PK. Chronologically sortable. |
| `name` | TEXT NOT NULL | Display name. Defaults to directory name. |
| `path` | TEXT UNIQUE | Nullable — NULL for `idea` status projects. |
| `description` | TEXT | From README or user-written. |
| `status` | TEXT DEFAULT 'active' | Enum: `active`, `paused`, `archived`, `idea`. |
| `primary_language` | TEXT | Dominant language by LOC. |
| `languages` | JSON | `{"typescript": 0.65, "css": 0.20}` |
| `frameworks` | JSON | `["react", "tailwind", "vite"]` |
| `package_manager` | TEXT | npm, yarn, pip, cargo, etc. |
| `loc` | INTEGER | Lines of code (excluding vendored). |
| `file_count` | INTEGER | Source file count. |
| `size_bytes` | INTEGER | Total directory size on disk. |
| `git_remote_url` | TEXT | GitHub/remote URL. |
| `git_branch` | TEXT | Current checked-out branch. |
| `git_dirty` | BOOLEAN | Uncommitted changes present. |
| `git_last_commit_hash` | TEXT | SHA of most recent commit. |
| `git_last_commit_date` | DATETIME | Timestamp of most recent commit. |
| `git_last_commit_msg` | TEXT | Message of most recent commit. |
| `git_branch_count` | INTEGER | Local branch count. |
| `color_override` | TEXT | User-set hex color (overrides auto-color). |
| `icon_override` | TEXT | User-set icon identifier. |
| `notes` | TEXT | Free-form user notes. |
| `missing` | BOOLEAN DEFAULT FALSE | TRUE if directory no longer exists. |
| `deleted_at` | DATETIME | Soft-delete timestamp. NULL = active. |
| `last_scanned_at` | DATETIME | Last scanner analysis time. |
| `last_opened_at` | DATETIME | Last user open from Engram. |
| `created_at` | DATETIME NOT NULL | First discovery time. |
| `updated_at` | DATETIME NOT NULL | Last row modification. |

**Indexes**: `path` (unique), `status`, `primary_language`, `git_last_commit_date`, `deleted_at`.

### 6.3 edges Table

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT (ULID) | PK. |
| `source_id` | TEXT NOT NULL | FK → projects.id ON DELETE CASCADE. |
| `target_id` | TEXT NOT NULL | FK → projects.id ON DELETE CASCADE. |
| `edge_type` | TEXT NOT NULL | Enum: `auto_tech`, `auto_dep`, `manual`. |
| `weight` | REAL NOT NULL | 0.0–1.0. Auto = computed, manual = user-set. |
| `label` | TEXT | Optional user label ("forked from", etc.). |
| `color_override` | TEXT | Optional hex color. |
| `directed` | BOOLEAN DEFAULT FALSE | Auto = undirected. Manual = directed by default. |
| `metadata` | JSON | `{"shared_deps": ["react", "zustand"], "score": 0.73}` |
| `created_at` | DATETIME NOT NULL | |
| `updated_at` | DATETIME NOT NULL | |

**Constraints**: `UNIQUE(source_id, target_id, edge_type)`.

### 6.4 Other Tables

**tags**: `id` (ULID PK), `name` (TEXT UNIQUE), `color` (TEXT), `created_at`.

**project_tags**: `project_id` (FK CASCADE), `tag_id` (FK CASCADE). PK = (project_id, tag_id).

**clusters**: `id` (ULID PK), `name`, `color`, `opacity` (REAL DEFAULT 0.15), `collapsed` (BOOLEAN DEFAULT FALSE), `created_at`, `updated_at`.

**project_clusters**: `project_id` (FK CASCADE), `cluster_id` (FK CASCADE). PK = (project_id, cluster_id). Projects CAN belong to multiple clusters.

**node_positions**: `project_id` (FK CASCADE, PK), `x` (REAL), `y` (REAL), `pinned` (BOOLEAN DEFAULT FALSE), `updated_at`.

**config**: `key` (TEXT PK), `value` (JSON), `updated_at`.

### 6.5 Critical SQLite Configuration

```python
# MUST execute on EVERY new connection — SQLite disables FK enforcement by default
from sqlalchemy import event
from sqlmodel import create_engine

engine = create_engine("sqlite:///engram.db", connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")  # Better concurrent read performance
    cursor.close()
```

### 6.6 Migration System

Manual SQL scripts tracked via `PRAGMA user_version`:

```
db/migrations/
├── 0001_init.sql          # Full initial schema
├── 0002_add_missing.sql   # Add missing boolean
└── ...
```

On app startup, the migrator checks `PRAGMA user_version`, runs scripts with version > current in order, updates `user_version`. All migrations run in transactions — failure rolls back and blocks startup with a clear error.

### 6.7 ULIDs

All primary keys use ULIDs (Universally Unique Lexicographically Sortable Identifiers). Benefits: globally unique, chronologically sortable, no auto-increment id leakage, safe for potential future sync/export.

Generated via `python-ulid` package: `from ulid import ULID; str(ULID())`.

---

## 7. Edge Computation Engine

### 7.1 Tech Stack Similarity (auto_tech)

```python
def compute_tech_similarity(a: Project, b: Project) -> tuple[float, list[str]]:
    features_a = set(a.frameworks or []) | set((a.languages or {}).keys())
    features_b = set(b.frameworks or []) | set((b.languages or {}).keys())

    intersection = features_a & features_b
    union = features_a | features_b

    if not union:
        return 0.0, []

    score = len(intersection) / len(union)  # Jaccard similarity
    return score, list(intersection)
```

### 7.2 Dependency Overlap (auto_dep)

```python
def compute_dep_overlap(a: Project, b: Project) -> tuple[float, list[str]]:
    deps_a = extract_dependencies(a)  # Parse from manifest
    deps_b = extract_dependencies(b)

    if not deps_a or not deps_b:
        return 0.0, []

    shared = deps_a & deps_b
    smaller = min(len(deps_a), len(deps_b))
    score = len(shared) / smaller if smaller > 0 else 0.0
    return score, list(shared)
```

### 7.3 Edge Lifecycle

Edges are upserted: if a `(source_id, target_id, edge_type)` tuple already exists, update its weight and metadata. If an existing auto-edge's weight drops below `auto_edge_min_weight` (default 0.3), the edge is deleted. Manual edges are never touched by the scanner — they're user-created and user-managed only.

---

## 8. File Watching & Incremental Updates

### 8.1 watchfiles Integration

```python
from watchfiles import awatch

class ProjectWatcher:
    def __init__(self, projects_root: str, orchestrator: ScanOrchestrator):
        self.projects_root = projects_root
        self.orchestrator = orchestrator

    async def watch(self):
        async for changes in awatch(self.projects_root):
            for change_type, path in changes:
                project_id = self._resolve_project_id(path)
                if project_id:
                    await self.orchestrator.trigger_incremental_scan(
                        project_id, debounce_secs=5.0
                    )
```

**Why watchfiles?** Rust-based, async-native (`async for` iteration), no thread-to-asyncio bridging. Built by Samuel Colvin (author of Pydantic). Faster and simpler than watchdog.

### 8.2 Debouncing

A single `npm install` generates thousands of file events. The orchestrator debounces per-project: it waits 5 seconds after the last event for a given project before triggering a re-scan. Implementation uses per-project `asyncio.Task` with cancel/reschedule on each new event.

### 8.3 Incremental Scan Optimization

On re-scan, first check `git_last_commit_hash`. If unchanged and the trigger was a file watcher event (not manual rescan), only refresh `git_dirty` status (a single `git status --porcelain` call). Full re-analysis only runs if the commit hash changed or the user explicitly requested a rescan.

---

## 9. Scan Concurrency Architecture

```
┌─────────────────────────────────────────────────────┐
│              SCAN ORCHESTRATOR                       │
│                                                     │
│  Layer 1: PriorityQueue                             │
│  ┌───────────────────────────────────────────────┐  │
│  │ Full scan jobs       → priority 0 (highest)   │  │
│  │ Manual rescan jobs   → priority 5             │  │
│  │ File watcher debounce→ priority 10 (lowest)   │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Layer 2: Global Semaphore (max 4 concurrent)       │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐                       │
│  │ W1 │ │ W2 │ │ W3 │ │ W4 │  ← worker tasks       │
│  └────┘ └────┘ └────┘ └────┘                       │
│                                                     │
│  Layer 3: Per-Project asyncio.Lock                  │
│  ┌────────┐ ┌────────┐ ┌────────┐                  │
│  │ proj-A │ │ proj-B │ │ proj-C │  ← one lock each  │
│  └────────┘ └────────┘ └────────┘                  │
│                                                     │
│  Blocking I/O (git, file walk) runs in              │
│  ThreadPoolExecutor via run_in_executor()           │
└─────────────────────────────────────────────────────┘
```

- **PriorityQueue**: Full scans take precedence over debounced file watcher events.
- **Semaphore(4)**: Max 4 projects scanned concurrently. Prevents CPU/IO overload when all 25+ projects trigger simultaneously.
- **Per-project Lock**: Only one scan of project X at a time. Prevents double-writes.
- **ThreadPoolExecutor**: Git commands and `os.walk` are blocking — wrapped in `asyncio.to_thread` or `loop.run_in_executor`.

---

## 10. Detail Panel & Live Data

### 10.1 Panel Behavior

The detail panel slides in from the right on node click (~420px wide). The graph canvas remains visible and interactive behind it (dims slightly). Spring animation via Motion (~300ms, damping 25). Clicking a different node swaps content with a crossfade — no close/reopen flicker. Frosted glass backdrop (`backdrop-filter: blur(20px)`).

### 10.2 Data Strategy — Cached vs. Live

| Data | Source | Reason |
|------|--------|--------|
| Name, path, status, tags, clusters | DB (`projects` table) | Stable, user-editable |
| Language, frameworks, LOC, size | DB (`projects` table) | Computed during scan, cached |
| Git branch, dirty, last commit | DB (`projects` table) | Updated each scan — good enough for graph |
| Recent commit log (last 10) | **Live fetch** on panel open | Too volatile to cache. `git log -10` is fast. |
| Full branch list | **Live fetch** on panel open | Branches change frequently. |
| Uncommitted changes list | **Live fetch** on panel open | Changes by the second. |
| Connected edges + clusters | DB (edges, project_clusters) | Stable relational data |

The FastAPI endpoint `GET /api/projects/{id}/git-detail` runs the live git commands and returns commit log, branch list, and status. TanStack Query on the frontend caches this per-project with a 30s TTL.

### 10.3 Quick Actions

Four icon buttons in the header, each launching via Tauri's shell API:

| Action | Command |
|--------|---------|
| VS Code | `open -a "Visual Studio Code" <path>` |
| Terminal | `open -a Terminal <path>` |
| Finder | `open <path>` |
| GitHub | Opens `git_remote_url` in default browser |

---

## 11. Search, Filter & Clustering

### 11.1 Search (⌘K Spotlight)

Spotlight-style search bar triggered by ⌘K. Searches project names, descriptions, languages, frameworks, and tags. Non-matching nodes fade to `opacity: 0.08`. Matching nodes glow brighter. Implemented client-side with Zustand store filtering — no backend call needed for 25-30 projects.

### 11.2 Filter Chips

Persistent filter chips below the search bar: by language, tag, status, recency. Multiple filters combine with AND logic. Activating a filter smoothly animates non-matching nodes via Motion. Active filters stored in Zustand and persisted to the `config` table.

### 11.3 Clusters

Clusters render as soft radial gradient backgrounds behind grouped nodes. Creating a cluster: drag-select nodes → "Create Group" → name + pick color. Clusters can be collapsed into a single super-node (sets `collapsed=TRUE` in DB). A project can belong to multiple overlapping clusters.

---

## 12. Tauri Shell & IPC Layer

### 12.1 Rust Layer Responsibilities

The Rust layer is intentionally thin — just glue:

- **Sidecar lifecycle**: Spawn the PyInstaller-bundled Python backend on app start, kill on quit. Health-check via `GET /api/health` with retry loop on startup.
- **Window management**: Single main window, frameless with custom titlebar, vibrancy effect for macOS native feel.
- **Native dialogs**: Folder picker for project root selection and re-linking missing projects.
- **System tray**: Optional menubar icon with quick-access to recent projects.
- **Auto-update**: `tauri-plugin-updater` checks GitHub Releases API on launch, downloads and installs updates silently.

### 12.2 Sidecar Spawn

```rust
// Tauri sidecar configuration (tauri.conf.json)
{
  "bundle": {
    "externalBin": ["binaries/engram-sidecar"]
  }
}

// Rust: spawn sidecar
let sidecar = app.shell()
    .sidecar("engram-sidecar")
    .args(["--port", "9721"])
    .spawn()
    .expect("Failed to spawn sidecar");
```

The frontend connects to `http://localhost:9721` for API calls and `ws://localhost:9721/api/ws` for WebSocket events. Port is configurable but defaults to 9721.

### 12.3 IPC Commands

Minimal Tauri commands — most logic lives in the Python backend:

| Command | Purpose |
|---------|---------|
| `open_in_vscode` | Shell exec: `code <path>` |
| `open_in_terminal` | Shell exec: `open -a Terminal <path>` |
| `open_in_finder` | Shell exec: `open <path>` |
| `pick_folder` | Native folder picker dialog |
| `get_sidecar_port` | Return the port the sidecar is running on |

---

## 13. Sidecar Bundling & Distribution

### 13.1 PyInstaller Configuration

```
pyinstaller \
  --name engram-sidecar \
  --onedir \
  --noconfirm \
  --clean \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.protocols.http \
  --hidden-import sqlmodel \
  --collect-all watchfiles \
  main.py
```

Output binary: `engram-sidecar-aarch64-apple-darwin` (arm64) or `engram-sidecar-x86_64-apple-darwin` (Intel). Estimated size: 40-50MB. Cold start: 1-3 seconds (frontend shows loading animation).

### 13.2 Binary Naming Convention

Tauri's `externalBin` uses target-triple suffixed binaries:

```
src-tauri/binaries/
├── engram-sidecar-aarch64-apple-darwin     # Apple Silicon
└── engram-sidecar-x86_64-apple-darwin      # Intel Mac
```

### 13.3 Fallback

If PyInstaller code-signing proves problematic with Apple notarization, switch to PyOxidizer (better official macOS signing support, steeper learning curve, 50-80MB binary).

---

## 14. GitHub Actions & CI/CD

### 14.1 Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `build-release.yml` | Tag push (`v*`) | Build .dmg/.app, sign, notarize, upload to Releases |
| `ci.yml` | PR / push to main | Lint, test, type-check (frontend + backend) |
| `nightly.yml` | Cron (daily) | Build from main, upload as pre-release |
| `changelog.yml` | Release published | Auto-generate changelog from conventional commits |
| `dep-audit.yml` | Cron (weekly) | Scan npm + pip deps for vulnerabilities |

### 14.2 Build & Release Pipeline

```
1. Build arm64 sidecar on macOS arm64 runner
   → PyInstaller --onedir
   → Code sign with Developer ID

2. Build x86_64 sidecar on macOS x86_64 runner
   → Same process

3. Tauri Action builds .app/.dmg for each architecture
   → Embeds signed sidecar binary
   → Signs the .app bundle

4. Notarize with Apple notarytool
   → Staple notarization ticket

5. Upload to GitHub Releases
   → .dmg for each arch
   → Update manifest JSON for tauri-plugin-updater
```

### 14.3 Auto-Update Flow

The app checks GitHub Releases on launch via `tauri-plugin-updater`. If a newer version exists, it downloads the update, verifies the signature, and prompts the user to restart. Silent background download, non-intrusive prompt.

---

## 15. Performance Budgets

| Metric | Budget | Measurement |
|--------|--------|-------------|
| App launch to interactive | < 3s | Sidecar boot + initial render |
| Full scan (25 projects) | < 5s | Discovery + analysis + edge computation |
| Incremental scan (1 project) | < 500ms | Single project re-analysis |
| Canvas render (30 nodes) | 60fps | React Flow + custom nodes |
| Detail panel open | < 200ms | Slide animation + DB read |
| Live git detail fetch | < 300ms | `git log` + `git status` + `git branch` |
| Search filter apply | < 100ms | Client-side, opacity transitions |
| SQLite query (any) | < 50ms | Indexed queries, small dataset |
| Memory (frontend) | < 200MB | React + React Flow + cached data |
| Memory (sidecar) | < 100MB | FastAPI + SQLite + scanner |
| Disk (sidecar binary) | < 60MB | PyInstaller --onedir bundle |

---

## 16. Design System Reference

Full design system is documented in `DESIGN_SYSTEM.md`. Key tokens for quick reference:

### Color Palette — Language Colors

| Language | Color | Hex |
|----------|-------|-----|
| Python | Amber/Gold | `#F59E0B` |
| TypeScript/React | Electric Blue | `#3B82F6` |
| Rust | Copper/Orange | `#EA580C` |
| JavaScript | Yellow | `#EAB308` |
| Go | Cyan | `#06B6D4` |
| Swift | Orange-Red | `#F97316` |
| Ruby | Red | `#EF4444` |
| CSS | Purple | `#8B5CF6` |

### Status Colors

| Status | Color | Usage |
|--------|-------|-------|
| Active | Green | `#22C55E` — bright glow, breathing pulse |
| Paused | Amber | `#F59E0B` — dimmed glow |
| Archived | Gray | `#6B7280` — minimal glow |
| Idea | Purple | `#A855F7` — dashed outline, seed icon |
| Missing | Amber/Red | `#F59E0B` — dashed ring, warning icon |

### Typography

- **Body**: SF Pro (system font), 13px base
- **Code elements**: SF Mono (SHAs, paths, branches)
- **Headings**: SF Pro, 20px name, descending hierarchy
- **Stats/numbers**: SF Mono for alignment

### Spacing

- 8px grid system
- 16px horizontal padding in panels
- 24px between sections
- 8px between items within sections

### Elevation Model

5 layers with frosted glass (`backdrop-filter: blur(20px)`) on overlays. Background canvas is the lowest layer, detail panel and modals float above.

---

> This document evolves with implementation. Update sections as architecture decisions are refined during development. All subagents MUST read relevant sections before implementing.
