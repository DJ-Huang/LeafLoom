from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


def _default_builtin_exclude() -> tuple[str, ...]:
    """Default gitignore-style lines (always applied)."""
    return (
        ".obsidian/**",
        ".git/**",
        ".vault-rag/**",
        "node_modules/**",
    )


# Any path segment (folder or file name) matching case-insensitively → skip that .md
BUILTIN_EXCLUDE_DIR_NAMES: tuple[str, ...] = (
    ".obsidian",
    ".git",
    ".vault-rag",
    "node_modules",
    "_index",
)


class Settings(BaseSettings):
    """Load from environment variables and optional `.env` in cwd."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Default pydantic-settings order lets OS/IDE env beat `.env`. Cursor often
        # inherits INDEX_IN_VAULT=false from an old shell, which hides vault output.
        # Treat repo `vault-rag/.env` as source of truth over stray env vars.
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    vault_root: Path = Field(
        default=Path(r"C:\ExampleVault Knowledge\DJ knowledge"),
        description="Obsidian vault root (folder that contains notes).",
    )
    index_in_vault: bool = Field(
        default=True,
        description="If true, index artifacts live under VAULT_ROOT / vault_index_folder.",
    )
    vault_index_folder: str = Field(
        default=".vault-rag",
        description="Subfolder under vault for LanceDB + nodes.jsonl (dot-folder, Obsidian can exclude from graph).",
    )
    index_dir: Path = Field(
        default=Path("_index"),
        description="When index_in_vault=false: index under vault-rag project (relative or absolute).",
    )
    load_ragignore_file: bool = Field(
        default=True,
        description="If vault_root/.ragignore exists, merge its rules into path exclusions.",
    )
    exclude_dot_prefixed_dir_segments: bool = Field(
        default=True,
        description=(
            "If true, skip any .md whose relative path has a directory segment starting with '.' "
            "(e.g. .codely-cli/, .obsidian/). Set EXCLUDE_DOT_PREFIXED_DIR_SEGMENTS=false to disable."
        ),
    )

    @field_validator(
        "index_in_vault",
        "load_ragignore_file",
        "exclude_dot_prefixed_dir_segments",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    builtin_exclude_pathspec: tuple[str, ...] = Field(
        default_factory=_default_builtin_exclude,
        description="Always-on gitignore-style patterns (relative to vault root).",
    )
    exclude_pathspec_extra: tuple[str, ...] = Field(
        default=(),
        description="Extra gitignore-style lines (see EXCLUDE_PATHSPEC_EXTRA env).",
    )
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    embedding_model: str = Field(default="bge-m3")
    embed_dim: int = Field(default=1024, description="Dense dimension for bge-m3.")
    lance_table: str = Field(default="vault_chunks")
    exclude_dir_names_extra: tuple[str, ...] = Field(
        default=(),
        description=(
            "Extra directory (or file) name tokens: if any path segment matches case-insensitively, "
            "skip that markdown. Merged with built-ins; set EXCLUDE_DIR_NAMES_EXTRA (pipe or comma)."
        ),
    )
    exclude_globs: tuple[str, ...] = Field(
        default=(),
        description="Substring rules on relative path (case-insensitive); legacy simple excludes.",
    )

    @field_validator("exclude_dir_names_extra", "exclude_globs", "exclude_pathspec_extra", mode="before")
    @classmethod
    def _split_pipe_or_comma(cls, v: object) -> tuple[str, ...]:
        if v is None or v == "":
            return ()
        if isinstance(v, str):
            sep = "|" if "|" in v else ","
            return tuple(s.strip() for s in v.split(sep) if s.strip())
        if isinstance(v, (list, tuple)):
            return tuple(str(x).strip() for x in v if str(x).strip())
        return (str(v),)

    vector_top_k: int = Field(default=40)
    bm25_top_k: int = Field(default=40)
    rrf_k: int = Field(default=60)

    def merged_exclude_dir_names(self) -> tuple[str, ...]:
        """Built-in dir-name excludes plus `exclude_dir_names_extra`, deduped case-insensitively."""
        out: list[str] = []
        seen_lower: set[str] = set()
        for name in (*BUILTIN_EXCLUDE_DIR_NAMES, *self.exclude_dir_names_extra):
            n = str(name).strip()
            if not n:
                continue
            low = n.lower()
            if low in seen_lower:
                continue
            seen_lower.add(low)
            out.append(n)
        return tuple(out)

    def resolved_index_dir(self, project_root: Path) -> Path:
        """Where LanceDB + nodes.jsonl + status.json are stored."""
        if self.index_in_vault:
            return (self.vault_root.expanduser().resolve() / self.vault_index_folder).resolve()
        p = self.index_dir
        if p.is_absolute():
            return p.resolve()
        return (project_root / p).resolve()
