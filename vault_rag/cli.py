from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.traceback import install as rich_install

from vault_rag.index_build import build_index
from vault_rag.settings import Settings

rich_install(show_locals=False)
app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _print_json_utf8(data: object) -> None:
    """Avoid Windows cp1252 UnicodeEncodeError when printing CJK."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8"))


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@app.command()
def reindex() -> None:
    """Rebuild LanceDB + nodes.jsonl + status.json (full rebuild)."""
    logging.basicConfig(level=logging.INFO)
    root = project_root()
    settings = Settings()
    console.print(f"[bold]Vault[/bold]: {settings.vault_root}")
    console.print(f"[bold]Index dir[/bold]: {settings.resolved_index_dir(root)}")
    status = build_index(root, settings)
    _print_json_utf8(status)


@app.command()
def doctor() -> None:
    """Print resolved settings and whether index artifacts exist."""
    root = project_root()
    settings = Settings()
    idx = settings.resolved_index_dir(root)
    artifacts = {
        "vault_root_exists": settings.vault_root.is_dir(),
        "nodes_jsonl": (idx / "nodes.jsonl").is_file(),
        "lancedb_dir": (idx / "lancedb").exists(),
        "status_json": (idx / "status.json").is_file(),
    }
    payload = {
        "vault_root": str(settings.vault_root),
        "index_dir": str(idx),
        "embedding_model": settings.embedding_model,
        "ollama_base_url": settings.ollama_base_url,
        "artifacts": artifacts,
    }
    _print_json_utf8(payload)


@app.command()
def audit(
    write_report: bool = typer.Option(
        False,
        "--write-report",
        help="Write AUDIT-last.md under the configured index directory.",
    ),
) -> None:
    """Scan vault: counts, skips, largest files (preflight before reindex)."""
    from vault_rag.vault_audit import audit_vault, write_audit_report_md

    root = project_root()
    settings = Settings()
    data = audit_vault(settings, root)
    _print_json_utf8(data)
    if write_report:
        path = write_audit_report_md(settings, root)
        console.print(f"[bold]Wrote[/bold] {path}")


@app.command()
def search(query: str, top_k: int = 8, note_type: str | None = None, domain: str | None = None) -> None:
    """Run one hybrid search locally (uses the built index)."""
    from vault_rag.service import VaultRagService

    svc = VaultRagService(project_root(), Settings())
    rows = svc.search(query, top_k=top_k, type_=note_type, domain=domain)
    _print_json_utf8({"ok": True, "results": rows})


def main() -> None:
    app()


if __name__ == "__main__":
    main()
