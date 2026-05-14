from __future__ import annotations
import json
from pathlib import Path
from typing import Optional


class MemQGraph:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self._nodes: dict[str, dict] = {}
        self._edges: list[dict] = []
        self._load()

    def _load(self):
        nf = self.path / "nodes.json"
        ef = self.path / "edges.json"
        if nf.exists():
            with open(nf) as f:
                self._nodes = json.load(f)
        if ef.exists():
            with open(ef) as f:
                self._edges = json.load(f)

    def _save(self):
        with open(self.path / "nodes.json", "w") as f:
            json.dump(self._nodes, f, indent=2, default=str)
        with open(self.path / "edges.json", "w") as f:
            json.dump(self._edges, f, indent=2, default=str)

    def add_node(self, node_id: str, label: str, attrs: Optional[dict] = None):
        self._nodes[node_id] = {"id": node_id, "label": label, "attrs": attrs or {}}
        self._save()

    def add_edge(self, src: str, dst: str, rel: str, attrs: Optional[dict] = None):
        self._edges.append({"src": src, "dst": dst, "rel": rel, "attrs": attrs or {}})
        self._save()

    def get_node(self, node_id: str) -> Optional[dict]:
        return self._nodes.get(node_id)

    def query(self, node_id: str, max_depth: int = 2) -> list[dict]:
        visited = {node_id}
        queue = [(node_id, 0)]
        results = []
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for e in self._edges:
                if e["src"] == current and e["dst"] not in visited:
                    visited.add(e["dst"])
                    results.append(e)
                    queue.append((e["dst"], depth + 1))
                elif e["dst"] == current and e["src"] not in visited:
                    visited.add(e["src"])
                    results.append(e)
                    queue.append((e["src"], depth + 1))
        return results

    def nodes_by_label(self, label: str) -> list[dict]:
        return [n for n in self._nodes.values() if n["label"] == label]

    def clear(self):
        self._nodes.clear()
        self._edges.clear()
        self._save()
