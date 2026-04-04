"""Tests for the edge computation engine.

Covers the three layers of ``sidecar/scanner/edge_computer.py``:

1. **Pure functions** — ``normalize_pair``, ``compute_tech_similarity``,
   ``compute_dep_overlap``.
2. **DB-interacting orchestration** — ``compute_edges`` with real SQLite
   databases created via the migration runner to guarantee schema parity
   with production.

Every integration test uses an isolated SQLite database in ``tmp_path``
with real migrations applied.  No real project directories are referenced.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, select

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.engine import get_engine  # noqa: E402
from db.migrations.migrator import DatabaseMigrator  # noqa: E402
from models import Config, Edge, Project  # noqa: E402
from scanner.edge_computer import (  # noqa: E402
    DEFAULT_MIN_WEIGHT,
    EdgeComputationResult,
    compute_dep_overlap,
    compute_edges,
    compute_tech_similarity,
    normalize_pair,
)
from utils.ulid import generate_ulid  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
)
_NOW = "2025-06-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_project_counter = 0


@pytest.fixture()
def db_session(tmp_path: Path) -> Iterator[Session]:
    """Create an isolated DB, run migrations, and yield a session.

    The migration inserts default config rows (including
    ``auto_edge_min_weight = 0.3``).

    Yields:
        An active SQLModel session backed by a fresh SQLite database.
    """
    db_path = tmp_path / "test_edge_computer.db"
    migrator = DatabaseMigrator(db_path, _MIGRATIONS_DIR)
    success = migrator.migrate()
    assert success, "Migration failed during test setup"
    engine = get_engine(db_path)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(
    session: Session,
    *,
    name: str,
    frameworks: list[str] | None = None,
    languages: dict[str, float] | None = None,
    path: str | None = None,
) -> Project:
    """Insert a project into the database and return the ORM instance.

    Generates a unique path for each call to avoid UNIQUE constraint
    violations on the ``path`` column.

    Args:
        session: Active SQLModel session.
        name: Human-readable project name.
        frameworks: List of framework names (stored as JSON array).
        languages: Language-to-percentage mapping (stored as JSON object).
        path: Optional explicit path.  Auto-generated if omitted.

    Returns:
        The inserted and refreshed ``Project`` instance.
    """
    global _project_counter
    _project_counter += 1
    if path is None:
        path = f"/tmp/test-edge-computer-{_project_counter}"

    project = Project(
        id=generate_ulid(),
        name=name,
        path=path,
        frameworks=json.dumps(frameworks) if frameworks else None,
        languages=json.dumps(languages) if languages else None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _create_manual_edge(
    session: Session,
    source_id: str,
    target_id: str,
    weight: float = 0.5,
) -> Edge:
    """Insert a manual edge and return the ORM instance.

    Args:
        session: Active SQLModel session.
        source_id: Source project ULID.
        target_id: Target project ULID.
        weight: Edge weight (default 0.5).

    Returns:
        The inserted and refreshed ``Edge`` instance.
    """
    edge = Edge(
        id=generate_ulid(),
        source_id=source_id,
        target_id=target_id,
        edge_type="manual",
        weight=weight,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


# ===========================================================================
# Layer 1: Pure Function Tests
# ===========================================================================


class TestNormalizePair:
    """Tests for ``normalize_pair`` — lexicographic ID ordering."""

    def test_already_ordered(self) -> None:
        """IDs already in ascending order are returned unchanged."""
        assert normalize_pair("AAA", "BBB") == ("AAA", "BBB")

    def test_reversed(self) -> None:
        """IDs in descending order are swapped to ascending."""
        assert normalize_pair("BBB", "AAA") == ("AAA", "BBB")

    def test_equal_ids(self) -> None:
        """Identical IDs are returned as-is (no swap needed)."""
        assert normalize_pair("AAA", "AAA") == ("AAA", "AAA")


class TestComputeTechSimilarity:
    """Tests for ``compute_tech_similarity`` — Jaccard similarity."""

    def test_identical_stacks(self) -> None:
        """Identical frameworks and languages produce a score of 1.0."""
        frameworks = ["react", "tailwind"]
        languages = {"typescript": 0.6, "css": 0.2}

        score, shared = compute_tech_similarity(
            frameworks, languages, frameworks, languages
        )

        assert score == pytest.approx(1.0)
        assert shared == sorted(["react", "tailwind", "typescript", "css"])

    def test_disjoint_stacks(self) -> None:
        """Completely disjoint stacks produce a score of 0.0."""
        score, shared = compute_tech_similarity(
            ["react"], {"typescript": 0.8},
            ["django"], {"python": 0.9},
        )

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_partial_overlap(self) -> None:
        """Partial overlap returns the correct Jaccard score.

        Features A = {react, tailwind, typescript, css} (4 items)
        Features B = {react, vue, typescript, python}   (4 items)
        Intersection = {react, typescript}               (2 items)
        Union = {react, tailwind, typescript, css, vue, python} (6 items)
        Score = 2 / 6 = 0.3333...
        """
        score, shared = compute_tech_similarity(
            ["react", "tailwind"], {"typescript": 0.6, "css": 0.2},
            ["react", "vue"], {"typescript": 0.7, "python": 0.3},
        )

        assert score == pytest.approx(2.0 / 6.0)
        assert shared == ["react", "typescript"]

    def test_both_empty(self) -> None:
        """Both projects with no frameworks or languages return 0.0."""
        score, shared = compute_tech_similarity([], {}, [], {})

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_one_empty(self) -> None:
        """One project with features, the other empty, returns 0.0."""
        score, shared = compute_tech_similarity(
            ["react"], {"typescript": 0.9},
            [], {},
        )

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_language_keys_only(self) -> None:
        """Language percentage values are ignored; only keys matter.

        Two projects with the same language keys but different
        percentages should produce the same score.
        """
        score_a, shared_a = compute_tech_similarity(
            [], {"python": 0.9, "javascript": 0.1},
            [], {"python": 0.1, "javascript": 0.9},
        )
        score_b, shared_b = compute_tech_similarity(
            [], {"python": 0.5, "javascript": 0.5},
            [], {"python": 0.5, "javascript": 0.5},
        )

        assert score_a == pytest.approx(1.0)
        assert score_b == pytest.approx(1.0)
        assert shared_a == shared_b

    def test_shared_features_sorted(self) -> None:
        """The returned shared features list is sorted alphabetically."""
        score, shared = compute_tech_similarity(
            ["zeppelin", "alpha"], {"mango": 0.5},
            ["alpha", "zeppelin"], {"mango": 0.3},
        )

        assert shared == sorted(shared)
        assert shared == ["alpha", "mango", "zeppelin"]


class TestComputeDepOverlap:
    """Tests for ``compute_dep_overlap`` — dependency overlap ratio."""

    def test_identical_deps(self) -> None:
        """Identical dependency sets produce a score of 1.0."""
        deps = frozenset({"react", "zustand", "vite"})

        score, shared = compute_dep_overlap(deps, deps)

        assert score == pytest.approx(1.0)
        assert set(shared) == {"react", "zustand", "vite"}

    def test_disjoint_deps(self) -> None:
        """Completely disjoint sets produce a score of 0.0."""
        score, shared = compute_dep_overlap(
            frozenset({"react", "zustand"}),
            frozenset({"django", "flask"}),
        )

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_subset_relationship(self) -> None:
        """When A is a subset of B, the score is 1.0.

        A = {react, zustand} (2 items)
        B = {react, zustand, vite, tailwind} (4 items)
        Shared = {react, zustand} (2 items)
        Score = 2 / min(2, 4) = 2 / 2 = 1.0
        """
        score, shared = compute_dep_overlap(
            frozenset({"react", "zustand"}),
            frozenset({"react", "zustand", "vite", "tailwind"}),
        )

        assert score == pytest.approx(1.0)
        assert set(shared) == {"react", "zustand"}

    def test_partial_overlap(self) -> None:
        """Partial overlap returns the correct ratio.

        A = {react, zustand, vite, typescript} (4 items)
        B = {react, zustand, vite, django, flask, python} (6 items)
        Shared = {react, zustand, vite} (3 items)
        Score = 3 / min(4, 6) = 3 / 4 = 0.75
        """
        score, shared = compute_dep_overlap(
            frozenset({"react", "zustand", "vite", "typescript"}),
            frozenset({"react", "zustand", "vite", "django", "flask", "python"}),
        )

        assert score == pytest.approx(0.75)
        assert set(shared) == {"react", "zustand", "vite"}

    def test_one_empty(self) -> None:
        """One empty dependency set returns 0.0."""
        score, shared = compute_dep_overlap(
            frozenset({"react"}),
            frozenset(),
        )

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_both_empty(self) -> None:
        """Both empty dependency sets return 0.0."""
        score, shared = compute_dep_overlap(frozenset(), frozenset())

        assert score == pytest.approx(0.0)
        assert shared == []

    def test_shared_deps_sorted(self) -> None:
        """The returned shared deps list is sorted alphabetically."""
        score, shared = compute_dep_overlap(
            frozenset({"zustand", "react", "axios"}),
            frozenset({"zustand", "react", "axios", "vite"}),
        )

        assert shared == sorted(shared)
        assert shared == ["axios", "react", "zustand"]


# ===========================================================================
# Layer 3: DB Integration Tests
# ===========================================================================


class TestComputeEdges:
    """Integration tests for ``compute_edges`` — full DB lifecycle."""

    def test_creates_auto_tech_edge_above_threshold(
        self, db_session: Session
    ) -> None:
        """An auto_tech edge is created when tech similarity exceeds the threshold.

        Two projects sharing all frameworks and languages should produce
        a Jaccard score of 1.0, well above the 0.3 default threshold.
        """
        p1 = _create_project(
            db_session,
            name="proj-alpha",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.7, "css": 0.3},
        )
        p2 = _create_project(
            db_session,
            name="proj-beta",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.7, "css": 0.3},
        )

        result = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )

        assert result.created >= 1

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        assert len(edges) == 1

        edge = edges[0]
        src, tgt = normalize_pair(p1.id, p2.id)
        assert edge.source_id == src
        assert edge.target_id == tgt
        assert edge.weight == pytest.approx(1.0)

        # Verify metadata JSON structure.
        meta = json.loads(edge.edge_metadata)
        assert "shared_features" in meta
        assert "score" in meta
        assert set(meta["shared_features"]) == {"react", "tailwind", "typescript", "css"}

    def test_creates_auto_dep_edge_above_threshold(
        self, db_session: Session
    ) -> None:
        """An auto_dep edge is created when dependency overlap exceeds the threshold."""
        p1 = _create_project(db_session, name="proj-dep-a")
        p2 = _create_project(db_session, name="proj-dep-b")

        dep_map = {
            p1.id: frozenset({"react", "zustand", "vite"}),
            p2.id: frozenset({"react", "zustand", "vite"}),
        }

        result = compute_edges(
            db_session, [p1, p2], dep_map=dep_map, min_weight=0.3
        )

        assert result.created >= 1

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_dep")
        ).all()
        assert len(edges) == 1

        edge = edges[0]
        assert edge.weight == pytest.approx(1.0)

        meta = json.loads(edge.edge_metadata)
        assert "shared_deps" in meta
        assert "score" in meta
        assert set(meta["shared_deps"]) == {"react", "zustand", "vite"}

    def test_skips_edge_below_threshold(self, db_session: Session) -> None:
        """No edge is created when similarity falls below ``min_weight``.

        Features A = {react, a1, a2, a3, a4} (5 items)
        Features B = {react, b1, b2, b3, b4} (5 items)
        Intersection = {react} (1 item)
        Union = 9 items
        Score = 1/9 = 0.111... < 0.3
        """
        p1 = _create_project(
            db_session,
            name="proj-lo-a",
            frameworks=["react", "a1", "a2", "a3", "a4"],
            languages={},
        )
        p2 = _create_project(
            db_session,
            name="proj-lo-b",
            frameworks=["react", "b1", "b2", "b3", "b4"],
            languages={},
        )

        compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        assert len(edges) == 0

    def test_updates_existing_edge_weight(
        self, db_session: Session
    ) -> None:
        """Running ``compute_edges`` twice updates an edge when similarity changes."""
        p1 = _create_project(
            db_session,
            name="proj-upd-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )
        p2 = _create_project(
            db_session,
            name="proj-upd-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )

        # First run: score = 1.0 (identical stacks).
        result1 = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )
        assert result1.created >= 1

        edge_before = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).first()
        assert edge_before is not None
        weight_before = edge_before.weight
        updated_at_before = edge_before.updated_at

        # Modify p2's frameworks to reduce similarity.
        p2.frameworks = json.dumps(["react", "vue", "nuxt", "pinia"])
        p2.languages = json.dumps({"typescript": 0.5, "python": 0.5})
        db_session.add(p2)
        db_session.commit()
        db_session.refresh(p2)

        # Second run: similarity changes.
        result2 = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.1
        )
        assert result2.updated >= 1

        edge_after = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).first()
        assert edge_after is not None
        assert edge_after.weight != pytest.approx(weight_before)
        assert edge_after.updated_at >= updated_at_before

    def test_deletes_edge_below_threshold(
        self, db_session: Session
    ) -> None:
        """An existing edge is deleted when similarity drops below the threshold."""
        p1 = _create_project(
            db_session,
            name="proj-del-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )
        p2 = _create_project(
            db_session,
            name="proj-del-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )

        # First run: score = 1.0, edge created.
        compute_edges(db_session, [p1, p2], dep_map={}, min_weight=0.3)
        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        assert len(edges) == 1

        # Make stacks completely disjoint.
        p2.frameworks = json.dumps(["django", "flask", "celery", "gunicorn"])
        p2.languages = json.dumps({"python": 0.9, "shell": 0.1})
        db_session.add(p2)
        db_session.commit()
        db_session.refresh(p2)

        # Second run: score drops to 0.0, edge deleted.
        result2 = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )
        assert result2.deleted >= 1

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        assert len(edges) == 0

    def test_manual_edges_untouched(self, db_session: Session) -> None:
        """Manual edges are never modified or deleted by ``compute_edges``."""
        p1 = _create_project(
            db_session,
            name="proj-man-a",
            frameworks=["react"],
            languages={"typescript": 0.9},
        )
        p2 = _create_project(
            db_session,
            name="proj-man-b",
            frameworks=["django"],
            languages={"python": 0.9},
        )

        manual = _create_manual_edge(db_session, p1.id, p2.id, weight=0.8)
        original_weight = manual.weight
        original_metadata = manual.edge_metadata
        original_updated = manual.updated_at

        # Run compute_edges — should not touch the manual edge.
        compute_edges(db_session, [p1, p2], dep_map={}, min_weight=0.3)

        # Re-fetch from DB to ensure no changes.
        refreshed = db_session.exec(
            select(Edge).where(Edge.id == manual.id)
        ).first()
        assert refreshed is not None
        assert refreshed.edge_type == "manual"
        assert refreshed.weight == pytest.approx(original_weight)
        assert refreshed.edge_metadata == original_metadata
        assert refreshed.updated_at == original_updated

    def test_stale_edge_cleanup(self, db_session: Session) -> None:
        """Auto edges involving removed projects are deleted as stale.

        First run with projects [A, B, C] creates edges.
        Second run with [A, C] removes all auto edges that involved B.
        """
        p_a = _create_project(
            db_session,
            name="proj-stale-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.9},
        )
        p_b = _create_project(
            db_session,
            name="proj-stale-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )
        p_c = _create_project(
            db_session,
            name="proj-stale-c",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.7},
        )

        # First run: all three projects.
        compute_edges(
            db_session, [p_a, p_b, p_c], dep_map={}, min_weight=0.3
        )
        edges_round1 = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        # With 3 projects, up to 3 pairs (AB, AC, BC).
        assert len(edges_round1) >= 1

        # Second run: B removed from list.
        result2 = compute_edges(
            db_session, [p_a, p_c], dep_map={}, min_weight=0.3
        )

        # All edges involving B should be deleted.
        remaining = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        for edge in remaining:
            assert edge.source_id != p_b.id
            assert edge.target_id != p_b.id

        # The stale edges should be counted as deleted.
        assert result2.deleted >= 1

    def test_edge_metadata_valid_json(self, db_session: Session) -> None:
        """Every auto edge has valid JSON metadata with expected keys."""
        p1 = _create_project(
            db_session,
            name="proj-meta-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )
        p2 = _create_project(
            db_session,
            name="proj-meta-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.7},
        )

        dep_map = {
            p1.id: frozenset({"react", "zustand"}),
            p2.id: frozenset({"react", "zustand"}),
        }

        compute_edges(db_session, [p1, p2], dep_map=dep_map, min_weight=0.3)

        all_auto = db_session.exec(
            select(Edge).where(Edge.edge_type.in_(["auto_tech", "auto_dep"]))
        ).all()
        assert len(all_auto) >= 1

        for edge in all_auto:
            assert edge.edge_metadata is not None
            meta = json.loads(edge.edge_metadata)
            assert isinstance(meta, dict)
            assert "score" in meta

            if edge.edge_type == "auto_tech":
                assert "shared_features" in meta
                assert isinstance(meta["shared_features"], list)
            elif edge.edge_type == "auto_dep":
                assert "shared_deps" in meta
                assert isinstance(meta["shared_deps"], list)

    def test_consistent_source_target_ordering(
        self, db_session: Session
    ) -> None:
        """Edge source/target ordering is consistent regardless of input order.

        Passing ``[A, B]`` and ``[B, A]`` should produce the same
        ``(source_id, target_id)`` pair.
        """
        p1 = _create_project(
            db_session,
            name="proj-ord-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.9},
        )
        p2 = _create_project(
            db_session,
            name="proj-ord-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )

        # Run with [p1, p2].
        compute_edges(db_session, [p1, p2], dep_map={}, min_weight=0.3)
        edge_first = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).first()
        assert edge_first is not None
        src_first = edge_first.source_id
        tgt_first = edge_first.target_id

        # Delete the edge and re-run with reversed order [p2, p1].
        db_session.delete(edge_first)
        db_session.commit()

        compute_edges(db_session, [p2, p1], dep_map={}, min_weight=0.3)
        edge_second = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).first()
        assert edge_second is not None

        assert edge_second.source_id == src_first
        assert edge_second.target_id == tgt_first

    def test_reads_min_weight_from_config(
        self, db_session: Session
    ) -> None:
        """When ``min_weight=None``, the threshold is read from the config table.

        The migration seeds ``auto_edge_min_weight = 0.3``.  We override
        it to ``0.1`` and verify that a low-similarity edge IS created.
        """
        # Two projects with low overlap.
        # Features A = {react, a1, a2, a3} (4), B = {react, b1, b2, b3} (4)
        # Intersection = {react} (1), Union = 7
        # Score = 1/7 = 0.1428... which is > 0.1 but < 0.3
        p1 = _create_project(
            db_session,
            name="proj-cfg-a",
            frameworks=["react", "a1", "a2", "a3"],
            languages={},
        )
        p2 = _create_project(
            db_session,
            name="proj-cfg-b",
            frameworks=["react", "b1", "b2", "b3"],
            languages={},
        )

        # Override config to lower the threshold to 0.1.
        config_entry = db_session.exec(
            select(Config).where(Config.key == "auto_edge_min_weight")
        ).first()
        assert config_entry is not None
        config_entry.value = "0.1"
        db_session.add(config_entry)
        db_session.commit()

        # Run with min_weight=None so it reads from config.
        compute_edges(db_session, [p1, p2], dep_map={}, min_weight=None)

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        # Score ~0.143 > 0.1, so the edge should be created.
        assert len(edges) == 1

    def test_default_min_weight_when_config_absent(
        self, db_session: Session
    ) -> None:
        """Without a config entry the default 0.3 threshold applies.

        Two projects with overlap 0.25 (below 0.3) should NOT produce
        an edge.

        Features A = {react, a1, a2, a3, a4, a5} (6)
        Features B = {react, b1, a1, b2, b3, b4} (6)
        Intersection = {react, a1} (2), Union = 10
        Score = 2/10 = 0.2 < 0.3
        """
        # Delete the seeded config entry so the default is used.
        config_entry = db_session.exec(
            select(Config).where(Config.key == "auto_edge_min_weight")
        ).first()
        if config_entry is not None:
            db_session.delete(config_entry)
            db_session.commit()

        p1 = _create_project(
            db_session,
            name="proj-noconf-a",
            frameworks=["react", "a1", "a2", "a3", "a4", "a5"],
            languages={},
        )
        p2 = _create_project(
            db_session,
            name="proj-noconf-b",
            frameworks=["react", "a1", "b2", "b3", "b4", "b5"],
            languages={},
        )

        # Score = 2/10 = 0.2 < DEFAULT_MIN_WEIGHT (0.3).
        compute_edges(db_session, [p1, p2], dep_map={}, min_weight=None)

        edges = db_session.exec(
            select(Edge).where(Edge.edge_type == "auto_tech")
        ).all()
        assert len(edges) == 0

    def test_result_counts_accurate(self, db_session: Session) -> None:
        """The ``EdgeComputationResult`` counters match actual DB state.

        Run 1: creates edges (verify ``created`` count).
        Run 2: no changes (verify ``unchanged`` count).
        """
        p1 = _create_project(
            db_session,
            name="proj-cnt-a",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.8},
        )
        p2 = _create_project(
            db_session,
            name="proj-cnt-b",
            frameworks=["react", "tailwind"],
            languages={"typescript": 0.7},
        )

        # Run 1: edges should be created.
        result1 = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )

        # Count edges actually in DB.
        db_edges = db_session.exec(
            select(Edge).where(Edge.edge_type.in_(["auto_tech", "auto_dep"]))
        ).all()
        assert result1.created == len(db_edges)
        assert result1.updated == 0
        assert result1.deleted == 0
        assert result1.unchanged == 0

        # Verify EdgeComputationResult is a frozen dataclass with expected fields.
        assert isinstance(result1, EdgeComputationResult)

        # Run 2: identical data, nothing should change.
        result2 = compute_edges(
            db_session, [p1, p2], dep_map={}, min_weight=0.3
        )
        assert result2.created == 0
        assert result2.updated == 0
        assert result2.deleted == 0
        assert result2.unchanged == result1.created
