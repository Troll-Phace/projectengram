# Engram Design System & Wireframe Brief

> A comprehensive design reference for producing SVG wireframes of Engram — a personal coding project manager rendered as a neural network graph.
>
> **For the designer**: This document describes *what* each view must communicate and *why*, along with firm constraints. The *how* — layout proportions, exact spacing, visual flourishes, micro-interactions — is yours to interpret. Think of each wireframe spec as a creative brief, not a pixel-perfect mandate.
>
> **Output format**: SVG wireframes, one per view. Dark theme. Apple-level polish is the north star.

---

## 1. Design Philosophy

### 1.1 Core Identity

Engram visualizes a developer's entire portfolio of coding projects as a living neural network. The aesthetic draws from deep learning architecture diagrams, attention map visualizations, and data-flow animations — but it must never feel clinical or academic. The goal is warmth, personality, and tactile delight layered over the neural metaphor.

**The tension to hold**: scientific precision meets personal expression. The graph should feel like peering into a beautiful machine that happens to be *your* brain.

### 1.2 Design Pillars

**Luminosity over flatness**. This is a dark-canvas app. Light comes from the content itself — glowing nodes, particle trails, pulsing indicators. The UI should feel like it emits light rather than reflects it. Avoid flat gray-on-gray; instead, let elements radiate outward with soft bloom and falloff.

**Information through form**. Every visual property encodes real data. Node size isn't decorative — it's LOC. Edge thickness isn't random — it's relationship strength. Color isn't preference — it's tech stack. The designer should lean into this: the graph should be *readable* by someone who understands the visual language, not just pretty.

**Calm density**. There's a lot of information here (25+ projects, 100+ edges, git status, tags, clusters). The design must never feel cluttered. Use progressive disclosure aggressively — hover reveals, click expands, scroll uncovers. The resting state of the UI should feel spacious and meditative. Complexity reveals itself on demand.

**Tactile physics**. Every interaction should feel physically grounded. Nodes have weight when dragged. Edges have tension. Panels slide with spring easing, not linear motion. The graph settles into equilibrium like a physical system. Nothing teleports; everything transitions.

### 1.3 Emotional Targets

- **First launch**: "Whoa, this is beautiful."
- **Daily use**: "I know exactly where everything is."
- **Idle on desk**: "That ambient mode is mesmerizing."
- **Showing a friend**: "Look at this — it's a map of everything I've built."

---

## 2. Foundations

### 2.1 Color System

The palette is dark-first with luminous accents. The background is not pure black — it has just enough warmth or coolness to feel like a space rather than a void.

**Canvas background**: A very dark neutral. Consider a subtle noise texture or ultra-fine grid pattern to give depth. The designer should decide whether the canvas leans cool (deep navy-charcoal) or warm (near-black with a hint of brown/purple). Either can work — it depends on how the node colors interact.

**Language color palette**: Each programming language maps to a curated accent color. These colors define node glow, detail panel accents, edge tints, and tag chips. The palette must be:
- Visually distinguishable at a glance (no two languages should look alike at node size)
- Beautiful in isolation and in combination (nodes of different colors will cluster together)
- Readable against the dark canvas (sufficient luminance)

Suggested starting associations (the designer may adjust hues to achieve better harmony):

| Language | Color Direction | Rationale |
|----------|----------------|-----------|
| Python | Amber / Gold | The Python community's yellow-blue branding, warm |
| TypeScript / React | Electric Blue | Associated with modern frontend, cool |
| Rust | Copper / Burnt Orange | Rust's branding, industrial warmth |
| JavaScript | Yellow / Chartreuse | JS's traditional yellow, energetic |
| Go | Cyan / Teal | Go's blue gopher, clean |
| C / C++ | Steel / Silver | Low-level, metallic |
| Swift | Coral / Salmon | Swift's orange-red gradient |
| HTML / CSS | Magenta / Rose | Web fundamentals, distinct from JS |
| Shell / Bash | Green | Terminal green, classic |
| Multi-language | Gradient blend | Blend the top 2-3 language colors |

**Status colors** (for badges and indicators):
- Active: A vibrant green (alive, healthy)
- Paused: Amber / warm yellow (on hold, attention)
- Archived: Muted gray (put away, but not gone)
- Idea: Soft purple / lavender (aspirational, not yet real)

