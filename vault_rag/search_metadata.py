"""Dependency-free metadata rules shared by file service and retrieval adapters."""
from __future__ import annotations
import json,re
from pathlib import Path
from typing import Any

def _normalize_posix_path(value: str) -> str:
    return value.replace('\\','/').strip('/')

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
