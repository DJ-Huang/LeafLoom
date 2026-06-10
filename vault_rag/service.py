from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.schema import TextNode

from vault_rag.fusion import reciprocal_rank_fusion
from vault_rag.nodes_store import read_nodes_jsonl
from vault_rag.settings import Settings
from vault_rag.verification_rank import (
    UNVERIFIED_EXCERPT_PREFIX,
    rank_search_candidates,
    select_for_top_k,
    trust_label,
    verification_tier,
)

logger = logging.getLogger(__name__)


def _normalize_posix_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _path_under_prefix(file_path: str, prefix: str | None) -> bool:
    if not prefix:
        return True
    rel = _normalize_posix_path(file_path)
    root = _normalize_posix_path(prefix)
    return rel == root or rel.startswith(f"{root}/")


def _path_excluded_by_prefixes(file_path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if _path_under_prefix(file_path, prefix):
            return True
    return False


def _metadata_match(meta: dict[str, Any], *, type_: str | None, domain: str | None) -> bool:
    if type_ is not None and str(meta.get("type", "")).lower() != type_.lower():
        return False
    if domain is not None:
        want = domain.lower()
        raw = str(meta.get("domain", "")).lower()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if want not in parts and raw != want:
            return False
    return True


class VaultRagService:
    """Loads LanceDB + BM25 from a built index directory."""

    def __init__(self, project_root: Path, settings: Settings) -> None:
        self.project_root = project_root
        self.settings = settings
        self.index_dir = settings.resolved_index_dir(project_root)
        self._nodes_by_id: dict[str, TextNode] = {}
        self._vector_retriever = None
        self._bm25: BM25Retriever | None = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        nodes_path = self.index_dir / "nodes.jsonl"
        if not nodes_path.is_file():
            raise FileNotFoundError(
                f"Missing {nodes_path}. Run `vault-rag reindex` (from vault-rag/) first."
            )
        lance_path = self.index_dir / "lancedb"
        if not lance_path.exists():
            raise FileNotFoundError(
                f"Missing LanceDB directory {lance_path}. Run `vault-rag reindex` first."
            )

        nodes = read_nodes_jsonl(nodes_path)
        if not nodes:
            raise RuntimeError(f"No nodes in {nodes_path}")
        self._nodes_by_id = {n.node_id: n for n in nodes}

        embed_model = OllamaEmbedding(
            model_name=self.settings.embedding_model,
            base_url=self.settings.ollama_base_url,
        )
        vector_store = LanceDBVectorStore(
            uri=str(lance_path),
            table_name=self.settings.lance_table,
        )
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model=embed_model,
        )
        self._vector_retriever = index.as_retriever(
            similarity_top_k=self.settings.vector_top_k,
        )
        self._bm25 = BM25Retriever.from_defaults(
            nodes=nodes,
            similarity_top_k=self.settings.bm25_top_k,
        )
        self._loaded = True
        logger.info(
            "Vault RAG loaded: %s chunks, Lance=%s",
            len(nodes),
            lance_path,
        )

    def status(self) -> dict[str, Any]:
        path = self.index_dir / "status.json"
        if not path.is_file():
            return {"ok": False, "error": f"Missing index status at {path}"}
        return {"ok": True, **json.loads(path.read_text(encoding="utf-8"))}

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        type_: str | None = None,
        domain: str | None = None,
        path_prefix: str | None = None,
        path_exclude_prefixes: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        self._ensure_loaded()
        assert self._vector_retriever is not None and self._bm25 is not None

        v_results = self._vector_retriever.retrieve(query)
        b_results = self._bm25.retrieve(query)
        # BM25 first per LlamaIndex community guidance for fusion with sparse retrievers.
        merged = reciprocal_rank_fusion(
            [b_results, v_results],
            k=self.settings.rrf_k,
            top_n=max(top_k * 8, 40),
        )

        filtered: list = []
        for nws in merged:
            meta = dict(nws.node.metadata or {})
            file_path = str(meta.get("file_path", ""))
            if not _path_under_prefix(file_path, path_prefix):
                continue
            if _path_excluded_by_prefixes(file_path, path_exclude_prefixes):
                continue
            if _metadata_match(meta, type_=type_, domain=domain):
                filtered.append(nws)

        if self.settings.verification_ranking_enabled:
            preferred, backfill = rank_search_candidates(
                filtered,
                restricted_prefixes=self.settings.unverified_restricted_prefixes,
            )
            selected = select_for_top_k(preferred, backfill, top_k)
        else:
            selected = [(nws, "preferred") for nws in filtered[:top_k]]

        out: list[dict[str, Any]] = []
        for nws, ranking in selected:
            meta = dict(nws.node.metadata or {})
            tier = verification_tier(meta)
            text = nws.node.get_content(metadata_mode="none")
            excerpt = text.strip().replace("\r\n", "\n")
            if ranking == "backfill" or tier == 0:
                if not excerpt.startswith(UNVERIFIED_EXCERPT_PREFIX.strip()):
                    excerpt = UNVERIFIED_EXCERPT_PREFIX + excerpt
            if len(excerpt) > 900:
                excerpt = excerpt[:900] + "…"
            out.append(
                {
                    "chunk_id": nws.node.node_id,
                    "score": float(nws.score or 0.0),
                    "file_path": meta.get("file_path", ""),
                    "verified_status": meta.get("verified_status", ""),
                    "trust": trust_label(tier),
                    "ranking": ranking,
                    "metadata": {k: meta[k] for k in sorted(meta.keys()) if k != "file_path"},
                    "excerpt": excerpt,
                }
            )
        return out

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        self._ensure_loaded()
        node = self._nodes_by_id.get(chunk_id)
        if node is None:
            return {"ok": False, "error": f"Unknown chunk_id: {chunk_id}"}
        meta = dict(node.metadata or {})
        return {
            "ok": True,
            "chunk_id": node.node_id,
            "file_path": meta.get("file_path", ""),
            "metadata": meta,
            "text": node.get_content(metadata_mode="none"),
        }
