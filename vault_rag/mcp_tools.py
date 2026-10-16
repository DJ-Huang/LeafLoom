"""The production HTTP MCP surface; legacy retrieval and explicit workspace tools."""
from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from vault_rag.local_state import ConflictError
from vault_rag.note_operations import NoteError


def build_workspace_mcp(config, runtime, operations, access, legacy_token):
    mcp = FastMCP('vault-rag', host='127.0.0.1', port=config.data.get('port', 18080),
                  stateless_http=True, json_response=True)

    def tool(*, write=False, additive=False):
        return mcp.tool(annotations=ToolAnnotations(readOnlyHint=not write,
                        destructiveHint=write and not additive, openWorldHint=False), structured_output=False)

    def principal(ctx):
        request = ctx.request_context.request
        if request is None:
            raise PermissionError('HTTP MCP authentication required')
        try:
            loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            loopback = False
        return access.principal(request.headers.get('authorization', ''), legacy_token, loopback=loopback)

    async def call(ctx, fn, *args, legacy=False, write=False, **kwargs):
        # Extract the request before crossing into the worker thread. Check its
        # credential again under the access lock immediately before mutation.
        request = ctx.request_context.request
        header = request.headers.get('authorization', '') if request else ''
        def execute():
            runtime.foreground_begin()
            try:
                with access.lock:
                    who = principal(ctx)
                    if not legacy:
                        access.require(who, write=write)
                    if write:
                        return fn(*args, **kwargs)
                return fn(*args, **kwargs)
            finally:
                runtime.foreground_end()
        try:
            value = await asyncio.to_thread(execute)
            failed = isinstance(value, dict) and bool(value.get('error')) and value.get('ok') is False
            if failed:
                value.setdefault('error_code', 'retrieval_failed')
        except Exception as error:
            if isinstance(error, NoteError):
                code, details = error.code, error.details
            else:
                code = ('permission_denied' if isinstance(error, PermissionError) else
                        'write_conflict' if isinstance(error, ConflictError) else
                        'not_found' if isinstance(error, FileNotFoundError) else
                        'invalid_text_encoding' if isinstance(error, UnicodeError) else
                        'invalid_request' if isinstance(error, (ValueError, TypeError)) else 'operation_failed')
                details = {}
            # Do not reflect arbitrary request headers or internal exception paths.
            message = str(error) if isinstance(error, (NoteError, ConflictError, PermissionError, ValueError)) else code.replace('_', ' ')
            if header:
                message = message.replace(header, '[credential]').replace(header.removeprefix('Bearer '), '[credential]')
            value = {'ok': False, 'error_code': code, 'error': message, **details}
            failed = True
        # JSON-roundtrip also normalizes YAML dates/other metadata for MCP JSON.
        text = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
        return CallToolResult(content=[TextContent(type='text', text=text)], structuredContent=json.loads(text), isError=failed)

    @tool()
    async def vault_search(query: str, ctx: Context, top_k: int = 3, note_type: str | None = None,
                           domain: str | None = None, compact: bool = True, mode: str = 'hybrid') -> CallToolResult:
        """Search selected knowledge directories only: hybrid|wiki|rag|keyword. Excludes rules.
        Use domain=estimation for cost-estimation cards. For all workspace notes use vault_find_notes.
        Sources retain verification limits; fetch full notes for formulas.
        """
        return await call(ctx, runtime.knowledge.search, query, top_k=top_k, type_=note_type,
                          domain=domain, compact=compact, mode=mode, legacy=True)

    @tool()
    async def rule_search(query: str, ctx: Context, top_k: int = 3, domain: str | None = None,
                          compact: bool = True) -> CallToolResult:
        """Search selected rule directories only. Use for missing relevant rules."""
        if domain == 'pcg':
            return await call(ctx, lambda: {'ok': True, 'no_relevant_hit': True, 'results': []}, legacy=True)
        return await call(ctx, runtime.knowledge.search, query, top_k=top_k, domain=domain,
                          rules=True, compact=compact, legacy=True)

    @tool()
    async def vault_get_chunk(chunk_id: str, ctx: Context) -> CallToolResult:
        """Read a complete retrieved evidence chunk. Changed or withdrawn sources are unavailable."""
        return await call(ctx, runtime.knowledge.get_chunk, chunk_id, legacy=True)

    @tool()
    async def vault_get_note(note_id: str, ctx: Context) -> CallToolResult:
        """Legacy full-note read within the selected retrieval scope. Use vault_read_note for workspace access."""
        return await call(ctx, runtime.knowledge.get_note, note_id, legacy=True)

    @tool()
    async def vault_index_status(ctx: Context) -> CallToolResult:
        """Read index/model/sync status, current workspace_revision and this connection's permissions."""
        def status():
            return {**runtime.status(), 'workspace_revision': operations.workspace_revision,
                    'capabilities': access.capabilities(principal(ctx)),
                    'supported_formats': ['markdown', 'txt', 'html'],
                    'workspace_access': 'all connected notes; retrieval uses selected directories only'}
        return await call(ctx, status, legacy=True)

    @tool()
    async def vault_list_directory(ctx: Context, path: str = '', limit: int = 50, cursor: str = '') -> CallToolResult:
        """List a connected folder, including notes, subfolders and attachment metadata. Paginated; no RAG selection required."""
        return await call(ctx, operations.list_directory, path, limit, cursor)

    @tool()
    async def vault_find_notes(ctx: Context, query: str = '', folder: str = '', tags: list[str] | None = None,
                               format: Literal['markdown', 'txt', 'html'] | None = None,
                               limit: int = 50, cursor: str = '') -> CallToolResult:
        """Find all connected notes by path/title/source keywords and AND tags, including archives and unindexed HTML.
        No embedding model needed. metadata_pending means retry; incomplete identifies unreadable content.
        """
        return await call(ctx, operations.find, query, folder, tags, format, limit, cursor)

    @tool()
    async def vault_read_note(note_id: str, ctx: Context, offset: int = 0, limit: int = 12000) -> CallToolResult:
        """Read disk Markdown/TXT/HTML by exact relative path or unique ID/name, regardless of RAG scope.
        Character offsets; max 24000 per page. Retain revision and workspace_revision for writes.
        Unsaved editor drafts are not included. Ambiguous names return candidates.
        """
        return await call(ctx, operations.read, note_id, offset, limit)

    @tool()
    async def vault_query(query: str, ctx: Context, limit: int = 50, cursor: str = '') -> CallToolResult:
        """Query Markdown properties with the existing safe TABLE/LIST, FROM, WHERE, GROUP BY, SORT and LIMIT grammar.
        No arbitrary code or SQL execution. All connected Markdown notes are eligible.
        """
        return await call(ctx, operations.query, query, limit, cursor)

    @tool(write=True, additive=True)
    async def vault_create_note(path: str, workspace_revision: str, ctx: Context,
                                text: str | None = None, template: str | None = None) -> CallToolResult:
        """Create Markdown/TXT/HTML at an exact path in an existing folder, using text OR a listed template.
        Never overwrites. Missing text creates an empty note. Saves immediately when write access is enabled.
        """
        return await call(ctx, operations.create, path, workspace_revision, text, template, write=True)

    @tool(write=True)
    async def vault_update_note(path: str, workspace_revision: str, expected_revision: str, ctx: Context,
                                mode: Literal['replace', 'edit', 'append'] = 'replace', text: str | None = None,
                                edits: list[dict[str, str]] | None = None) -> CallToolResult:
        """Save a note with read-time revision. replace/append use text; replace targets the COMPLETE source including YAML.
        edit uses [{old_text,new_text}], each uniquely matching the original source without overlap; all edits succeed or none save.
        Keeps prior history and encoding/newlines. Conflicts require re-reading and merging, never a blind retry.
        """
        return await call(ctx, operations.update, path, workspace_revision, expected_revision, mode, text, edits, write=True)

    @tool(write=True)
    async def vault_update_properties(path: str, workspace_revision: str, expected_revision: str,
                                      updates: dict[str, Any], ctx: Context) -> CallToolResult:
        """Update Markdown YAML properties while preserving unknown fields and comments. null removes a property.
        Requires read-time note and workspace revisions; saves immediately with history.
        """
        return await call(ctx, operations.properties, path, workspace_revision, expected_revision, updates, write=True)

    @tool(write=True, additive=True)
    async def vault_create_folder(path: str, workspace_revision: str, ctx: Context) -> CallToolResult:
        """Create one folder in an existing parent. Cannot replace an existing name or modify the vault root."""
        return await call(ctx, operations.create_folder, path, workspace_revision, write=True)

    @tool(write=True)
    async def vault_move(path: str, destination: str, workspace_revision: str, ctx: Context,
                         dry_run: bool = True, operation_token: str | None = None, limit: int = 50, cursor: str = '') -> CallToolResult:
        """Move/rename a note or folder, repairing Markdown references. First call dry_run=true for affected paths and token.
        Commit the SAME arguments with dry_run=false and operation_token within 5 minutes. Changed files invalidate the preview.
        Folders include attachments; protected/hidden/link entries are rejected. Target must not exist.
        """
        return await call(ctx, operations.operation, 'move', path, workspace_revision, destination, dry_run, operation_token, limit, cursor, write=True)

    @tool(write=True)
    async def vault_delete(path: str, workspace_revision: str, ctx: Context,
                           dry_run: bool = True, operation_token: str | None = None, limit: int = 50, cursor: str = '') -> CallToolResult:
        """Move a note or complete folder to recoverable trash. Preview first; commit dry_run=false with its operation_token.
        Protected/hidden/link entries are rejected. No permanent deletion tool is exposed.
        """
        return await call(ctx, operations.operation, 'delete', path, workspace_revision, '', dry_run, operation_token, limit, cursor, write=True)

    @tool()
    async def vault_list_records(ctx: Context, kind: Literal['history', 'trash', 'operations'] = 'history',
                                 path: str | None = None, limit: int = 50, cursor: str = '') -> CallToolResult:
        """List recoverable note versions, trash or move journals. Read a record before restoring it."""
        return await call(ctx, operations.records, kind, path, limit, cursor)

    @tool()
    async def vault_read_record(kind: Literal['history', 'trash', 'operations'], id: str, ctx: Context,
                                offset: int = 0, limit: int = 12000, path_limit: int = 50, path_cursor: str = '') -> CallToolResult:
        """Preview a record without restoring it. Retain record_revision, expected_revision and workspace_revision for restore."""
        return await call(ctx, operations.read_record, kind, id, offset, limit, path_limit, path_cursor)

    @tool(write=True)
    async def vault_restore(kind: Literal['history', 'trash', 'operations'], id: str, workspace_revision: str,
                            expected_revision: str, record_revision: str, ctx: Context) -> CallToolResult:
        """Restore a previewed note version/trash item or undo a completed move. Use all versions from vault_read_record.
        Rejects changes since preview, occupied trash destinations and edits made after a move.
        """
        return await call(ctx, operations.restore, kind, id, workspace_revision, expected_revision, record_revision, write=True)

    @tool()
    async def vault_links(path: str, ctx: Context, limit: int = 50, cursor: str = '') -> CallToolResult:
        """List incoming/outgoing Markdown links for a note across the connected workspace."""
        return await call(ctx, operations.links, path, limit, cursor)

    @tool()
    async def vault_graph(path: str, ctx: Context, limit: int = 50, cursor: str = '') -> CallToolResult:
        """Read a paginated local Markdown graph centered on a note. Edges contain endpoints on the returned page."""
        return await call(ctx, operations.graph, path, limit, cursor)

    @tool()
    async def vault_list_templates(ctx: Context, limit: int = 50, cursor: str = '') -> CallToolResult:
        """List templates from the configured template folder. Use a returned path with vault_create_note."""
        return await call(ctx, operations.templates, limit, cursor)

    @tool(write=True, additive=True)
    async def vault_daily_note(workspace_revision: str, ctx: Context, date: str | None = None) -> CallToolResult:
        """Create a daily Markdown note for YYYY-MM-DD (default this computer's local date). Existing notes are returned unchanged."""
        return await call(ctx, operations.daily, workspace_revision, date, write=True)

    @tool(write=True, additive=True)
    async def vault_reindex(workspace_revision: str, ctx: Context) -> CallToolResult:
        """Queue index synchronization and return immediately. Does not download a model or change retrieval scope."""
        return await call(ctx, operations.reindex, workspace_revision, write=True)

    return mcp
