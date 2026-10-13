from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from client.authentication import CallbackListener, StoredOAuthProvider
from client.logging import RecordingTransport
from client.storage import FileTokenStorage


@asynccontextmanager
async def connect(config, browser_handler=None):
    with CallbackListener(config) as callback:
        async def redirect(url):
            if browser_handler:
                from urllib.parse import parse_qs, urlsplit
                callback.expected_state = parse_qs(urlsplit(url).query)["state"][0]
                await browser_handler(url)
            else:
                await callback.redirect(url)

        oauth = StoredOAuthProvider(server_url=config.url, client_metadata=OAuthClientMetadata(
            client_name="Learning client: " + config.name, redirect_uris=[AnyUrl(config.callback_url)],
            token_endpoint_auth_method="none", grant_types=["authorization_code", "refresh_token"],
            response_types=["code"], scope="tools offline_access"),
            storage=FileTokenStorage(config), redirect_handler=redirect, callback_handler=callback.callback)
        async with httpx2.AsyncClient(auth=oauth, transport=RecordingTransport(config.log_dir / "http.jsonl"),
                                     timeout=httpx2.Timeout(30, read=180), follow_redirects=True) as http:
            transport = streamable_http_client(config.url, http_client=http)
            async with Client(transport, cache=None) as sdk:
                yield sdk
