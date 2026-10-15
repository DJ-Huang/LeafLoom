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
    """Queue a rebuild in the shared service; no duplicate model process."""
    from vault_rag.service_control import request
    _print_json_utf8(request('/api/reindex', {}))

@app.command()
def serve() -> None:
    """Run the shared web and HTTP MCP service."""
    from vault_rag.web_server import serve as run
    run()

@app.command()
def service(action: str = typer.Argument('status')) -> None:
    """Manage the macOS/Windows user service; Windows also supports enable/disable-autostart."""
    from vault_rag.service_control import control
    control(action)

@app.command()
def local_resolver(action: str = typer.Argument('status')) -> None:
    """Install/remove scoped Safari name resolution (macOS administrator dialog)."""
    from vault_rag.local_state import LocalConfig
    from vault_rag.html_projects import HtmlProjects
    from vault_rag.local_dns import LocalDns
    if action not in ('status','install','remove'):raise typer.BadParameter('Use status/install/remove')
    config=LocalConfig();websites=HtmlProjects(config,config.data['port'])
    resolver=LocalDns(websites.install_id,config.data['port'])
    _print_json_utf8(resolver.status() if action=='status' else resolver.configure(action=='install'))

@app.command()
def tray() -> None:
    """Run the Windows notification-area icon without loading the model."""
    from vault_rag.windows_entry import main as run
    run(['tray'])

@app.command()
def model_prepare() -> None:
    """Download and pin the official local model before normal offline use."""
    from vault_rag.embedded_model import EmbeddedModel
    from vault_rag.local_state import LocalConfig
    _print_json_utf8(EmbeddedModel(LocalConfig().directory).prepare())


@app.command()
def doctor() -> None:
    """Inspect the shared service without loading another model."""
    from vault_rag.service_control import request
    _print_json_utf8(request('/api/status'))


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
def search(query: str, top_k: int = 3, note_type: str | None = None, domain: str | None = None, mode: str = 'hybrid') -> None:
    """Query the shared service without loading a second model."""
    from vault_rag.service_control import request
    _print_json_utf8(request('/api/knowledge-search', {'query':query,'top_k':top_k,'note_type':note_type,'domain':domain,'mode':mode}))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
