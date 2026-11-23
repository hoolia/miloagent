"""The client logs in, reuses its session, and only ever reads."""

from __future__ import annotations

import json

import httpx
import pytest

from miloagent_bridge.client import MiloAgentClient, MiloAgentError, parse_csv, parse_rows

from .conftest import PASSWORD, fixture, mock_exports


async def test_login_once_and_bearer_reused(api, client):
    mock_exports(api)
    await client.opportunities(("acted", "pending"))
    await client.actions()
    login = api.routes[0]
    assert login.call_count == 1
    assert json.loads(login.calls.last.request.content) == {"username": "admin", "password": PASSWORD}
    for call in api.calls[1:]:
        assert call.request.headers["Authorization"] == "Bearer tok-1"


async def test_relogin_once_after_miloagent_restart(api, client):
    answers = iter([httpx.Response(401), httpx.Response(200, text=fixture("actions.json"))])
    api.get("/api/actions").mock(side_effect=lambda r: next(answers))
    rows = await client.actions()
    assert len(rows) == 2
    assert api.routes[0].call_count == 2


async def test_401_keeps_token_another_request_refreshed(api, client):
    client._token = "tok-0"

    def actions(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer tok-0":
            # a concurrent request logged in again while this one was in flight
            client._token = "tok-2"
            return httpx.Response(401)
        return httpx.Response(200, text=fixture("actions.json"))

    route = api.get("/api/actions").mock(side_effect=actions)
    rows = await client.actions()
    assert len(rows) == 2
    assert api.routes[0].call_count == 0
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok-2"


@pytest.mark.parametrize("answer", [httpx.Response(200, text="<html>"), httpx.Response(200, json=["tok"])])
async def test_malformed_login_answer_is_an_error(api, client, answer):
    api.post("/api/auth/login").mock(return_value=answer)
    with pytest.raises(MiloAgentError, match="returned no token"):
        await client.actions()


async def test_persistent_401_is_an_error_without_password(api, client):
    api.get("/api/actions").mock(return_value=httpx.Response(401))
    with pytest.raises(MiloAgentError) as exc:
        await client.actions()
    assert PASSWORD not in str(exc.value)


async def test_failed_login_hides_password(api, client):
    api.post("/api/auth/login").mock(return_value=httpx.Response(401, json={"detail": "Invalid credentials"}))
    with pytest.raises(MiloAgentError, match="login failed: HTTP 401") as exc:
        await client.opportunities(("acted",))
    assert PASSWORD not in str(exc.value)


async def test_actions_asks_maximum(api, client):
    mock_exports(api)
    await client.actions()
    assert api.calls.last.request.url.params["limit"] == "200"


async def test_miloagent_error_body_is_an_error(api, client):
    api.get("/api/actions").mock(return_value=httpx.Response(200, json={"error": "database is locked"}))
    with pytest.raises(MiloAgentError, match="database is locked"):
        await client.actions()


async def test_only_login_and_exports_are_requested(api, client):
    mock_exports(api)
    await client.opportunities()
    await client.actions()
    for call in api.calls:
        req = call.request
        if req.method == "POST":
            assert req.url.path == "/api/auth/login"
        else:
            assert req.method == "GET"
            assert req.url.path in ("/api/export/opportunities", "/api/actions")


def test_client_has_no_generic_request_method():
    public = {n for n in dir(MiloAgentClient) if not n.startswith("_")}
    assert public == {"aclose", "opportunities", "actions"}


async def test_cache_avoids_repeat_requests(api, settings):
    from dataclasses import replace

    mock_exports(api)
    c = MiloAgentClient(replace(settings, cache_seconds=60))
    try:
        await c.actions()
        await c.actions()
    finally:
        await c.aclose()
    assert api.routes[2].call_count == 1  # the actions export route


def test_parse_csv_types_and_metadata():
    rows = parse_csv(fixture("opportunities_acted.csv"))
    assert rows[0]["id"] == 29217
    assert rows[0]["score"] == 10.0
    assert rows[0]["metadata"]["num_comments"] == 12
    assert rows[0]["rejection_reason"] is None
    assert rows[1]["rejection_reason"] is None  # MiloAgent writes the string None


def test_parse_rows_json_metadata():
    rows = parse_rows([{"id": 1, "metadata": "{\"subreddit\": \"x\"}"}, {"id": 2, "metadata": None}])
    assert rows[0]["metadata"] == {"subreddit": "x"}
    assert rows[1]["metadata"] == {}


def test_parse_csv_bad_metadata_is_empty():
    rows = parse_csv("id,metadata\n1,{not json\n2,[1]\n")
    assert rows[0]["metadata"] == {}
    assert rows[1]["metadata"] == {}
