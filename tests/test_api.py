"""Exercise cookie authentication against an actual local HTTP server."""

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
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
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True)
    ) as session:
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


@pytest.mark.parametrize(
    "html, expected",
    [
        (
            '<a href="/mc/123/pricing-electricity/">Prices</a>',
            "/mc/123/pricing-electricity/",
        ),
        (
            '<a href="/mc/456/pricing-electricity/">Prices</a><a href="/mc/456/pricing-electricity/">Menu</a>',
            "/mc/456/pricing-electricity/",
        ),
        ('<a href="https://example.org/mc/123/pricing-electricity/">Other</a>', None),
        ('<a href="/mc/123/pricing-gas/">Gas</a>', None),
    ],
)
def test_discover_account_from_dashboard(html, expected):
    assert api.DashboardPage(html).pricing_path == expected


@pytest.mark.asyncio
async def test_price_fetch_discovers_and_reuses_account(monkeypatch):
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import AsyncMock, Mock

    fixed = datetime(2026, 9, 27, 12, tzinfo=api.TIME_ZONE)
    monkeypatch.setattr(api, "datetime", Mock(now=Mock(return_value=fixed)))
    html = (Path(__file__).parent / "fixtures/pricing_today.html").read_text()
    client = api.ZonopnaamClient(None, "user", "secret")
    client.async_get = AsyncMock(
        side_effect=[
            '<a href="/mc/123/pricing-electricity/">Prices</a>',
            html,
            html,
        ]
    )
    data = await client.async_get_prices()
    assert len(data.intervals) == 24
    await client.async_get_prices()
    assert [call.args[0] for call in client.async_get.call_args_list] == [
        "/",
        "/mc/123/pricing-electricity/",
        "/mc/123/pricing-electricity/",
    ]


@pytest.mark.asyncio
async def test_missing_pricing_link_fails_clearly():
    from unittest.mock import AsyncMock

    client = api.ZonopnaamClient(None, "user", "secret")
    client.async_get = AsyncMock(return_value="<main>No dynamic pricing</main>")
    with pytest.raises(api.UnexpectedResponse, match="pricing link"):
        await client.async_get_prices()


@pytest.mark.asyncio
async def test_invalid_price_page_is_reported_as_unexpected():
    from unittest.mock import AsyncMock

    client = api.ZonopnaamClient(None, "user", "secret")
    client.pricing_path = "/mc/123/pricing-electricity/"
    client.async_get = AsyncMock(return_value="<main>No prices</main>")
    with pytest.raises(api.UnexpectedResponse):
        await client.async_get_prices()


@pytest.mark.asyncio
async def test_gas_discovery_and_fetch(monkeypatch):
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import AsyncMock, Mock

    fixed = datetime(2026, 9, 27, 12, tzinfo=api.TIME_ZONE)
    monkeypatch.setattr(api, "datetime", Mock(now=Mock(return_value=fixed)))
    fixtures = Path(__file__).parent / "fixtures"
    client = api.ZonopnaamClient(None, "user", "secret")
    client.pricing_path = "/mc/123/pricing-electricity/"
    electricity_html = (fixtures / "pricing_today.html").read_text()
    client.async_get = AsyncMock(
        side_effect=[
            electricity_html + '<a href="/mc/123/pricing-gas/">Gas</a>',
            (fixtures / "pricing_gas.html").read_text(),
        ]
    )
    await client.async_get_prices()
    assert client.gas_pricing_path == "/mc/123/pricing-gas/"
    gas = await client.async_get_gas_prices()
    assert gas.value("current_gas_price", fixed) == 1.6523
    assert client.async_get.call_args.args == ("/mc/123/pricing-gas/",)


@pytest.mark.asyncio
async def test_other_locations_gas_link_not_used(monkeypatch):
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import AsyncMock, Mock

    monkeypatch.setattr(
        api,
        "datetime",
        Mock(now=Mock(return_value=datetime(2026, 9, 27, tzinfo=api.TIME_ZONE))),
    )
    client = api.ZonopnaamClient(None, "user", "secret")
    client.pricing_path = "/mc/123/pricing-electricity/"
    html = (Path(__file__).parent / "fixtures/pricing_today.html").read_text()
    client.async_get = AsyncMock(
        return_value=html + '<a href="/mc/999/pricing-gas/">Other</a>'
    )
    await client.async_get_prices()
    assert client.gas_pricing_path is None
    with pytest.raises(api.UnexpectedResponse, match="Gas pricing link"):
        await client.async_get_gas_prices()
