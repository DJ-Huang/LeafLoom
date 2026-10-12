from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex
from vault_rag.embedded_model import llama_embedding
from vault_rag.local_state import LocalConfig
from llama_index.vector_stores.lancedb import LanceDBVectorStore

from vault_rag.chunking import documents_to_nodes
from vault_rag.loader import iter_markdown_documents
from vault_rag.metadata_unify import unify_node_metadata_keys
from vault_rag.nodes_store import write_nodes_jsonl
from vault_rag.settings import Settings
from vault_rag.content_scope import CONTENT_SCOPE_VERSION

logger = logging.getLogger(__name__)


def _write_index(project_root: Path, settings: Settings, index_dir: Path) -> dict[str, Any]:
    """Full rebuild: wipe Lance table files, embed all chunks, write nodes.jsonl + status.json."""
    # Validate and load the scope before touching the old index.
    docs = iter_markdown_documents(settings)
    num_files = len(docs)
    nodes = documents_to_nodes(docs)
    if not nodes:
        raise RuntimeError("No Markdown chunks produced in VAULT_CONTENT_FOLDER; old index untouched")
    index_dir.mkdir(parents=True, exist_ok=True)
    lance_path = index_dir / "lancedb"
    if lance_path.exists():
        shutil.rmtree(lance_path)
    lance_path.mkdir(parents=True, exist_ok=True)

    unify_node_metadata_keys(nodes)

    # LanceDB + LlamaIndex: table schema is fixed on first `create_table`. Batched
    # `add()` can fail if later rows include metadata fields absent from the first
    # batch (e.g. rare YAML keys like `createdTime`). Single batch matches schema
    # to the full union of keys after `unify_node_metadata_keys`.
    insert_batch = max(1, len(nodes))

    logger.info("Embedding %s chunks from %s markdown files…", len(nodes), num_files)
    embed_model = llama_embedding(LocalConfig().directory)

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
        "vault_content_folder": settings.vault_content_folder,
        "vault_content_root": str(settings.resolved_content_root()),
        "content_scope_version": CONTENT_SCOPE_VERSION,
        "index_in_vault": settings.index_in_vault,
        "vault_index_folder": settings.vault_index_folder,
        "num_files": num_files,
        "num_chunks": len(nodes),
        "embedding_model": settings.embedding_model,
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


def build_index(project_root: Path, settings: Settings) -> dict[str, Any]:
    """Build in a sibling staging folder and publish only after successful embedding."""
    settings.resolved_content_root()
    target = settings.resolved_index_dir(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=target.name + ".building-", dir=target.parent))
    previous = stage.with_name(stage.name + ".previous")
    published = False
    try:
        status = _write_index(project_root, settings, stage)
        status.update(index_dir=str(target), nodes_jsonl=str(target / "nodes.jsonl"),
                      lance_uri=str(target / "lancedb"))
        (stage / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            target.rename(previous)
        try:
            stage.rename(target)
            published = True
        except Exception:
            if previous.exists():
                previous.rename(target)
            raise
        return status
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if published and previous.exists():
            shutil.rmtree(previous)
