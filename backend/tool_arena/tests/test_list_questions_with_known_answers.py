"""EvaluationCatalog — backend-side eval query metadata loader.

Mirrors the rag_pill FixedCorpus eval query loader but ships *only* the
metadata (id, query_text, goal_text) the router needs to substitute task/goal
text in benchmark mode. The expected_spans stay in rag_pill (the judge runs
there in plan 13-05; the backend never touches gold truth directly).

Tests drive the catalog's contract — slices 4.1, 4.2, 4.3.
"""

from pathlib import Path

from backend.tool_arena.question.list_questions_with_known_answers import EvaluationCatalog


def test_catalog_loads_queries_from_yaml(tmp_path: Path) -> None:
    """Slice 4.1 — minimal YAML fixture; assert list_ids() returns ids
    in file order (deterministic for the frontend benchmark picker)."""
    (tmp_path / "queries.yaml").write_text(
        """\
- id: q01_capital_france
  query_text: "Quelle est la capitale de la France ?"
  goal_text: "Réponse précise."
  expected_spans:
    - source_doc_id: "geography_fr.md"
      char_start: 0
      char_end: 35
- id: q02_eiffel
  query_text: "Où se trouve la Tour Eiffel ?"
  goal_text: "Ville et arrondissement."
  expected_spans: []
"""
    )

    cat = EvaluationCatalog(tmp_path / "queries.yaml")
    assert cat.list_ids() == ["q01_capital_france", "q02_eiffel"]


def test_catalog_get_returns_query_metadata(tmp_path: Path) -> None:
    """Slice 4.2 — lookup by id returns query_text + goal_text (the two
    fields the router substitutes into the compare call in benchmark mode)."""
    (tmp_path / "queries.yaml").write_text(
        """\
- id: q01
  query_text: "Question text."
  goal_text: "Goal text."
  expected_spans: []
"""
    )
    cat = EvaluationCatalog(tmp_path / "queries.yaml")
    q = cat.get("q01")
    assert q is not None
    assert q.id == "q01"
    assert q.query_text == "Question text."
    assert q.goal_text == "Goal text."


def test_catalog_get_returns_none_for_unknown_id(tmp_path: Path) -> None:
    """Slice 4.3 — unknown id -> None. Router treats None as 'invalid
    evaluation_query_id', returns 422; never blows up."""
    (tmp_path / "queries.yaml").write_text(
        '- {id: q01, query_text: "x", goal_text: "y", expected_spans: []}\n'
    )
    cat = EvaluationCatalog(tmp_path / "queries.yaml")
    assert cat.get("does_not_exist") is None


def test_catalog_empty_when_file_missing(tmp_path: Path) -> None:
    """Defensive: backend starts before corpus is mounted. Empty catalog,
    no exception. Router's validator rejects evaluation_query_id in that
    case (cannot match any id), so users see 422 not 500."""
    cat = EvaluationCatalog(tmp_path / "missing.yaml")
    assert cat.list_ids() == []
    assert cat.get("anything") is None
