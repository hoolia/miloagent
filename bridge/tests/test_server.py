"""The MCP surface (three read-only tools) and GET /signals."""

from __future__ import annotations

import httpx
import pytest
from mcp import Client

from miloagent_bridge.server import build_server

from .conftest import PASSWORD, mock_exports


@pytest.fixture
def server(client, settings):
    return build_server(client, settings)


@pytest.fixture
async def http(server):
    app = server.streamable_http_app(stateless_http=True, host="0.0.0.0")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bridge") as c:
        yield c


async def test_exactly_three_read_only_tools(server):
    async with Client(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {"list_findings", "get_finding", "list_actions"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert "untrusted data" in tool.description


async def test_list_findings_since_and_order(api, server):
    mock_exports(api)
    async with Client(server) as c:
        result = await c.call_tool("list_findings", {"since": "2026-07-14T08:00:00Z"})
    data = result.structured_content
    assert [f["id"] for f in data["findings"]] == [30002, 30001, 29217]
    assert data["count"] == 3


async def test_list_findings_status_filter(api, server):
    mock_exports(api)
    async with Client(server) as c:
        result = await c.call_tool("list_findings", {"status": "acted", "limit": 1})
    assert [f["id"] for f in result.structured_content["findings"]] == [29217]
    assert {c.request.url.params["status"] for c in api.calls if "opportunities" in c.request.url.path} == {"acted"}


async def test_list_findings_bad_status_is_tool_error(api, server):
    async with Client(server) as c:
        result = await c.call_tool("list_findings", {"status": "approved"})
    assert result.is_error


async def test_get_finding(api, server):
    mock_exports(api)
    async with Client(server) as c:
        found = await c.call_tool("get_finding", {"id": 29008})
        missing = await c.call_tool("get_finding", {"id": 1})
    assert found.structured_content["author"] == "example_user"
    assert found.structured_content["draft_response"]
    assert missing.is_error


async def test_list_actions_since(api, server):
    mock_exports(api)
    async with Client(server) as c:
        result = await c.call_tool("list_actions", {"since": "2026-07-20T00:00:00Z"})
    assert [a["id"] for a in result.structured_content["actions"]] == [247]


async def test_no_tool_writes_to_miloagent(api, server):
    mock_exports(api)
    async with Client(server) as c:
        await c.call_tool("list_findings", {})
        await c.call_tool("get_finding", {"id": 29008})
        await c.call_tool("list_actions", {})
    writes = [c.request for c in api.calls if c.request.method != "GET"]
    assert {w.url.path for w in writes} == {"/api/auth/login"}


async def test_signals_endpoint(api, http):
    mock_exports(api)
    resp = await http.get("/signals", params={"since": "2020-01-01T00:00:00Z"})
    assert resp.status_code == 200
    body = resp.json()
    # reddit only, rejected excluded by default, newest first
    assert [s["miloagent"]["id"] for s in body["signals"]] == [30001, 29217, 29008]
    assert all(s["source"] == "reddit" for s in body["signals"])
    statuses = {c.request.url.params["status"] for c in api.calls if "opportunities" in c.request.url.path}
    assert "rejected" not in statuses


async def test_signals_default_window_is_seven_days(api, http):
    mock_exports(api)
    resp = await http.get("/signals")
    assert resp.status_code == 200
    # the acted fixtures are from July 2026, far outside seven days
    ids = {s["miloagent"]["id"] for s in resp.json()["signals"]}
    assert not ids & {29217, 29008}


async def test_signals_bad_since(api, http):
    resp = await http.get("/signals", params={"since": "yesterday"})
    assert resp.status_code == 400


async def test_signals_upstream_failure_is_502(api, http):
    api.get("/api/export/opportunities").mock(return_value=httpx.Response(500))
    resp = await http.get("/signals", params={"since": "2020-01-01T00:00:00Z"})
    assert resp.status_code == 502
    assert PASSWORD not in resp.text


async def test_healthz(http):
    resp = await http.get("/healthz")
    assert resp.json() == {"status": "ok"}
