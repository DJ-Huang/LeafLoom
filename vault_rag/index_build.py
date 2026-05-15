from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore

from vault_rag.chunking import documents_to_nodes
from vault_rag.loader import iter_markdown_documents
from vault_rag.metadata_unify import unify_node_metadata_keys
from vault_rag.nodes_store import write_nodes_jsonl
from vault_rag.settings import Settings

logger = logging.getLogger(__name__)


def build_index(project_root: Path, settings: Settings) -> dict[str, Any]:
    """Full rebuild: wipe Lance table files, embed all chunks, write nodes.jsonl + status.json."""
    index_dir = settings.resolved_index_dir(project_root)
    index_dir.mkdir(parents=True, exist_ok=True)
    lance_path = index_dir / "lancedb"
    if lance_path.exists():
        shutil.rmtree(lance_path)
    lance_path.mkdir(parents=True, exist_ok=True)

    docs = iter_markdown_documents(settings)
    num_files = len(docs)
    nodes = documents_to_nodes(docs)
    if not nodes:
        raise RuntimeError(
            "No Markdown chunks produced. Check VAULT_ROOT, note content, and exclude rules."
        )
    unify_node_metadata_keys(nodes)

    # LanceDB + LlamaIndex: table schema is fixed on first `create_table`. Batched
    # `add()` can fail if later rows include metadata fields absent from the first
    # batch (e.g. rare YAML keys like `createdTime`). Single batch matches schema
    # to the full union of keys after `unify_node_metadata_keys`.
    insert_batch = max(1, len(nodes))

    logger.info("Embedding %s chunks from %s markdown files…", len(nodes), num_files)
    embed_model = OllamaEmbedding(
        model_name=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )

    vector_store = LanceDBVectorStore(
        uri=str(lance_path),
        table_name=settings.lance_table,
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True,
        insert_batch_size=insert_batch,
    )

    nodes_path = index_dir / "nodes.jsonl"
    write_nodes_jsonl(nodes, nodes_path)

    status = {
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "vault_root": str(settings.vault_root.resolve()),
        "index_in_vault": settings.index_in_vault,
        "vault_index_folder": settings.vault_index_folder,
        "num_files": num_files,
        "num_chunks": len(nodes),
        "embedding_model": settings.embedding_model,
        "ollama_base_url": settings.ollama_base_url,
        "lance_uri": str(lance_path),
        "lance_table": settings.lance_table,
        "nodes_jsonl": str(nodes_path),
        "index_dir": str(index_dir),
        "exclude_dir_names_effective": list(settings.merged_exclude_dir_names()),
    }
    (index_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Index written under %s", index_dir)
    return status
