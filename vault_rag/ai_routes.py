"""Authenticated browser routes and a capability-scoped MCP for CLI sessions."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import StreamingResponse

from vault_rag.local_state import ConflictError


def ai_mcp_server(ai, design=None):
    server = FastMCP('vault-ai', host='127.0.0.1', port=ai.config.data.get('port', 18080),
                     streamable_http_path='/ai-mcp', stateless_http=True, json_response=True)

    def conversation(ctx):
        request = ctx.request_context.request
        return ai.authorized(request.headers.get('authorization', '') if request else '')

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def knowledge_search(query: str, ctx: Context, top_k: int = 3, mode: str = 'hybrid') -> str:
        """Search the configured knowledge corpus. Cite returned note paths, then read needed notes."""
        with ai.config.lock:
            conversation(ctx)
            if mode not in ('hybrid', 'wiki', 'rag', 'keyword'):
                raise ValueError('检索模式无效')
            return json.dumps(ai.runtime.knowledge.search(query, top_k=max(1, min(10, top_k)), mode=mode), ensure_ascii=False, default=str)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def read_note(path: str, ctx: Context, offset: int = 0, limit: int = 12000) -> str:
        """Read a note or the current unsaved draft. Retain base_hash to propose edits; paginate long notes."""
        return json.dumps(ai.read_note(conversation(ctx), path, offset, limit), ensure_ascii=False)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def propose_note(path: str, text: str, ctx: Context, base_hash: str = '', create: bool = False) -> str:
        """Propose complete Markdown/TXT content for user preview. Does NOT write any note.
        For existing notes supply read_note's base_hash. For a new note set create=true.
        """
        return json.dumps(ai.propose(conversation(ctx), path, text, base_hash, create), ensure_ascii=False)

    if design is not None:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
        def design_list_projects(ctx: Context, folder: str = '') -> str:
            """List all Design Studio projects in the connected vault."""
            conversation(ctx)
            return json.dumps(design.list_projects(folder), ensure_ascii=False, default=str)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
        def design_get_project(directory: str, ctx: Context, board_id: str | None = None) -> str:
            """Read a Design Studio project's spec, artboards, and saved layer transforms."""
            conversation(ctx)
            return json.dumps(design.get_project(directory, board_id), ensure_ascii=False, default=str)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        def design_update_layers(directory: str, board_id: str, layers: dict, ctx: Context, merge: bool = True) -> str:
            """Apply Figma-like layer transforms (tx, ty, x, y, width, height, scaleX, scaleY, rotate, flipX, flipY, opacity, zIndex, text) to a design board."""
            conversation(ctx)
            return json.dumps(design.save_transforms(directory, board_id, layers, merge=merge), ensure_ascii=False, default=str)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
        def design_document(directory: str, ctx: Context, page_id: str | None = None, manifest: bool = False) -> str:
            """Read managed design pages/elements/assets/components/scripts and revision. Use stable IDs in design_operations."""
            conversation(ctx)
            return json.dumps(design.documents.manifest(directory) if manifest else design.documents.read(directory, page_id), ensure_ascii=False)

        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
        def design_operations(directory: str, commands: list[dict], expected_revision: str, operation_id: str,
                              workspace_revision: str, ctx: Context, label: str = '') -> str:
            """Apply one directly undoable AI instruction. Commands type page.create/update/delete, node.create/update/replace/delete/move,
            component.create/update/detach, asset.update/replace, project.update. node.update uses {page_id,node_id,patch}.
            Nodes support script:{source:'export function mount(ctx){...}',props,parameters} and animation:{preset,trigger,duration,delay,iterations,easing}.
            ctx provides el,props,state,find,on,onEvent,emit,animate,timers,assets,navigate and overlays. Retain expected_revision; stale writes save nothing.
            """
            current = conversation(ctx)
            turn = ai.rows('SELECT references_json FROM turns WHERE id=?', (ai.active_turns.get(current['id'], ''),))
            references = json.loads(turn[0]['references_json']) if turn else []
            from vault_rag.local_state import relative
            if not any(ref.get('kind') == 'design' and ref.get('directory') == relative(directory) for ref in references):
                raise ValueError('Attach this Design Studio project before applying AI edits')
            return json.dumps(design.documents.apply(directory, commands, expected_revision, operation_id,
                                                      label=label, workspace_revision=workspace_revision), ensure_ascii=False)

    return server


def ai_router(ai):
    router = APIRouter(prefix='/api/ai')

    def root(body):
        if not isinstance(body, dict) or body.get('root') != ai.root():
            raise ConflictError('知识库已切换，请重新打开 AI 对话')

    @router.get('/providers')
    async def providers():
        return ai.providers()

    @router.get('/conversations')
    async def conversations():
        return ai.conversations()

    @router.post('/conversations')
    async def create(request: Request):
        body = await request.json()
        root(body)
        return ai.create(body.get('provider'), body.get('title', ''), body.get('client_id'))

    @router.get('/conversations/{key}')
    async def detail(key: str):
        return ai.detail(key)

    @router.patch('/conversations/{key}')
    async def rename(key: str, request: Request):
        body = await request.json()
        root(body)
        return ai.rename(key, body.get('title'))

    @router.post('/conversations/{key}/messages')
    async def send(key: str, request: Request):
        body = await request.json()
        root(body)
        return await ai.send(key, body)

    @router.post('/conversations/{key}/stop')
    async def stop(key: str, request: Request):
        root(await request.json())
        return await ai.stop(key)

    @router.post('/conversations/{key}/proposals/{proposal_id}/accept')
    async def accept(key: str, proposal_id: str, request: Request):
        body = await request.json()
        root(body)
        return ai.accept(key, proposal_id, body)

    @router.post('/conversations/{key}/proposals/{proposal_id}/reject')
    async def reject(key: str, proposal_id: str, request: Request):
        root(await request.json())
        return ai.reject(key, proposal_id)

    @router.post('/conversations/{key}/proposals/{proposal_id}/applied')
    async def applied(key: str, proposal_id: str, request: Request):
        root(await request.json())
        return ai.applied(key, proposal_id)

    @router.get('/events')
    async def events(request: Request):
        ai.loop = asyncio.get_running_loop()
        initial_root = ai.root()

        async def stream():
            queue = asyncio.Queue(maxsize=128)
            ai.listeners.add(queue)
            try:
                yield 'data: ' + json.dumps({'type': 'reset', 'sequence': ai.sequence}) + '\n\n'
                while not ai.closed and not await request.is_disconnected():
                    if ai.root() != initial_root:
                        yield 'data: {"type":"closed"}\n\n'
                        return
                    try:
                        message = await asyncio.wait_for(queue.get(), 15)
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n'
                        continue
                    if message.get('conversation_id'):
                        try:
                            ai.conversation(message['conversation_id'])
                        except ValueError:
                            continue
                    yield 'id: ' + str(message['sequence']) + '\ndata: ' + json.dumps(message, ensure_ascii=False) + '\n\n'
            finally:
                ai.listeners.discard(queue)

        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    return router
