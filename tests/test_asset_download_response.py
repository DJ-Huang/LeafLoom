"""Prepared HTTP downloads always release their local staging lease."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from vault_rag.asset_library_routes import PreparedFileResponse


class PreparedResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_response_and_disconnected_response_both_release_lease(self):
        for error in (None,asyncio.CancelledError()):
            service=Mock()
            response=PreparedFileResponse('/fictional/attachment.bin',downloads=service,
                root='/fictional/vault',job_id='fictional-job',media_type='application/octet-stream')
            with patch('starlette.responses.FileResponse.__call__',new=AsyncMock(side_effect=error)):
                if error:
                    with self.assertRaises(asyncio.CancelledError):await response({},None,None)
                else:await response({},None,None)
            service.release_handle.assert_called_once_with('/fictional/vault','fictional-job')


if __name__=='__main__':unittest.main()
