"""Exercise cookie authentication against an actual local HTTP server."""
import importlib.util
from pathlib import Path
import sys
import types

import aiohttp
from aiohttp import web
import pytest
import pytest_asyncio

# Load the standalone client without importing the Home Assistant entry point.
package = types.ModuleType("zonopnaam_test")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/zonopnaam")]
sys.modules[package.__name__] = package
from zonopnaam_test import api

FORM = '<input name="csrfmiddlewaretoken" value="form-token"><input name="password">'


@pytest_asyncio.fixture
async def site(monkeypatch):
    state = {"posts": 0, "expired": False, "reject": False, "status": 200}

    async def root(request):
        if state["status"] != 200:
            return web.Response(status=state["status"])
        if request.method == "POST":
            state["posts"] += 1
            data = await request.post()
            assert data["csrfmiddlewaretoken"] == "form-token"
            assert data["username"] == "user"
            assert data["password"] == "secret"
            assert request.cookies["csrftoken"] == "initial"
            assert request.headers["Referer"] == api.BASE_URL
            assert request.headers["Origin"] == api.BASE_URL.rstrip("/")
            if state["reject"]:
                return web.Response(text=FORM)
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie("sessionid", "authenticated")
            response.set_cookie("csrftoken", "rotated")
            state["expired"] = False
            return response
        if request.cookies.get("sessionid") == "authenticated" and not state["expired"]:
            return web.Response(text="<main>Account</main>")
        response = web.Response(text=FORM)
        response.set_cookie("csrftoken", "initial")
        response.set_cookie("sessionid", "anonymous")
        return response

    async def redirect(request):
        return web.Response(status=302, headers={"Location": "https://example.org/"})

    app = web.Application()
    app.router.add_route("*", "/", root)
    app.router.add_get("/redirect", redirect)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(api, "BASE_URL", f"http://127.0.0.1:{port}/")
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        yield api.ZonopnaamClient(session, "user", "secret"), state
    await runner.cleanup()


@pytest.mark.asyncio
async def test_login_retains_rotated_cookies(site):
    client, state = site
    await client.async_login()
    cookies = client.session.cookie_jar.filter_cookies(api.URL(api.BASE_URL))
    assert cookies["sessionid"].value == "authenticated"
    assert cookies["csrftoken"].value == "rotated"
    assert state["posts"] == 1


@pytest.mark.asyncio
async def test_anonymous_cookie_is_not_success(site):
    client, state = site
    state["reject"] = True
    with pytest.raises(api.InvalidAuth):
        await client.async_login()


@pytest.mark.asyncio
async def test_expired_session_renews_once(site):
    client, state = site
    await client.async_login()
    state["expired"] = True
    assert "Account" in await client.async_get("/")
    assert state["posts"] == 2


@pytest.mark.asyncio
async def test_rejected_renewal_does_not_loop(site):
    client, state = site
    await client.async_login()
    state.update(expired=True, reject=True)
    with pytest.raises(api.InvalidAuth):
        await client.async_get("/")
    assert state["posts"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_server_errors(site, status):
    client, state = site
    state["status"] = status
    with pytest.raises(api.CannotConnect):
        await client.async_login()


@pytest.mark.asyncio
async def test_external_redirect_rejected(site):
    client, _ = site
    with pytest.raises(api.UnexpectedResponse):
        await client.async_get("/redirect")
