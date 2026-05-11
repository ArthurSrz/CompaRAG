"""EvaluationCatalog — backend-side eval query metadata loader.

Mirrors the rag_pill FixedCorpus eval query loader but ships *only* the
metadata (id, query_text, goal_text) the router needs to substitute task/goal
text in benchmark mode. The expected_spans stay in rag_pill (the judge runs
there in plan 13-05; the backend never touches gold truth directly).

Tests drive the catalog's contract — slices 4.1, 4.2, 4.3.
"""

from pathlib import Path

from backend.tool_arena.evaluation import EvaluationCatalog


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
