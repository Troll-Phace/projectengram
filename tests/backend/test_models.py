"""Tests for SQLModel ORM models against the real SQLite migration schema.

Validates CRUD operations, ULID generation, JSON column round-trips,
cascade deletes, and relationship traversal for all 8 Engram models.
"""

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------
_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from db.engine import get_engine  # noqa: E402
from db.migrations.migrator import DatabaseMigrator  # noqa: E402
from models import (  # noqa: E402
    Cluster,
    Config,
    Edge,
    NodePosition,
    Project,
    ProjectCluster,
    ProjectTag,
    Tag,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "sidecar" / "db" / "migrations"
_ULID_CHARSET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
_NOW = "2025-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(**overrides: object) -> Project:
    """Return a Project instance with sensible defaults for all required fields."""
    defaults = dict(
        name="test-project",
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_edge(source_id: str, target_id: str, **overrides: object) -> Edge:
    """Return an Edge instance with sensible defaults."""
    defaults = dict(
        source_id=source_id,
        target_id=target_id,
        edge_type="manual",
        weight=0.5,
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    return Edge(**defaults)


def _make_tag(**overrides: object) -> Tag:
    """Return a Tag instance with sensible defaults."""
    defaults = dict(
        name="backend",
        color="#FF0000",
        created_at=_NOW,
    )
    defaults.update(overrides)
    return Tag(**defaults)


def _make_cluster(**overrides: object) -> Cluster:
    """Return a Cluster instance with sensible defaults."""
    defaults = dict(
        name="web",
        color="#00FF00",
        created_at=_NOW,
        updated_at=_NOW,
    )
    defaults.update(overrides)
    return Cluster(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def migrated_engine(tmp_path):
    """Create a temp DB, run the real migration, return engine with PRAGMAs."""
    db_path = tmp_path / "test_models.db"
    migrator = DatabaseMigrator(db_path, _MIGRATIONS_DIR)
    success = migrator.migrate()
    assert success, "Migration failed during test setup"
    engine = get_engine(db_path)
    return engine


@pytest.fixture()
def session(migrated_engine) -> Iterator[Session]:
    """Yield a SQLModel Session bound to a fresh migrated DB."""
    with Session(migrated_engine) as s:
        yield s


# ===========================================================================
# Test classes
# ===========================================================================


class TestULIDGeneration:
    """Verify that ULID primary keys are auto-generated correctly."""

    def test_ulid_auto_generated(self) -> None:
        """A new Project instance has a ULID id before commit."""
        project = _make_project()
        assert project.id is not None
        assert len(project.id) == 26

    def test_ulid_unique_across_instances(self) -> None:
        """Two Project instances receive different ULID ids."""
        p1 = _make_project(name="project-one")
        p2 = _make_project(name="project-two")
        assert p1.id != p2.id

    def test_ulid_format(self) -> None:
        """ULID is 26 characters using the Crockford Base32 charset."""
        project = _make_project()
        uid = project.id
        assert len(uid) == 26, f"Expected 26 chars, got {len(uid)}"
        assert set(uid).issubset(_ULID_CHARSET), (
            f"ULID contains invalid characters: {set(uid) - _ULID_CHARSET}"
        )


class TestProjectCRUD:
    """Create, read, update, and delete operations on the Project model."""

    def test_create_project_with_defaults(self, session: Session) -> None:
        """Create with only required fields; verify defaults are applied."""
        project = _make_project()
        session.add(project)
        session.commit()
        session.refresh(project)

        assert len(project.id) == 26
        assert project.status == "active"
        assert project.git_dirty is False
        assert project.missing is False
        assert project.name == "test-project"

    def test_create_project_all_fields(self, session: Session) -> None:
        """Create with every field populated, including JSON columns."""
        project = Project(
            name="full-project",
            path="/tmp/full-project",
            description="A fully populated project",
            status="paused",
            primary_language="python",
            languages=json.dumps({"python": 0.8, "sql": 0.2}),
            frameworks=json.dumps(["fastapi", "sqlmodel"]),
            package_manager="pip",
            loc=10000,
            file_count=150,
            size_bytes=2048000,
            git_remote_url="https://github.com/test/repo",
            git_branch="main",
            git_dirty=True,
            git_last_commit_hash="abc123def",
            git_last_commit_date="2025-06-01T12:00:00Z",
            git_last_commit_msg="feat: add feature",
            git_branch_count=5,
            color_override="#FF5500",
            icon_override="brain",
            notes="Important project",
            missing=False,
            deleted_at=None,
            last_scanned_at="2025-06-01T12:00:00Z",
            last_opened_at="2025-06-01T11:00:00Z",
            created_at=_NOW,
            updated_at=_NOW,
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        assert project.name == "full-project"
        assert project.status == "paused"
        assert project.git_dirty is True
        assert project.loc == 10000
        assert project.git_branch_count == 5

    def test_read_project_by_id(self, session: Session) -> None:
        """session.get(Project, id) round-trips correctly."""
        project = _make_project(name="read-me")
        session.add(project)
        session.commit()
        pid = project.id

        fetched = session.get(Project, pid)
        assert fetched is not None
        assert fetched.name == "read-me"
        assert fetched.id == pid

    def test_update_project_fields(self, session: Session) -> None:
        """Modify fields, commit, refresh, verify changes persist."""
        project = _make_project(name="before-update")
        session.add(project)
        session.commit()

        project.name = "after-update"
        project.status = "paused"
        project.loc = 9999
        session.add(project)
        session.commit()
        session.refresh(project)

        assert project.name == "after-update"
        assert project.status == "paused"
        assert project.loc == 9999

    def test_delete_project(self, session: Session) -> None:
        """Delete project, verify it is gone."""
        project = _make_project(name="to-delete")
        session.add(project)
        session.commit()
        pid = project.id

        session.delete(project)
        session.commit()

        result = session.get(Project, pid)
        assert result is None

    def test_project_path_unique_enforced(self, session: Session) -> None:
        """Second project with same path raises IntegrityError."""
        p1 = _make_project(name="proj-a", path="/tmp/same-path")
        session.add(p1)
        session.commit()

        p2 = _make_project(name="proj-b", path="/tmp/same-path")
        session.add(p2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_project_null_path_allowed(self, session: Session) -> None:
        """Multiple projects with path=None coexist without unique conflict."""
        p1 = _make_project(name="idea-one", path=None)
        p2 = _make_project(name="idea-two", path=None)
        session.add(p1)
        session.add(p2)
        session.commit()

        results = session.exec(select(Project).where(Project.path.is_(None))).all()  # type: ignore[union-attr]
        assert len(results) == 2

    def test_project_status_check_constraint(self, session: Session) -> None:
        """Invalid status value raises IntegrityError."""
        project = _make_project(name="bad-status", status="invalid_status")
        session.add(project)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestProjectJSONColumns:
    """Verify JSON columns round-trip correctly through the ORM."""

    def test_languages_json_roundtrip(self, session: Session) -> None:
        """Store JSON object in languages column, read back and parse."""
        languages = {"python": 0.8, "sql": 0.2}
        project = _make_project(
            name="json-lang",
            path="/tmp/json-lang",
            languages=json.dumps(languages),
        )
        session.add(project)
        session.commit()

        fetched = session.get(Project, project.id)
        assert fetched is not None
        assert json.loads(fetched.languages) == languages  # type: ignore[arg-type]

    def test_frameworks_json_roundtrip(self, session: Session) -> None:
        """Store JSON array in frameworks column, read back and parse."""
        frameworks = ["fastapi", "sqlmodel"]
        project = _make_project(
            name="json-fw",
            path="/tmp/json-fw",
            frameworks=json.dumps(frameworks),
        )
        session.add(project)
        session.commit()

        fetched = session.get(Project, project.id)
        assert fetched is not None
        assert json.loads(fetched.frameworks) == frameworks  # type: ignore[arg-type]

    def test_json_columns_nullable(self, session: Session) -> None:
        """None for languages and frameworks works without errors."""
        project = _make_project(name="no-json", path="/tmp/no-json")
        session.add(project)
        session.commit()

        fetched = session.get(Project, project.id)
        assert fetched is not None
        assert fetched.languages is None
        assert fetched.frameworks is None


class TestEdgeCRUD:
    """Create, read, and constraint tests for the Edge model."""

    def test_create_edge_with_defaults(self, session: Session) -> None:
        """ULID generated, directed=False default."""
        p1 = _make_project(name="src", path="/tmp/src")
        p2 = _make_project(name="tgt", path="/tmp/tgt")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(source_id=p1.id, target_id=p2.id)
        session.add(edge)
        session.commit()
        session.refresh(edge)

        assert len(edge.id) == 26
        assert edge.directed is False
        assert edge.weight == 0.5

    def test_edge_metadata_column_mapping(self, session: Session) -> None:
        """edge_metadata attribute maps to DB column 'metadata'."""
        p1 = _make_project(name="src-meta", path="/tmp/src-meta")
        p2 = _make_project(name="tgt-meta", path="/tmp/tgt-meta")
        session.add_all([p1, p2])
        session.commit()

        meta = json.dumps({"shared_tech": ["python", "fastapi"]})
        edge = _make_edge(
            source_id=p1.id,
            target_id=p2.id,
            edge_metadata=meta,
        )
        session.add(edge)
        session.commit()
        session.refresh(edge)

        assert edge.edge_metadata == meta

        # Verify the data is in the DB column named 'metadata'
        from sqlalchemy import text

        row = session.exec(
            text("SELECT metadata FROM edges WHERE id = :eid"),
            params={"eid": edge.id},
        ).one()
        assert row[0] == meta

    def test_edge_metadata_json_roundtrip(self, session: Session) -> None:
        """Store JSON in edge_metadata, read back, parse correctly."""
        p1 = _make_project(name="src-json", path="/tmp/src-json")
        p2 = _make_project(name="tgt-json", path="/tmp/tgt-json")
        session.add_all([p1, p2])
        session.commit()

        meta_obj = {"similarity": 0.85, "common_deps": ["requests"]}
        edge = _make_edge(
            source_id=p1.id,
            target_id=p2.id,
            edge_metadata=json.dumps(meta_obj),
        )
        session.add(edge)
        session.commit()

        fetched = session.get(Edge, edge.id)
        assert fetched is not None
        assert json.loads(fetched.edge_metadata) == meta_obj  # type: ignore[arg-type]

    def test_edge_unique_constraint(self, session: Session) -> None:
        """Duplicate (source_id, target_id, edge_type) raises IntegrityError."""
        p1 = _make_project(name="src-uniq", path="/tmp/src-uniq")
        p2 = _make_project(name="tgt-uniq", path="/tmp/tgt-uniq")
        session.add_all([p1, p2])
        session.commit()

        e1 = _make_edge(source_id=p1.id, target_id=p2.id, edge_type="manual")
        session.add(e1)
        session.commit()

        e2 = _make_edge(source_id=p1.id, target_id=p2.id, edge_type="manual")
        session.add(e2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_edge_type_check_constraint(self, session: Session) -> None:
        """Invalid edge_type raises IntegrityError."""
        p1 = _make_project(name="src-chk", path="/tmp/src-chk")
        p2 = _make_project(name="tgt-chk", path="/tmp/tgt-chk")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(
            source_id=p1.id,
            target_id=p2.id,
            edge_type="invalid_type",
        )
        session.add(edge)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


class TestTagCRUD:
    """Create and constraint tests for the Tag model."""

    def test_create_tag(self, session: Session) -> None:
        """ULID generated, fields persist after commit."""
        tag = _make_tag(name="api-layer")
        session.add(tag)
        session.commit()
        session.refresh(tag)

        assert len(tag.id) == 26
        assert tag.name == "api-layer"
        assert tag.color == "#FF0000"

    def test_tag_name_unique(self, session: Session) -> None:
        """Duplicate tag name raises IntegrityError."""
        t1 = _make_tag(name="backend")
        session.add(t1)
        session.commit()

        t2 = _make_tag(name="backend")
        session.add(t2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_project_tag_link(self, session: Session) -> None:
        """Create ProjectTag, verify accessible via relationships."""
        project = _make_project(name="tagged-proj", path="/tmp/tagged")
        tag = _make_tag(name="frontend")
        session.add_all([project, tag])
        session.commit()

        link = ProjectTag(project_id=project.id, tag_id=tag.id)
        session.add(link)
        session.commit()

        # Verify via select
        result = session.exec(
            select(ProjectTag).where(
                ProjectTag.project_id == project.id,
                ProjectTag.tag_id == tag.id,
            )
        ).first()
        assert result is not None


class TestClusterCRUD:
    """Create and relationship tests for the Cluster model."""

    def test_create_cluster_with_defaults(self, session: Session) -> None:
        """Verify opacity=0.15, collapsed=False defaults."""
        cluster = _make_cluster(name="ml-cluster")
        session.add(cluster)
        session.commit()
        session.refresh(cluster)

        assert len(cluster.id) == 26
        assert cluster.opacity == pytest.approx(0.15)
        assert cluster.collapsed is False

    def test_project_cluster_link(self, session: Session) -> None:
        """Create ProjectCluster, verify accessible."""
        project = _make_project(name="clustered-proj", path="/tmp/clustered")
        cluster = _make_cluster(name="data-cluster")
        session.add_all([project, cluster])
        session.commit()

        link = ProjectCluster(project_id=project.id, cluster_id=cluster.id)
        session.add(link)
        session.commit()

        result = session.exec(
            select(ProjectCluster).where(
                ProjectCluster.project_id == project.id,
                ProjectCluster.cluster_id == cluster.id,
            )
        ).first()
        assert result is not None


class TestNodePositionCRUD:
    """Create and update tests for the NodePosition model."""

    def test_create_node_position(self, session: Session) -> None:
        """PK is project_id (FK), pinned=False default."""
        project = _make_project(name="positioned-proj", path="/tmp/positioned")
        session.add(project)
        session.commit()

        pos = NodePosition(
            project_id=project.id,
            x=100.5,
            y=200.3,
            updated_at=_NOW,
        )
        session.add(pos)
        session.commit()
        session.refresh(pos)

        assert pos.project_id == project.id
        assert pos.x == pytest.approx(100.5)
        assert pos.y == pytest.approx(200.3)
        assert pos.pinned is False

    def test_update_position(self, session: Session) -> None:
        """Modify x/y/pinned, verify persists after commit."""
        project = _make_project(name="move-proj", path="/tmp/move")
        session.add(project)
        session.commit()

        pos = NodePosition(
            project_id=project.id,
            x=0.0,
            y=0.0,
            updated_at=_NOW,
        )
        session.add(pos)
        session.commit()

        pos.x = 500.0
        pos.y = 750.0
        pos.pinned = True
        session.add(pos)
        session.commit()
        session.refresh(pos)

        assert pos.x == pytest.approx(500.0)
        assert pos.y == pytest.approx(750.0)
        assert pos.pinned is True


class TestConfigCRUD:
    """Tests for the Config model and seeded entries."""

    def test_read_seeded_config(self, session: Session) -> None:
        """Migration seeds 4 config entries; verify readable via ORM."""
        results = session.exec(select(Config)).all()
        keys = {c.key for c in results}

        expected_keys = {
            "projects_root",
            "auto_edge_min_weight",
            "scan_interval_minutes",
            "sidecar_port",
        }
        assert keys == expected_keys

        config_map = {c.key: c.value for c in results}
        assert config_map["projects_root"] == '"~/Documents"'
        assert config_map["auto_edge_min_weight"] == "0.3"
        assert config_map["scan_interval_minutes"] == "30"
        assert config_map["sidecar_port"] == "9721"

    def test_create_config_entry(self, session: Session) -> None:
        """Add a new config key/value pair."""
        entry = Config(key="theme", value='"dark"', updated_at=_NOW)
        session.add(entry)
        session.commit()

        fetched = session.get(Config, "theme")
        assert fetched is not None
        assert fetched.value == '"dark"'

    def test_update_config_value(self, session: Session) -> None:
        """Modify an existing config value."""
        entry = session.get(Config, "sidecar_port")
        assert entry is not None

        entry.value = "8080"
        session.add(entry)
        session.commit()
        session.refresh(entry)

        assert entry.value == "8080"


class TestCascadeDeletes:
    """Verify ON DELETE CASCADE propagation through the ORM.

    These tests rely on the SQLite PRAGMA foreign_keys = ON set by
    the engine listener in db/engine.py.
    """

    def test_delete_project_cascades_edges(self, session: Session) -> None:
        """Delete project that is source/target of edges; edges are gone."""
        p1 = _make_project(name="cascade-src", path="/tmp/cas-src")
        p2 = _make_project(name="cascade-tgt", path="/tmp/cas-tgt")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(source_id=p1.id, target_id=p2.id)
        session.add(edge)
        session.commit()
        edge_id = edge.id

        # Delete the source project
        session.delete(p1)
        session.commit()

        # Edge should be gone
        remaining = session.exec(select(Edge).where(Edge.id == edge_id)).first()
        assert remaining is None

    def test_delete_project_cascades_node_position(self, session: Session) -> None:
        """Delete project with position; position is gone."""
        project = _make_project(name="cas-pos", path="/tmp/cas-pos")
        session.add(project)
        session.commit()
        pid = project.id

        pos = NodePosition(project_id=pid, x=10.0, y=20.0, updated_at=_NOW)
        session.add(pos)
        session.commit()

        session.delete(project)
        session.commit()

        remaining = session.exec(
            select(NodePosition).where(NodePosition.project_id == pid)
        ).first()
        assert remaining is None

    def test_delete_project_cascades_project_tags(self, session: Session) -> None:
        """Delete project with tag links; links gone but tag remains."""
        project = _make_project(name="cas-tag", path="/tmp/cas-tag")
        tag = _make_tag(name="cas-tag-label")
        session.add_all([project, tag])
        session.commit()
        pid = project.id
        tid = tag.id

        link = ProjectTag(project_id=pid, tag_id=tid)
        session.add(link)
        session.commit()

        session.delete(project)
        session.commit()

        # Link gone
        remaining_link = session.exec(
            select(ProjectTag).where(ProjectTag.project_id == pid)
        ).first()
        assert remaining_link is None

        # Tag still exists
        remaining_tag = session.get(Tag, tid)
        assert remaining_tag is not None

    def test_delete_project_cascades_project_clusters(self, session: Session) -> None:
        """Delete project with cluster links; links gone but cluster remains."""
        project = _make_project(name="cas-clus", path="/tmp/cas-clus")
        cluster = _make_cluster(name="cas-cluster")
        session.add_all([project, cluster])
        session.commit()
        pid = project.id
        cid = cluster.id

        link = ProjectCluster(project_id=pid, cluster_id=cid)
        session.add(link)
        session.commit()

        session.delete(project)
        session.commit()

        # Link gone
        remaining_link = session.exec(
            select(ProjectCluster).where(ProjectCluster.project_id == pid)
        ).first()
        assert remaining_link is None

        # Cluster still exists
        remaining_cluster = session.get(Cluster, cid)
        assert remaining_cluster is not None

    def test_delete_tag_cascades_project_tags(self, session: Session) -> None:
        """Delete tag; project_tag links gone but project remains."""
        project = _make_project(name="tag-del-proj", path="/tmp/tag-del")
        tag = _make_tag(name="tag-to-delete")
        session.add_all([project, tag])
        session.commit()
        pid = project.id
        tid = tag.id

        link = ProjectTag(project_id=pid, tag_id=tid)
        session.add(link)
        session.commit()

        session.delete(tag)
        session.commit()

        # Link gone
        remaining_link = session.exec(
            select(ProjectTag).where(ProjectTag.tag_id == tid)
        ).first()
        assert remaining_link is None

        # Project still exists
        remaining_project = session.get(Project, pid)
        assert remaining_project is not None

    def test_delete_cluster_cascades_project_clusters(self, session: Session) -> None:
        """Delete cluster; project_cluster links gone but project remains."""
        project = _make_project(name="clus-del-proj", path="/tmp/clus-del")
        cluster = _make_cluster(name="cluster-to-delete")
        session.add_all([project, cluster])
        session.commit()
        pid = project.id
        cid = cluster.id

        link = ProjectCluster(project_id=pid, cluster_id=cid)
        session.add(link)
        session.commit()

        session.delete(cluster)
        session.commit()

        # Link gone
        remaining_link = session.exec(
            select(ProjectCluster).where(ProjectCluster.cluster_id == cid)
        ).first()
        assert remaining_link is None

        # Project still exists
        remaining_project = session.get(Project, pid)
        assert remaining_project is not None


class TestRelationships:
    """Verify SQLModel relationship traversal works correctly."""

    def test_project_source_edges_relationship(self, session: Session) -> None:
        """Access project.source_edges returns correct Edge objects."""
        p1 = _make_project(name="rel-src", path="/tmp/rel-src")
        p2 = _make_project(name="rel-tgt", path="/tmp/rel-tgt")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(source_id=p1.id, target_id=p2.id)
        session.add(edge)
        session.commit()

        # Expire cached state and re-fetch the project
        session.expire(p1)
        fetched = session.get(Project, p1.id)
        assert fetched is not None
        assert len(fetched.source_edges) == 1
        assert fetched.source_edges[0].target_id == p2.id

    def test_project_target_edges_relationship(self, session: Session) -> None:
        """Access project.target_edges returns correct Edge objects."""
        p1 = _make_project(name="rel-src2", path="/tmp/rel-src2")
        p2 = _make_project(name="rel-tgt2", path="/tmp/rel-tgt2")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(source_id=p1.id, target_id=p2.id)
        session.add(edge)
        session.commit()

        session.expire(p2)
        fetched = session.get(Project, p2.id)
        assert fetched is not None
        assert len(fetched.target_edges) == 1
        assert fetched.target_edges[0].source_id == p1.id

    def test_project_node_position_one_to_one(self, session: Session) -> None:
        """project.node_position returns single object, not a list."""
        project = _make_project(name="rel-pos", path="/tmp/rel-pos")
        session.add(project)
        session.commit()

        pos = NodePosition(
            project_id=project.id,
            x=42.0,
            y=84.0,
            updated_at=_NOW,
        )
        session.add(pos)
        session.commit()

        session.expire(project)
        fetched = session.get(Project, project.id)
        assert fetched is not None
        assert fetched.node_position is not None
        assert not isinstance(fetched.node_position, list)
        assert fetched.node_position.x == pytest.approx(42.0)
        assert fetched.node_position.y == pytest.approx(84.0)

    def test_edge_source_target_relationships(self, session: Session) -> None:
        """edge.source and edge.target return correct Project objects."""
        p1 = _make_project(name="edge-src", path="/tmp/edge-src")
        p2 = _make_project(name="edge-tgt", path="/tmp/edge-tgt")
        session.add_all([p1, p2])
        session.commit()

        edge = _make_edge(source_id=p1.id, target_id=p2.id)
        session.add(edge)
        session.commit()

        session.expire(edge)
        fetched = session.get(Edge, edge.id)
        assert fetched is not None
        assert fetched.source.id == p1.id
        assert fetched.source.name == "edge-src"
        assert fetched.target.id == p2.id
        assert fetched.target.name == "edge-tgt"

    def test_tag_project_links_relationship(self, session: Session) -> None:
        """tag.project_links returns list of ProjectTag."""
        project = _make_project(name="tag-link-proj", path="/tmp/tag-link")
        tag = _make_tag(name="tag-link-tag")
        session.add_all([project, tag])
        session.commit()

        link = ProjectTag(project_id=project.id, tag_id=tag.id)
        session.add(link)
        session.commit()

        session.expire(tag)
        fetched = session.get(Tag, tag.id)
        assert fetched is not None
        assert len(fetched.project_links) == 1
        assert fetched.project_links[0].project_id == project.id

    def test_cluster_project_links_relationship(self, session: Session) -> None:
        """cluster.project_links returns list of ProjectCluster."""
        project = _make_project(name="clus-link-proj", path="/tmp/clus-link")
        cluster = _make_cluster(name="clus-link-cluster")
        session.add_all([project, cluster])
        session.commit()

        link = ProjectCluster(project_id=project.id, cluster_id=cluster.id)
        session.add(link)
        session.commit()

        session.expire(cluster)
        fetched = session.get(Cluster, cluster.id)
        assert fetched is not None
        assert len(fetched.project_links) == 1
        assert fetched.project_links[0].project_id == project.id