**Semantic colors**:
- Dirty git status: Amber pulse (something needs attention)
- Clean git status: Subtle green or no indicator (everything is fine — don't shout about normal)
- Missing directory: Amber/red warning (something is wrong)
- Error / destructive action: Red (used sparingly)

### 2.2 Typography

**System font stack**: SF Pro for body text, SF Mono for code elements (commit SHAs, file paths, branch names, LOC counts). This keeps the app feeling native to macOS without shipping custom fonts.

**Hierarchy guidance** (the designer should establish exact sizes, but here's the intended weight):

| Role | Usage | Character |
|------|-------|-----------|
| Display | App title, empty-state headlines | Large, light weight, generous tracking |
| Heading | Section headers in detail panel ("GIT", "CONNECTIONS") | Small caps or uppercase, letterspaced, understated |
| Body | Descriptions, commit messages, labels | Regular weight, comfortable line height |
| Caption | Timestamps, secondary info, tooltips | Smaller, reduced opacity, never the focus |
| Mono | SHAs, paths, branch names, file names | Fixed-width, slightly reduced size |
| Stat | LOC count, file count, size numbers | Tabular/monospaced numerals for alignment |

### 2.3 Spacing & Layout Principles

- **8px base grid**: All spacing should derive from multiples of 8 (8, 16, 24, 32, 48, 64...).
- **Generous whitespace**: When in doubt, add more space. Density is achieved through progressive disclosure, not cramming.
- **Content-width constraint**: Side panels and overlays should have a maximum comfortable reading width (~420px for the detail drawer). Don't stretch text to fill available space.
- **Edge-to-edge canvas**: The graph canvas itself has no padding — it extends to all window edges. UI elements float on top.

### 2.4 Elevation & Depth

The app uses a layered depth model:

| Layer | Z-Order | Content | Visual Treatment |
|-------|---------|---------|-----------------|
| Canvas (base) | 0 | Graph background, cluster regions | Deepest, darkest |
| Graph elements | 1 | Nodes, edges, particles | Luminous, self-lit |
| Floating UI | 2 | Sidebar, search bar, filter chips, toasts | Frosted glass (`backdrop-filter: blur`), slight elevation shadow |
| Overlay panels | 3 | Detail drawer, context menus, modals | Stronger blur, higher opacity, soft drop shadow |
| Tooltips | 4 | Hover labels, popovers | Minimal chrome, close to cursor |

The frosted glass (vibrancy) effect on floating UI elements is important — it connects the UI to the living canvas behind it. The graph content should bleed through blurred, creating a sense that the UI is a lens over the data, not a wall in front of it.

### 2.5 Motion Principles

All motion uses spring-based easing (no linear, no ease-in-out). Springs feel organic and physical.

| Interaction | Duration | Character |
|-------------|----------|-----------|
| Panel slide-in/out | ~300ms | Snappy spring, slight overshoot |
| Node hover highlight | ~150ms | Quick fade, no overshoot |
| Filter/search dim | ~400ms | Gradual, relaxed spring |
| Node drag | Real-time | 1:1 tracking, no lag |
| Edge spring (after drag) | ~500ms | Elastic settle, visible wobble |
| Canvas pan/zoom | Momentum | Deceleration curve, Apple Maps feel |
| Node breathing (idle) | ~4s loop | Barely perceptible scale pulse |
| Particle flow | Continuous | Speed varies by git activity |

---

## 3. Wireframe Specifications

Each section below describes one SVG wireframe to produce. The wireframes should be high-fidelity enough to communicate layout, hierarchy, and visual tone — but they are NOT production mockups. Leave room for the implementer to make final decisions on exact pixel values, interaction states, and edge cases.

### Color note for wireframes

Wireframes should use the dark theme with a representative set of node colors to demonstrate how the palette works in context. Include at least 4-5 different language colors in any view that shows the graph.

---

### 3.1 Wireframe: Main View — Neural Graph Canvas

**What this is**: The primary view of the app. The full-screen graph with floating UI elements on top. This is the hero shot — the view that makes people say "whoa."

**What it must communicate**:
- The graph is the app. It fills the entire window. There is no chrome around it except floating UI.
- Nodes are visually distinct by color (language), size (complexity), and glow (activity).
- Edges connect related projects with varying thickness and style.
- The sidebar provides a fast-access list without leaving the graph.
- Search/filter lives at the top, always accessible via keyboard shortcut.

**Required elements**:

The neural graph canvas occupies the entire window background. Show 8-12 representative project nodes scattered across the canvas in a roughly force-directed layout. The nodes should demonstrate variety: different sizes (small side project vs. large app), different colors (at least 4 languages represented), and different activity states (some glowing brightly, some dim). Edges should connect related nodes with visible weight variation — some thick and bright, others thin and faint. At least one cluster region should be visible as a soft background glow encompassing 3-4 related nodes. Show a few animated particles along 2-3 active edges (use small dots along the edge path to suggest motion).

A collapsible sidebar lives on the left edge. It should be shown in its expanded state, approximately 260px wide, with a frosted glass background. The sidebar contains: a small Engram logo or wordmark at top, a search input field, filter chips (e.g., "Python", "React", "Active"), and a scrollable list of project names. Each list item shows a small colored dot (matching node color), the project name, and a secondary line with primary language and last activity. One item in the list should appear highlighted/selected, and the corresponding node on the canvas behind it should be visually emphasized.

A search/command bar floats at the top center of the canvas. Show it in its resting state — a subtle, compact pill-shaped element with a magnifying glass icon and "Search projects... ⌘K" placeholder text. This should feel like macOS Spotlight when invoked but be minimal when resting.

A toast notification floats in the bottom-right area. Show an example: "New project detected: retrolaunch [Add] [Ignore]". This demonstrates the notification flow for newly discovered projects.

**Mood and feel**: The resting state should feel spacious, calm, and alive. The particles should suggest gentle activity. The nodes should feel like they're floating in a deep space. The sidebar and search bar should feel like lightweight glass overlays — present but not heavy.

**Creative latitude**: The designer decides: exact node shape (perfect circles, rounded hexagons, organic blobs?), edge curve style (bezier, smooth step, straight with rounded joins?), how cluster regions are rendered (gradient, outline, filled region?), sidebar visual treatment, search bar styling, and the overall spatial composition of the graph. How do nodes relate to each other spatially? Is there a visual "gravity" pulling related nodes together? How does the eye travel across the canvas?

---

### 3.2 Wireframe: Node Anatomy — Close-Up

**What this is**: A zoomed-in detail view of a single project node and its immediate connections. This is a reference sheet for the node component design, not a separate app view.

**What it must communicate**:
- Every visual property of a node maps to real data.
- The node is not just a circle with a label — it has layered visual elements that each encode meaning.

**Required elements**:

Show a single node at large scale (occupying roughly 30-40% of the wireframe width) with annotated callouts pointing to each visual element.

The **node core** is the main shape, filled with the language color. Its radius/size is proportional to project complexity. Show two sizes side-by-side or annotate the scaling rule.

The **glow halo** radiates outward from the node core. Active projects have a bright, visible glow; dormant projects have minimal or no glow. Show both states.

The **ring indicator** encircles the node. A solid ring means clean git status. A dashed or pulsing ring means dirty (uncommitted changes). Show both.

**Satellite dots** orbit the node — one per git branch. Show a node with 3 branches (3 small dots on a subtle orbital path).

A **hover label** appears near the node when hovered. It contains: project name (bold), primary language, and last commit date. Show this as a floating tooltip with a subtle background.

**Connected edges** radiate outward. Show 3-4 edges leaving the node at different angles. Annotate the visual encoding: thick edge = high weight, thin edge = low weight. One edge should show particle dots (suggesting animation). One edge should be visually distinct as a "manual" edge (different dash pattern or color from auto-edges). One directed edge should have an arrowhead.

An **idea node** variant should be shown nearby — smaller, with a dashed outline instead of solid, and a placeholder icon (lightbulb, seed, or similar) instead of the language-colored core. This represents a project that hasn't been started yet.

A **missing node** variant should appear as well — showing the same language-colored core but with an amber warning badge overlay and the glow dimmed/desaturated.

**Creative latitude**: Node shape, glow rendering technique, ring style, satellite animation suggestion, tooltip design, and how the node variants (idea, missing) feel visually distinct without breaking the overall aesthetic. The designer should decide how much visual weight the glow carries — is it a tight halo or a wide, diffuse bloom?

---

### 3.3 Wireframe: Detail Panel — Slide-Over Drawer

**What this is**: The right-side panel that appears when you click a project node. This is where utility lives — all the detailed information about a single project.

**What it must communicate**:
- Rich project information in a scannable, well-structured layout.
- Quick actions are always within reach (sticky header).
- The panel feels like an extension of the node you clicked — its accent color matches the node.
- The graph canvas is still visible behind the panel (frosted glass).

**Required elements**:

The panel is approximately 420px wide, anchored to the right edge of the window. Behind it, the graph canvas should be partially visible through frosted glass.

**Header section** (sticky — stays at top when scrolling): A miniature version of the project node (glow orb) sits next to the project name in large, bold type. Below the name: a subtitle line with primary language, primary framework, and a status badge (colored pill: "Active" in green). Below that: the file path in monospace, truncated with "~/" prefix. Below that: a row of quick-action icon buttons — VS Code, Terminal, Finder, GitHub. These should feel like a toolbar.

**Overview section**: A description paragraph (2-3 lines of body text). A row of tech stack pills (small badges showing detected frameworks: "react", "tailwind", "vite" etc. — with subtle icons where possible). A horizontal stacked bar chart showing language proportions (TypeScript 65%, CSS 20%, Python 15% — each segment colored to match the language palette). A three-column stat row showing LOC, file count, and disk size in large numeric type with small labels beneath. A tag row with colored pills and a "+" add button.

**Git section**: Current branch name with a clean/dirty indicator. A commit log showing 4-5 recent commits, each with: a commit message (first line), short SHA in monospace, and relative timestamp. Show conventional commit prefixes ("feat:", "fix:") with subtle color differentiation. A compact branch list (3 branches). A dirty file list showing 3-4 changed files with M/A/D/? status indicators, color-coded (green added, amber modified, red deleted, gray untracked).

**Connections section**: A list of 2-3 linked projects. Each shows: the connected project name with its colored dot, the edge type and shared tech ("auto: shared [rust, cpal]"), and a visual weight bar. A "Draw connection" button. A row of cluster pills the project belongs to.

**Meta section** (bottom): Timestamps for "First seen", "Last scanned", "Last opened" in human-friendly format. Action buttons: "Archive", "Rescan", "More (⋯)".

**Design principle for this panel**: The accent color throughout (section dividers, hover states, the header orb, subtle tints) should derive from the project's primary language color. Show this wireframe with a specific language color (e.g., Rust's copper/orange) to demonstrate how the accent propagates. Add a small annotation noting that this color changes per project.

**Creative latitude**: Section divider style, how the language bar chart is rendered, stat number typography, commit log density and visual rhythm, how the sticky header transitions on scroll, the overall scrolling feel. How does the panel handle very long content (many commits, many connections)? The designer should think about rhythm — alternating between dense information blocks and breathing room.

---

### 3.4 Wireframe: Search & Filter — Active State

**What this is**: The main view with the search/command bar expanded and actively filtering the graph. This shows how search transforms the canvas.

**What it must communicate**:
- Search is fast, fluid, and visually dramatic.
- Non-matching nodes don't disappear — they fade to near-invisible. The graph structure remains but focus narrows.
- Filter chips provide faceted filtering by language, tag, status, recency.

**Required elements**:

The search bar is expanded at the top center — wider than its resting state, with a text input showing a typed query (e.g., "wave"). It should feel like Spotlight or Raycast — prominent, centered, authoritative.

On the graph below, demonstrate the filter effect. 2-3 matching nodes (e.g., "WaveForge", "WaveForm") should be fully bright and glowing, perhaps even slightly enlarged. All other nodes should be dramatically dimmed — still visible in position so the spatial context is preserved, but faded to very low opacity. Edges connected to matching nodes remain visible; all other edges are near-invisible.

A row of filter chips sits below the search bar or in the sidebar. Show a few active filter states: "Python" chip selected (highlighted), "Active" chip selected, and other chips in their unselected state. Annotate that multiple chips can be active simultaneously (AND filtering).

An autocomplete dropdown should appear below the search input, showing 3-4 matching results: project names with their colored dot, primary language, and a secondary hint (e.g., last commit). One result should be highlighted as the current selection.

**Creative latitude**: Search bar expansion animation (how does it grow from resting state?), autocomplete dropdown styling, how the filter dimming effect feels (is it opacity? blur? desaturation? some combination?), chip design, and how the spatial context of the graph is preserved during heavy filtering. The designer should consider: what does it look like when only 1 out of 25 nodes matches? The canvas should still feel intentional, not empty.

---

### 3.5 Wireframe: Context Menu & Edge Drawing

**What this is**: A reference for the right-click context menu and the edge-drawing interaction mode. These are interaction states, not full views — they overlay on the main canvas.

**What it must communicate**:
- Right-click on a node reveals contextual actions.
- Edge drawing is a deliberate, guided interaction — hold a modifier key and drag between nodes.

**Required elements**:

**Context menu**: Show a right-click menu floating near a node. The menu should feel native to macOS — not a web-style dropdown, but a real context menu with subtle backdrop blur and shadow. Menu items: "Open in VS Code", "Open in Terminal", "Open in Finder", "Open on GitHub" (with a separator), "Add Tag...", "Change Status ▸" (with a submenu indicator), "Draw Connection", "Change Color...", (separator), "Archive Project", "Remove from Engram" (in a warning/red color). Use appropriate keyboard shortcut hints on the right side of relevant items.

**Edge drawing mode**: Show the state where the user is in the middle of drawing a manual connection. One node (the source) should have a highlighted "connection point" or anchor. A dashed/animated line should extend from that node to the cursor position, which hovers near a potential target node. The target node should show a "drop target" highlight — perhaps a ring or glow indicating it's ready to receive the connection. Other nodes that are valid targets could have a subtle indicator. A small instructional tooltip near the cursor: "Click a project to connect" or similar.

**Creative latitude**: Context menu visual design (how far does it lean native vs. custom?), edge drawing visual language (how does the in-progress edge look — dashed? particle trail? ghosted?), and how source and target nodes signal their roles during the interaction. The designer should consider how this feels with trackpad vs. mouse — is the modifier key workflow clear?

---

### 3.6 Wireframe: Cluster Management

**What this is**: The interaction for creating and managing visual clusters (groups) of projects on the canvas.

**What it must communicate**:
- Clusters are soft spatial groupings, not rigid containers.
- They render as background regions behind their member nodes.
- Clusters can be created, named, colored, collapsed, and dissolved.

**Required elements**:

**Selection state**: Show a rectangular selection marquee being drawn around 3-4 nodes. The selected nodes should be highlighted. A small floating action bar appears near the selection: "Create Group", "Tag All", "Archive All".

**Active cluster**: Show a completed cluster with 3-4 nodes inside it. The cluster renders as a soft, radial background region — like a nebula or attention-head region in a neural network diagram. It should have a name label at the top edge ("Audio Projects") and a very subtle boundary that feels organic rather than geometric. The cluster's color should be distinct but muted — it's a background element, not a foreground one.

**Collapsed cluster**: Show a second cluster in its collapsed state — all member nodes have been condensed into a single "super-node" that is larger than a regular node, shows the cluster name, and has a count badge ("4 projects"). Show a visual hint that it can be expanded (e.g., a small expand icon).

**Overlapping clusters**: Show two cluster regions that partially overlap, with one node belonging to both. The overlapping region should blend gracefully — the two background colors should mix without looking like an error.

**Creative latitude**: Cluster region shape and rendering (hard boundary vs. soft falloff? geometric vs. organic?), how the selection marquee looks and feels, collapsed super-node design, naming/editing flow, and how overlapping clusters blend. This is one of the most visually creative elements — the designer has significant latitude to define the cluster aesthetic. Think about attention-head visualizations, Venn diagrams, and nebula photography as potential inspiration sources.

---

### 3.7 Wireframe: Empty State — First Launch

**What this is**: What the user sees the very first time they open Engram, before any projects have been scanned.

**What it must communicate**:
- Engram is beautiful even before it has data.
- The onboarding is warm, simple, and fast — just point it at your projects folder.
- The neural graph metaphor is teased even in the empty state.

**Required elements**:

The canvas should not be blank. Show a subtle ambient animation suggestion — perhaps faint, ghosted nodes and edges that hint at the graph to come, or a gentle particle field, or a neural network pattern that's purely decorative. The app should feel alive even before it has real data.

A centered onboarding card or dialog (not a full-screen modal — let the ambient canvas peek through). The card should contain: the Engram wordmark or logo, a short tagline (e.g., "Your projects, connected." or similar — the designer may suggest alternatives), a brief one-sentence description, and a prominent "Choose Projects Folder" button that will trigger a native macOS folder picker. Below the button, a subtle hint about what happens next: "Engram will scan your projects and build your graph."

**Creative latitude**: Ambient empty-state animation, onboarding card design, wordmark/logo treatment, tagline copy, and the overall emotional tone of the first impression. This view is critical — it's the first thing the user sees. It should feel premium and inviting, not utilitarian. Consider how apps like Linear, Raycast, or Arc handle their empty/onboarding states.

---

### 3.8 Wireframe: Settings View

**What this is**: The app settings/preferences panel. This is a utilitarian view — it doesn't need to be flashy, but it should feel consistent with the overall design language.

**What it must communicate**:
- Configuration is simple and well-organized.
- The most important setting (projects folder) is prominent.
- Advanced settings are accessible but not overwhelming.

**Required elements**:

This could be a modal dialog, a full-view takeover, or a slide-over panel — the designer decides which fits best. It should have clear sections:

**General**: Projects root directory (with a path display and "Change" button), scan interval (dropdown or slider: 15 / 30 / 60 min), app launch behavior (start minimized? start with scan?).

**Appearance**: Theme toggle (dark is default and primary — but acknowledge the setting exists), canvas background style options (if we offer variations), auto-edge visibility toggle, auto-edge minimum weight threshold (slider: 0.0–1.0), ambient mode delay (seconds before idle animation kicks in).

**Graph**: Force-layout toggle (on/off), default new-node behavior (pinned vs. floating), particle animation toggle (for performance).

**Updates**: Current version display, "Check for Updates" button, auto-update toggle, link to changelog.

**About**: Engram wordmark, version number, "Built with Tauri, React, and Python", link to GitHub repo.

**Creative latitude**: Settings layout structure (tabbed? scrolling sections? sidebar navigation?), control styling (toggles, sliders, dropdowns), and how much personality to inject. Settings pages are often boring — the designer has an opportunity to make this feel more polished than expected, without overdesigning it.

---

### 3.9 Wireframe: Ambient Mode

**What this is**: The idle state of the graph when the app hasn't been interacted with for 60+ seconds. This turns the app into a living wallpaper of the user's work.

**What it must communicate**:
- The graph is alive even when you're not using it.
- It's beautiful enough to leave on a second monitor.
- Any interaction instantly snaps back to the functional UI.

**Required elements**:

Show the graph in a subtly different state from the active view. The floating UI elements (sidebar, search bar) should be hidden or faded to near-invisible. The nodes should have slightly enhanced glow. The particle animations along edges should be the primary visual focus — flowing, pulsing, mesmerizing. The canvas might very slowly drift or rotate.

There should be a visual quality shift — like the difference between a screensaver and a desktop. The ambient state should feel dreamier, more atmospheric. Consider: increased bloom/glow, slower animation speeds, perhaps a subtle vignette darkening the edges of the canvas, enhanced depth-of-field (background nodes blurred slightly).

**Exit state**: Show (via annotation) that any mouse movement, keypress, or trackpad touch instantly fades the UI back in (sidebar, search) and returns to the active state.

**Creative latitude**: This is the most creatively open wireframe. The designer should interpret "living neural network screensaver" however they see fit. The key constraint is that it must use the same graph data as the active view — it's not a separate animation, it's the real graph in a relaxed visual mode. Think about what makes neural network visualizations captivating in research papers and conference talks, and bring that energy here.

---

## 4. Component Reference

These are reusable components that appear across multiple wireframes. The designer should establish consistent treatments for each.

### 4.1 Status Badge

A small pill-shaped badge showing project status. Four variants: Active (green), Paused (amber), Archived (gray), Idea (purple). Used in the detail panel header and sidebar list items.

### 4.2 Tag Chip

A small colored pill with tag name text. Tags have user-defined colors. Used in the detail panel, sidebar filters, and potentially as labels on the canvas. Should feel lightweight — not like buttons, more like metadata annotations. Include a variant with an "×" dismiss icon for editing contexts.

### 4.3 Quick Action Button

Icon-only buttons used in the detail panel header (VS Code, Terminal, Finder, GitHub). Each has an icon and a tooltip on hover. The hover state should include a subtle glow matching the current project's accent color. These are high-frequency interaction targets — they should feel snappy and responsive.

### 4.4 Stat Block

A numeric display used for LOC, file count, and disk size. Large number on top (tabular numerals), small label beneath. Three of these sit in a row. They should feel like instrument readings — clean, precise, scannable.

### 4.5 Commit Entry

A compact list item for the git commit log. Shows: commit message (truncated), short SHA (monospace), relative timestamp. Conventional commit prefixes (feat:, fix:, refactor:, docs:, test:) can have subtle color coding. Used in the detail panel's git section.

### 4.6 Weight Bar

A small horizontal bar visualization showing edge weight (0.0–1.0). Filled portion is tinted with the relevant color; unfilled portion is muted. Used in the detail panel's connections section. Should feel like a confidence meter or signal strength indicator.

### 4.7 Toast Notification

A floating notification card that appears at a consistent position (bottom-right recommended). Used for "New project detected" alerts, scan completion, update available, etc. Should have: a message, 1-2 action buttons, and auto-dismiss after a timeout. Frosted glass background, consistent with the floating UI layer.

### 4.8 Language Dot

A tiny colored circle (8-12px) representing a project's primary language. Used everywhere a project is listed outside the graph (sidebar, connections list, autocomplete). Always matches the node color on the canvas.

---

## 5. Appendix: Data Context

For the designer's reference — the real data this app will visualize. Use these to populate wireframes with realistic content.

### Sample Projects (from the user's actual VSCode-Projects folder)

| Name | Primary Language | Frameworks | Status | LOC (est.) | Description |
|------|-----------------|------------|--------|-----------|-------------|
| WaveForge | Rust | cpal, tokio | Active | 4,200 | Real-time audio synthesis engine |
| WaveForm | Rust | cpal | Active | 2,800 | Waveform visualization tool |
| Chatot | TypeScript | React, Vite, Tailwind | Active | 3,500 | Chat application |
| aero | TypeScript | React, Electron | Paused | 5,100 | Desktop productivity app |
| boids | Python | pygame | Archived | 800 | Flocking simulation |
| RVC-Portal | Python | FastAPI, torch | Active | 6,200 | Voice conversion interface |
| retrolaunch | Swift | SwiftUI | Active | 1,900 | Retro game launcher |
| chordprog | TypeScript | React, Tone.js | Paused | 1,400 | Chord progression generator |
| Sentinel | Python | FastAPI | Active | 3,800 | Monitoring dashboard |
| dino | JavaScript | Canvas API | Archived | 600 | Chrome dino game clone |
| micrOS | C | — | Idea | 200 | Microcontroller operating system |
| Oxide | Rust | — | Active | 2,100 | Systems programming experiments |

### Sample Edges

| Source | Target | Type | Weight | Shared |
|--------|--------|------|--------|--------|
| WaveForge | WaveForm | auto_tech | 0.85 | rust, cpal |
| WaveForge | RVC-Portal | manual | 0.40 | "audio pipeline reference" |
| Chatot | aero | auto_tech | 0.72 | typescript, react, vite |
| Chatot | chordprog | auto_dep | 0.55 | react, vite, tailwind |
| RVC-Portal | Sentinel | auto_tech | 0.68 | python, fastapi |
| boids | dino | auto_tech | 0.30 | python/js game projects |
| Oxide | WaveForge | auto_tech | 0.60 | rust |

### Sample Clusters

| Name | Members | Color Direction |
|------|---------|----------------|
| Audio Projects | WaveForge, WaveForm, RVC-Portal, chordprog | Warm (amber/copper region) |
| Rust | WaveForge, WaveForm, Oxide | Copper/orange region |
| Web Apps | Chatot, aero, chordprog | Blue/electric region |

---

## 6. Deliverables Checklist

The designer should produce the following SVG files:

1. **main-view.svg** — Full neural graph canvas with sidebar, search, and toast (Section 3.1)
2. **node-anatomy.svg** — Close-up node reference with annotated callouts (Section 3.2)
3. **detail-panel.svg** — Slide-over drawer with full content layout (Section 3.3)
4. **search-filter.svg** — Active search/filter state showing graph dimming (Section 3.4)
5. **context-edge-drawing.svg** — Context menu and edge drawing interaction (Section 3.5)
6. **clusters.svg** — Cluster creation, active, collapsed, and overlapping states (Section 3.6)
7. **empty-state.svg** — First launch onboarding (Section 3.7)
8. **settings.svg** — Settings/preferences view (Section 3.8)
9. **ambient-mode.svg** — Idle screensaver state (Section 3.9)

Each wireframe should be self-contained and render clearly at 1440x900 or larger viewport dimensions.
