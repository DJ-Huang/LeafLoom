from __future__ import annotations

import hashlib
from typing import Iterable

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import TextNode


def _stable_chunk_id(file_path: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(file_path.encode("utf-8"))
    h.update(b"\n")
    h.update(text.encode("utf-8", errors="replace"))
    return h.hexdigest()


def documents_to_nodes(documents: Iterable[Document]) -> list[TextNode]:
    """Split markdown by headings; assign stable node ids for persistence."""
    parser = MarkdownNodeParser.from_defaults()
    nodes: list[TextNode] = []
    for doc in documents:
        for node in parser.get_nodes_from_documents([doc]):
            if not isinstance(node, TextNode):
                continue
            fp = str(node.metadata.get("file_path", ""))
            text = node.get_content(metadata_mode="none")
            node_id = _stable_chunk_id(fp, text)
            node.node_id = node_id
            nodes.append(node)
    return nodes
