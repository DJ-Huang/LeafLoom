"""Authenticated HTTP MCP and service lifecycle check in install_smoke's private fixture."""
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def check_mcp(config):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from vault_rag.service_control import base_url
    token=(config.directory/'auth-token').read_text().strip()
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},trust_env=False) as client:
        async with streamable_http_client(base_url(config)+'/mcp',http_client=client) as (read,write,_):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                assert any(tool.name=='vault_index_status' for tool in tools.tools)
                result=await session.call_tool('vault_index_status',{})
                assert not result.isError


def main():
    from vault_rag.local_state import LocalConfig
    from vault_rag.service_control import control,health
    config=LocalConfig()
    assert not config.data.get('root'),'Acceptance must not modify an associated knowledge directory'
    asyncio.run(check_mcp(config))
    if os.environ.get('VAULT_RAG_INSTALL_TEST_SERVER')!='1':
        if sys.platform=='win32':
            # A browser/network reset must not strand a transport and hang stop.
            import socket,struct,time
            for _ in range(8):
                with socket.create_connection(('127.0.0.1',config.data['port']),timeout=5) as client:
                    client.sendall(('GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:%s\r\n\r\n'%config.data['port']).encode())
                    client.recv(4096)
                    client.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('HH',1,0))
            time.sleep(.3)
        control('start',config);control('start',config)
        assert health(config)=='ready'
        if sys.platform=='win32':
            from vault_rag.windows_native import Instance
            with Instance(config.directory,'service') as duplicate:assert not duplicate.primary
        control('stop',config);assert health(config)=='stopped'
        control('start',config);control('restart',config);assert health(config)=='ready'
    print('Authenticated HTTP MCP and service acceptance passed.')


if __name__=='__main__':main()
