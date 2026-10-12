from __future__ import annotations

import gc
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.schema import NodeWithScore, TextNode

from vault_rag.fusion import reciprocal_rank_fusion
from vault_rag.nodes_store import read_nodes_jsonl
from vault_rag.settings import Settings
from vault_rag.content_scope import CONTENT_SCOPE_VERSION, indexed_path_is_in_scope
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


def _path_under_prefix(
    file_path: str,
    prefix: str | tuple[str, ...] | None,
) -> bool:
    if not prefix:
        return True
    if isinstance(prefix, tuple):
        return any(_path_under_prefix(file_path, item) for item in prefix)
    rel = _normalize_posix_path(file_path)
    root = _normalize_posix_path(prefix)
    return rel == root or rel.startswith(f"{root}/")


def _path_excluded_by_prefixes(file_path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if _path_under_prefix(file_path, prefix):
            return True
    return False


_PATH_NOTE_TYPES = {
    "bugfix": "bugfix",
    "concepts": "concept",
    "decisions": "decision",
    "experience": "experience",
    "features": "feature",
    "guides": "guide",
    "mocs": "moc",
    "performance": "performance",
    "pitfalls": "pitfall",
    "rules": "rule",
    "tips": "tip",
}

_DOMAIN_MARKERS = {
    "comfyui": ("comfyui", "ta-toolkit", "nodebase", "node_base"),
    "dcc": (
        "blender",
        "houdini",
        "substance painter",
        "substance designer",
        "maya",
        "zbrush",
        "bpy",
        "bmesh",
    ),
    "pcg": ("pcg-ai", "pcg ai", ".pcg-ai"),
    "unity": (
        "unity",
        "tuanjie",
        "hmirp",
        "hmicore",
        "cpt-tmp-",
        "shadergraph",
        "rendertexture",
        "scriptable render pass",
        "textmeshpro",
        "universal render pipeline",
    ),
}


def _metadata_tokens(value: Any) -> set[str]:
    """Normalize scalar, CSV, JSON-list, or list metadata into lowercase tokens."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        raw = str(value).strip()
        if not raw:
            return set()
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = raw
        values = parsed if isinstance(parsed, list) else re.split(r"[,|]", str(parsed))
    return {str(item).strip().lower() for item in values if str(item).strip()}


def _effective_note_type(meta: dict[str, Any]) -> str:
    explicit = str(meta.get("type", "")).strip().lower()
    if explicit:
        return explicit

    for tag in _metadata_tokens(meta.get("tags")):
        if tag.startswith("type/"):
            tagged = tag.split("/", 1)[1]
            return "tip" if tagged == "quick-tip" else tagged

    file_path = _normalize_posix_path(str(meta.get("file_path", "")))
    top_level = file_path.split("/", 1)[0].lower() if file_path else ""
    return _PATH_NOTE_TYPES.get(top_level, "")


def _effective_domains(meta: dict[str, Any]) -> set[str]:
    """Use declared domains first, then conservatively infer obvious legacy scopes."""
    declared = _metadata_tokens(meta.get("domain"))
    if declared:
        return declared

    file_path = _normalize_posix_path(str(meta.get("file_path", ""))).lower()
    if file_path.startswith("dcc/"):
        return {"dcc"}

    searchable = " ".join(
        str(meta.get(key, ""))
        for key in ("file_path", "name", "tags", "techStack", "categories", "category")
    ).lower()
    inferred = {
        domain
        for domain, markers in _DOMAIN_MARKERS.items()
        if any(marker in searchable for marker in markers)
    }
    return inferred


def _metadata_match(meta: dict[str, Any], *, type_: str | None, domain: str | None) -> bool:
    if type_ is not None and _effective_note_type(meta) != type_.strip().lower():
        return False
    if domain is not None:
        want = domain.strip().lower()
        domains = _effective_domains(meta)
        # `general` is intentionally strict: specialized or legacy-inferred notes are noise.
        if want == "general":
            return not domains
        # Other domains keep truly unclassified cross-project notes as candidates.
        if domains and want not in domains:
            return False
    return True


def _passes_relevance_gate(
    candidate: NodeWithScore,
    *,
    vector_scores: dict[str, float],
    min_vector_score: float,
) -> bool:
    """Reject top-k filler using embedding similarity, not the relative RRF score."""
    if min_vector_score <= -1.0:
        return True
    return vector_scores.get(candidate.node.node_id, float("-inf")) >= min_vector_score


def _dedupe_candidates(
    candidates: list[NodeWithScore],
    *,
    prefer_rule_id: bool,
    seen: set[str] | None = None,
) -> list[NodeWithScore]:
    """Keep the highest-ranked chunk per note (or rule_id for rule_search)."""
    used = seen if seen is not None else set()
    out: list[NodeWithScore] = []
    for nws in candidates:
        meta = dict(nws.node.metadata or {})
        file_path = _normalize_posix_path(str(meta.get("file_path", "")))
        rule_id = str(meta.get("rule_id", "")).strip()
        key = rule_id if prefer_rule_id and rule_id else file_path or nws.node.node_id
        if key in used:
            continue
        used.add(key)
        out.append(nws)
    return out


def _ensure_required_rules(
    candidates: list[NodeWithScore],
    *,
    all_nodes: list[TextNode],
    required_rule_ids: tuple[str, ...],
    path_prefix: str | tuple[str, ...] | None = None,
) -> list[NodeWithScore]:
    """Pin required rule documents ahead of semantic candidates without duplicating them."""
    if not required_rule_ids:
        return candidates

    existing: dict[str, NodeWithScore] = {}
    for nws in candidates:
        rule_id = str((nws.node.metadata or {}).get("rule_id", "")).strip()
        if rule_id and rule_id not in existing:
            existing[rule_id] = nws

    fallback: dict[str, TextNode] = {}
    required = set(required_rule_ids)
    for node in all_nodes:
        meta = dict(node.metadata or {})
        if not _path_under_prefix(str(meta.get("file_path", "")), path_prefix):
            continue
        rule_id = str(meta.get("rule_id", "")).strip()
        if rule_id in required and rule_id not in fallback:
            fallback[rule_id] = node

    pinned: list[NodeWithScore] = []
    for rule_id in required_rule_ids:
        nws = existing.get(rule_id)
        if nws is None and rule_id in fallback:
            nws = NodeWithScore(node=fallback[rule_id], score=0.0)
        if nws is not None:
            pinned.append(nws)

    return pinned + [
        nws
        for nws in candidates
        if str((nws.node.metadata or {}).get("rule_id", "")).strip() not in required
    ]


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
        self._status_mtime: float | None = None

    def _index_changed_since_load(self) -> bool:
        """True if status.json mtime is newer than what we loaded (reindex happened)."""
        status_path = self.index_dir / "status.json"
        if not status_path.is_file():
            return True
        current = os.stat(status_path).st_mtime
        if self._status_mtime is None or current > self._status_mtime:
            return True
        return False

    def _release_resources(self) -> None:
        """Explicitly release LanceDB native handles and large Python objects.

        LanceDB's Rust core has no close()/__del__; without explicit teardown
        the old table/connection linger until GC eventually drops them, leaking
        ~4 MB per reload (native mmap + Arrow buffers).
        """
        self._vector_retriever = None
        self._bm25 = None
        self._nodes_by_id = {}
        gc.collect()

    def _ensure_loaded(self) -> None:
        status = self.status()
        if not status.get("scope_matches_settings"):
            raise RuntimeError("Index content scope is missing or mismatched. Run `vault-rag reindex` before searching.")
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
        if any(not indexed_path_is_in_scope(str(n.metadata.get("file_path", "")), self.settings) for n in nodes):
            raise RuntimeError("Index contains paths outside the content scope. Run `vault-rag reindex`.")
        self._nodes_by_id = {n.node_id: n for n in nodes}

        # Bypass macOS System proxy so localhost Ollama is not 502'd.
        embed_model = OllamaEmbedding(
            model_name=self.settings.embedding_model,
            base_url=self.settings.ollama_base_url,
            client_kwargs={"trust_env": False},
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
        status_path = self.index_dir / "status.json"
        self._status_mtime = (
            os.stat(status_path).st_mtime if status_path.is_file() else None
        )
        logger.info(
            "Vault RAG loaded: %s chunks, Lance=%s",
            len(nodes),
            lance_path,
        )

    def status(self) -> dict[str, Any]:
        path = self.index_dir / "status.json"
        scope = {
            "vault_root": str(self.settings.vault_root.expanduser().resolve()),
            "vault_content_folder": self.settings.vault_content_folder,
            "vault_content_root": str(self.settings.resolved_content_root()),
            "content_scope_version": CONTENT_SCOPE_VERSION,
        }
        if not path.is_file():
            return {"ok": False, **scope, "scope_matches_settings": False, "error": f"Missing index status at {path}"}
        stored = json.loads(path.read_text(encoding="utf-8"))
        matches = all(stored.get(key) == value for key, value in scope.items())
        return {"ok": True, **stored, **scope, "scope_matches_settings": matches,
                "indexed_content_root": stored.get("vault_content_root")}

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        type_: str | None = None,
        domain: str | None = None,
        path_prefix: str | tuple[str, ...] | None = None,
        path_exclude_prefixes: tuple[str, ...] = (),
        dedupe_by_rule: bool = False,
        required_rule_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        self._ensure_loaded()
        assert self._vector_retriever is not None and self._bm25 is not None

        v_results = self._vector_retriever.retrieve(query)
        b_results = self._bm25.retrieve(query)
        vector_scores = {
            result.node.node_id: float(result.score or 0.0)
            for result in v_results
        }
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
            if not indexed_path_is_in_scope(file_path, self.settings):
                continue
            if not _path_under_prefix(file_path, path_prefix):
                continue
            if _path_excluded_by_prefixes(file_path, path_exclude_prefixes):
                continue
            if _metadata_match(meta, type_=type_, domain=domain) and _passes_relevance_gate(
                nws,
                vector_scores=vector_scores,
                min_vector_score=self.settings.min_vector_score,
            ):
                filtered.append(nws)

        if required_rule_ids:
            filtered = _ensure_required_rules(
                filtered,
                all_nodes=list(self._nodes_by_id.values()),
                required_rule_ids=required_rule_ids,
                path_prefix=path_prefix,
            )

        if self.settings.verification_ranking_enabled:
            preferred, backfill = rank_search_candidates(
                filtered,
                restricted_prefixes=self.settings.unverified_restricted_prefixes,
            )
            seen: set[str] = set()
            preferred = _dedupe_candidates(
                preferred,
                prefer_rule_id=dedupe_by_rule,
                seen=seen,
            )
            backfill = _dedupe_candidates(
                backfill,
                prefer_rule_id=dedupe_by_rule,
                seen=seen,
            )
            selected = select_for_top_k(preferred, backfill, top_k)
        else:
            unique = _dedupe_candidates(filtered, prefer_rule_id=dedupe_by_rule)
            selected = [(nws, "preferred") for nws in unique[:top_k]]

        out: list[dict[str, Any]] = []
        for nws, ranking in selected:
            meta = dict(nws.node.metadata or {})
            tier = verification_tier(meta)
            text = nws.node.get_content(metadata_mode="none")
            excerpt = text.strip().replace("\r\n", "\n")
            if ranking == "backfill" or tier == 0:
                if not excerpt.startswith(UNVERIFIED_EXCERPT_PREFIX.strip()):
                    excerpt = UNVERIFIED_EXCERPT_PREFIX + excerpt
            excerpt_truncated = len(excerpt) > 900
            if excerpt_truncated:
                excerpt = excerpt[:900] + "…"
            out.append(
                {
                    "chunk_id": nws.node.node_id,
                    "score": float(nws.score or 0.0),
                    "vector_score": vector_scores.get(nws.node.node_id),
                    "file_path": meta.get("file_path", ""),
                    "note_type": _effective_note_type(meta),
                    "verified_status": meta.get("verified_status", ""),
                    "trust": trust_label(tier),
                    "ranking": ranking,
                    "match_reason": (
                        "required_rule"
                        if str(meta.get("rule_id", "")).strip() in required_rule_ids
                        else "semantic"
                    ),
                    "metadata": {k: meta[k] for k in sorted(meta.keys()) if k != "file_path"},
                    "excerpt": excerpt,
                    "excerpt_truncated": excerpt_truncated,
                }
            )
        return out

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        self._ensure_loaded()
        node = self._nodes_by_id.get(chunk_id)
        if node is None or not indexed_path_is_in_scope(str(node.metadata.get("file_path", "")), self.settings):
            return {"ok": False, "error": f"Unknown chunk_id: {chunk_id}"}
        meta = dict(node.metadata or {})
        return {
            "ok": True,
            "chunk_id": node.node_id,
            "file_path": meta.get("file_path", ""),
            "metadata": meta,
            "text": node.get_content(metadata_mode="none"),
        }
