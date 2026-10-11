import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for source_path in (ROOT / "apps" / "api", ROOT / "packages" / "shared"):
    sys.path.insert(0, str(source_path))

from app.services import store


def test_module_dependency_view_respects_limit_and_reports_truncation(monkeypatch):
    nodes = [
        {"id": f"module-{index}", "label": f"module-{index}", "kind": "module", "layer": "service"}
        for index in range(8)
    ]
    edges = [
        {"id": "inside", "source": "module-0", "target": "module-1"},
        {"id": "outside", "source": "module-1", "target": "module-7"},
    ]
    artifact = {"nodes": nodes, "edges": edges}
    monkeypatch.setattr(store, "require_complete", lambda _session, _analysis_id: None)
    monkeypatch.setattr(store, "get_artifact", lambda _session, _analysis_id, _kind: artifact)

    result = store.get_dependencies(object(), "analysis-id", view="modules", limit=3)

    assert [node["id"] for node in result["nodes"]] == ["module-0", "module-1", "module-2"]
    assert [edge["id"] for edge in result["edges"]] == ["inside"]
    assert result["stats"] == {
        "nodes": 3,
        "edges": 1,
        "shown_nodes": 3,
        "total_nodes": 8,
        "truncated": True,
    }


def test_module_dependency_view_is_not_marked_truncated_when_all_nodes_fit(monkeypatch):
    nodes = [{"id": "module-1", "label": "module-1", "kind": "module", "layer": "service"}]
    artifact = {"nodes": nodes, "edges": []}
    monkeypatch.setattr(store, "require_complete", lambda _session, _analysis_id: None)
    monkeypatch.setattr(store, "get_artifact", lambda _session, _analysis_id, _kind: artifact)

    result = store.get_dependencies(object(), "analysis-id", view="modules", limit=48)

    assert result["stats"]["shown_nodes"] == result["stats"]["total_nodes"] == 1
    assert result["stats"]["truncated"] is False
