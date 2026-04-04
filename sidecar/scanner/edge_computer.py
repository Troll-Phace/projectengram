"""Edge computation engine for pairwise project relationships.

Computes ``auto_tech`` edges (tech stack Jaccard similarity) and
``auto_dep`` edges (dependency overlap ratio) between all project
pairs.  Manual edges are **never** touched by this module.

The module is organized in three layers:

1. **Pure computation** — zero side-effects, fully testable functions.
2. **Data extraction helper** — parses JSON strings stored on Project
   models into typed Python collections.
3. **DB-interacting orchestration** — reads/writes edges in a single
   transaction via ``compute_edges``.

Reference: ARCHITECTURE.md §7 — Edge Computation Engine.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from models import Config, Edge, Project
from utils.time import now_iso
from utils.ulid import generate_ulid

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MIN_WEIGHT: float = 0.3
"""Minimum edge weight for an auto-edge to be kept.  Edges that fall
below this threshold are deleted during computation."""

AUTO_EDGE_TYPES: frozenset[str] = frozenset({"auto_tech", "auto_dep"})
"""Edge types managed by this module.  Manual edges are never touched."""

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1: Pure Computation (no I/O, no DB)
# ---------------------------------------------------------------------------


def normalize_pair(id_a: str, id_b: str) -> tuple[str, str]:
    """Return a consistently ordered ``(source_id, target_id)`` pair.

    Uses lexicographic ordering so that ``(A, B)`` and ``(B, A)`` always
    produce the same tuple, preventing duplicate edges with swapped IDs.

    Args:
        id_a: First project ULID.
        id_b: Second project ULID.

    Returns:
        A two-tuple with the smaller ID first.
    """
    return (id_a, id_b) if id_a < id_b else (id_b, id_a)


def compute_tech_similarity(
    frameworks_a: list[str],
    languages_a: dict[str, float],
    frameworks_b: list[str],
    languages_b: dict[str, float],
) -> tuple[float, list[str]]:
    """Compute Jaccard similarity of two projects' tech stacks.

    Builds a feature set per project as the union of framework names
    and language keys, then calculates the Jaccard index.

    Args:
        frameworks_a: Framework names for project A.
        languages_a: Language-to-percentage mapping for project A.
        frameworks_b: Framework names for project B.
        languages_b: Language-to-percentage mapping for project B.

    Returns:
        A tuple of ``(score, shared_features)`` where *score* is a
        float in ``[0.0, 1.0]`` and *shared_features* is a sorted
        list of features present in both projects.
    """
    features_a = {f.lower() for f in frameworks_a} | {k.lower() for k in languages_a}
    features_b = {f.lower() for f in frameworks_b} | {k.lower() for k in languages_b}

    union = features_a | features_b
    if not union:
        return 0.0, []

    intersection = features_a & features_b
    score = len(intersection) / len(union)
    return score, sorted(intersection)


def compute_dep_overlap(
    deps_a: frozenset[str],
    deps_b: frozenset[str],
) -> tuple[float, list[str]]:
    """Compute dependency overlap ratio between two projects.

    The score is ``|shared| / min(|a|, |b|)``, which measures how much
    the smaller dependency set is contained in the larger one.

    Args:
        deps_a: Dependency names for project A.
        deps_b: Dependency names for project B.

    Returns:
        A tuple of ``(score, shared_deps)`` where *score* is a float
        in ``[0.0, 1.0]`` and *shared_deps* is a sorted list of
        dependency names present in both projects.
    """
    if not deps_a or not deps_b:
        return 0.0, []

    shared = deps_a & deps_b
    smaller = min(len(deps_a), len(deps_b))
    score = len(shared) / smaller if smaller > 0 else 0.0
    return score, sorted(shared)


# ---------------------------------------------------------------------------
# Layer 2: Data Extraction Helper (private)
# ---------------------------------------------------------------------------


def _extract_tech_features(
    project: Project,
) -> tuple[list[str], dict[str, float]]:
    """Parse tech-stack JSON strings stored on a Project model.

    Handles ``None``, empty strings, and malformed JSON gracefully by
    returning empty collections.

    Args:
        project: A Project ORM instance with ``frameworks`` (JSON
            array string) and ``languages`` (JSON dict string) fields.

    Returns:
        A tuple of ``(frameworks, languages)`` where *frameworks* is
        a ``list[str]`` and *languages* is a ``dict[str, float]``.
    """
    frameworks: list[str] = []
    if project.frameworks:
        try:
            parsed = json.loads(project.frameworks)
            if isinstance(parsed, list):
                frameworks = [str(f) for f in parsed if isinstance(f, str)]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    languages: dict[str, float] = {}
    if project.languages:
        try:
            parsed = json.loads(project.languages)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if isinstance(k, str):
                        try:
                            languages[k] = float(v)
                        except (TypeError, ValueError):
                            pass
        except (json.JSONDecodeError, TypeError):
            pass

    return frameworks, languages


# ---------------------------------------------------------------------------
# Layer 3: DB-Interacting Orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeComputationResult:
    """Summary counters from a single edge computation run.

    Attributes:
        created: Number of new auto-edges inserted.
        updated: Number of existing auto-edges whose weight changed.
        deleted: Number of auto-edges removed (below threshold or stale).
        unchanged: Number of existing auto-edges that remained the same.
    """

    created: int
    updated: int
    deleted: int
    unchanged: int


def compute_edges(
    session: Session,
    projects: list[Project],
    dep_map: dict[str, frozenset[str]] | None = None,
    min_weight: float | None = None,
) -> EdgeComputationResult:
    """Compute and upsert auto-edges for all project pairs.

    Performs the full edge computation lifecycle in a single
    transaction: creates new edges, updates changed weights, and
    deletes edges that fall below the minimum threshold or are stale
    (i.e. their source/target projects are no longer in the input
    list).

    Manual edges (``edge_type='manual'``) are **never** queried,
    modified, or deleted.

    Args:
        session: An active SQLModel session.  The caller is
            responsible for providing a session with ``PRAGMA
            foreign_keys = ON``.
        projects: The list of projects to compute edges between.
        dep_map: Optional mapping of ``project.id`` to a frozenset
            of dependency names.  If ``None``, dependency sets are
            built by calling ``detect_project_type`` on each
            project's path.
        min_weight: Minimum edge weight.  Auto-edges below this
            value are deleted.  If ``None``, the value is read from
            the ``config`` table (key ``auto_edge_min_weight``),
            falling back to ``DEFAULT_MIN_WEIGHT``.

    Returns:
        An ``EdgeComputationResult`` with counts of created, updated,
        deleted, and unchanged edges.
    """
    # -----------------------------------------------------------------
    # Step 1: Resolve minimum weight from config if not provided
    # -----------------------------------------------------------------
    if min_weight is None:
        config_entry = session.exec(
            select(Config).where(Config.key == "auto_edge_min_weight")
        ).first()
        if config_entry is not None and config_entry.value is not None:
            try:
                min_weight = float(json.loads(config_entry.value))
            except (json.JSONDecodeError, TypeError, ValueError):
                min_weight = DEFAULT_MIN_WEIGHT
        else:
            min_weight = DEFAULT_MIN_WEIGHT

    # -----------------------------------------------------------------
    # Step 2: Build dependency map if not provided
    # -----------------------------------------------------------------
    if dep_map is None:
        dep_map = _build_dep_map(projects)

    # -----------------------------------------------------------------
    # Step 3: Load all existing auto-edges into a lookup dict
    # -----------------------------------------------------------------
    existing_auto = session.exec(
        select(Edge).where(Edge.edge_type.in_(list(AUTO_EDGE_TYPES)))
    ).all()

    edge_lookup: dict[tuple[str, str, str], Edge] = {
        (e.source_id, e.target_id, e.edge_type): e for e in existing_auto
    }

    # -----------------------------------------------------------------
    # Step 4: Iterate all unique pairs and compute edges
    # -----------------------------------------------------------------
    seen: set[tuple[str, str, str]] = set()
    created = 0
    updated = 0
    deleted = 0
    unchanged = 0

    timestamp = now_iso()

    for i in range(len(projects)):
        for j in range(i + 1, len(projects)):
            source_id, target_id = normalize_pair(projects[i].id, projects[j].id)

            # Extract tech features for both projects.
            fw_a, lang_a = _extract_tech_features(projects[i])
            fw_b, lang_b = _extract_tech_features(projects[j])

            # Compute tech similarity.
            tech_score, shared_features = compute_tech_similarity(fw_a, lang_a, fw_b, lang_b)

            # Compute dependency overlap.
            deps_a = dep_map.get(projects[i].id, frozenset())
            deps_b = dep_map.get(projects[j].id, frozenset())
            dep_score, shared_deps = compute_dep_overlap(deps_a, deps_b)

            # Process each edge type.
            edge_specs: list[tuple[str, float, str]] = [
                (
                    "auto_tech",
                    tech_score,
                    json.dumps(
                        {
                            "shared_features": shared_features,
                            "score": round(tech_score, 4),
                        }
                    ),
                ),
                (
                    "auto_dep",
                    dep_score,
                    json.dumps(
                        {
                            "shared_deps": shared_deps,
                            "score": round(dep_score, 4),
                        }
                    ),
                ),
            ]

            for edge_type, score, metadata_json in edge_specs:
                key = (source_id, target_id, edge_type)
                seen.add(key)

                if score >= min_weight:
                    existing = edge_lookup.get(key)
                    if existing is not None:
                        # Update only if weight actually changed.
                        if (
                            abs(existing.weight - score) > 1e-9
                            or existing.edge_metadata != metadata_json
                        ):
                            existing.weight = score
                            existing.edge_metadata = metadata_json
                            existing.updated_at = timestamp
                            session.add(existing)
                            updated += 1
                        else:
                            unchanged += 1
                    else:
                        new_edge = Edge(
                            id=generate_ulid(),
                            source_id=source_id,
                            target_id=target_id,
                            edge_type=edge_type,
                            weight=score,
                            edge_metadata=metadata_json,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                        session.add(new_edge)
                        created += 1
                else:
                    # Score below threshold — delete existing edge if any.
                    existing = edge_lookup.get(key)
                    if existing is not None:
                        session.delete(existing)
                        deleted += 1

    # -----------------------------------------------------------------
    # Step 5: Stale cleanup — delete edges whose pairs were not seen
    # -----------------------------------------------------------------
    for key, edge in edge_lookup.items():
        if key not in seen:
            session.delete(edge)
            deleted += 1

    # -----------------------------------------------------------------
    # Step 6: Commit all changes in a single transaction
    # -----------------------------------------------------------------
    session.commit()

    result = EdgeComputationResult(
        created=created,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
    )

    _log.info(
        "Edge computation complete: created=%d updated=%d deleted=%d " "unchanged=%d",
        result.created,
        result.updated,
        result.deleted,
        result.unchanged,
    )

    return result


def _build_dep_map(
    projects: list[Project],
) -> dict[str, frozenset[str]]:
    """Build a dependency map by detecting project types from disk.

    Falls back gracefully when a project has no path or its manifests
    cannot be parsed.

    Args:
        projects: The projects to inspect.

    Returns:
        A dict mapping project IDs to their frozenset of dependency
        names.
    """
    # Lazy import to avoid circular dependencies and to keep the
    # import cost out of the module top level.
    from scanner.analyzers.project_type import detect_project_type

    dep_map: dict[str, frozenset[str]] = {}

    for project in projects:
        if not project.path:
            dep_map[project.id] = frozenset()
            continue
        project_path = Path(project.path)
        if not project_path.is_dir():
            dep_map[project.id] = frozenset()
            continue
        try:
            result = detect_project_type(project_path)
            dep_map[project.id] = result.all_dependencies
        except Exception:  # noqa: BLE001
            _log.warning(
                "Failed to detect dependencies for project %s at %s",
                project.id,
                project.path,
                exc_info=True,
            )
            dep_map[project.id] = frozenset()

    return dep_map
