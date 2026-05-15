from __future__ import annotations

from llama_index.core.schema import TextNode

from vault_rag.metadata_sanitize import sanitize_metadata_for_vector_store


def unify_node_metadata_keys(nodes: list[TextNode]) -> None:
    """
    LanceDB table schema is fixed on first insert; every row must have the same columns.
    Collect all metadata keys across nodes, then pad missing keys with empty string.
    """
    all_keys: set[str] = set()
    for n in nodes:
        all_keys.update(str(k) for k in (n.metadata or {}).keys())

    for n in nodes:
        md = {str(k): v for k, v in (n.metadata or {}).items()}
        for k in all_keys:
            if k not in md:
                md[k] = ""
        n.metadata = sanitize_metadata_for_vector_store(md)
