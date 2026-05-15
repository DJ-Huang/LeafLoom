from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llama_index.core.schema import TextNode


def write_nodes_jsonl(nodes: list[TextNode], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for n in nodes:
            row = {
                "id": n.node_id,
                "text": n.get_content(metadata_mode="none"),
                "metadata": dict(n.metadata or {}),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_nodes_jsonl(path: Path) -> list[TextNode]:
    if not path.is_file():
        return []
    nodes: list[TextNode] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row: dict[str, Any] = json.loads(line)
            nid = str(row["id"])
            text = str(row.get("text", ""))
            meta = dict(row.get("metadata") or {})
            nodes.append(TextNode(id_=nid, text=text, metadata=meta))
    return nodes
