"""Cookie authentication for Zonopnaam."""

import asyncio
import re
from datetime import datetime
from html.parser import HTMLParser
from http.cookies import SimpleCookie

from aiohttp import ClientError, ClientTimeout
from yarl import URL

from .const import BASE_URL
from .gas import parse_gas_prices
from .prices import TIME_ZONE, PriceParseError, parse_prices


class CannotConnect(Exception):
    """Website unavailable."""


class InvalidAuth(Exception):
    """Login rejected or expired."""


class UnexpectedResponse(Exception):
    """Unsupported website response."""


class LoginPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.csrf = None
        self.password_field = False
        self.stay_signed_in = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            if attrs.get("name") == "csrfmiddlewaretoken":
                self.csrf = attrs.get("value")
            if attrs.get("name") == "password":
                self.password_field = True
        if (
            tag == "button"
            and attrs.get("name") == "stay_signed_in_btn"
            and attrs.get("value") == "yes"
        ):
            self.stay_signed_in = True


class DashboardPage(HTMLParser):
    """Find the selected account's electricity pricing link."""

    def __init__(self, html):
        super().__init__()
        self.pricing_path = None
        self.gas_pricing_path = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href", "")
        if (
            tag == "a"
            and self.pricing_path is None
            and re.fullmatch(r"/mc/\d+/pricing-electricity/", href)
        ):
            self.pricing_path = href
        if (
            tag == "a"
            and self.gas_pricing_path is None
            and re.fullmatch(r"/mc/\d+/pricing-gas/", href)
        ):
            self.gas_pricing_path = href


class ZonopnaamClient:
    """Manage one account's cookies in an isolated session."""

    def __init__(self, session):
        self.session = session
        self._lock = asyncio.Lock()
        self.pricing_path = None
        self.gas_pricing_path = None

    def restore_cookies(self, cookies):
        """Restore the saved Zonopnaam session without account credentials."""
        restored = SimpleCookie()
        for name, attributes in cookies.items():
            if name not in {"sessionid", "csrftoken"}:
                continue
            restored[name] = attributes.get("value", "")
            morsel = restored[name]
            for attribute in (
                "domain",
                "path",
                "secure",
                "httponly",
                "samesite",
                "expires",
                "max-age",
            ):
                if attributes.get(attribute):
                    morsel[attribute] = str(attributes[attribute])
        if restored:
            self.session.cookie_jar.update_cookies(
                restored, response_url=URL(BASE_URL)
            )

    def export_cookies(self):
        """Return only the cookies needed to resume the current session."""
        cookies = self.session.cookie_jar.filter_cookies(URL(BASE_URL))
        saved = {}
        for name in ("sessionid", "csrftoken"):
            morsel = cookies.get(name)
            if morsel is None:
                continue
            saved[name] = {
                "value": morsel.value,
                **{
                    attribute: morsel[attribute]
                    for attribute in (
                        "domain",
                        "path",
                        "secure",
                        "httponly",
                        "samesite",
                        "expires",
                        "max-age",
                    )
                    if morsel[attribute]
                },
            }
        return saved

    async def _request(self, method, path="/", data=None):
        url = URL(BASE_URL).join(URL(path))
        try:
            async with asyncio.timeout(60):
                for _ in range(6):
                    if url.origin() != URL(BASE_URL).origin():
                        raise UnexpectedResponse("Unexpected redirect origin")
                    async with self.session.request(
                        method,
                        url,
                        data=data,
                        allow_redirects=False,
                        headers={"Referer": BASE_URL, "Origin": BASE_URL.rstrip("/")},
                        timeout=ClientTimeout(total=30),
                    ) as response:
                        if response.status in (401, 403):
                            raise InvalidAuth
                        if response.status == 429 or response.status >= 500:
                            raise CannotConnect
                        if response.status in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                raise UnexpectedResponse
                            url = url.join(URL(location))
                            if response.status == 303 or (
                                response.status in (301, 302) and method == "POST"
                            ):
                                method, data = "GET", None
                            continue
                        if response.status != 200:
                            raise UnexpectedResponse
                        return await response.text()
                raise UnexpectedResponse("Too many redirects")
        except (ClientError, TimeoutError) as err:
            raise CannotConnect from err

    async def _login(self, username, password):
        self.session.cookie_jar.clear()
        page = LoginPage(await self._request("GET"))
        if not page.csrf or not page.password_field:
            raise UnexpectedResponse("Login form not found")
        form_data = {
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": page.csrf,
        }
        page = LoginPage(
            await self._request(
                "POST",
                data=form_data,
            )
        )
        if page.password_field:
            raise InvalidAuth
        # The site asks this after credentials, and can hide the question when
        # a previous choice was saved. Explicitly request a persistent session.
        stay_path = "/login/stay-signed-in/"
        if not page.stay_signed_in:
            page = LoginPage(await self._request("GET", stay_path))
        if page.password_field:
            raise InvalidAuth
        if not page.stay_signed_in or not page.csrf:
            raise UnexpectedResponse("Stay-signed-in form not found")
        page = LoginPage(
            await self._request(
                "POST",
                stay_path,
                data={
                    "csrfmiddlewaretoken": page.csrf,
                    "stay_signed_in_btn": "yes",
                    "ask_stay_signed_in": "on",
                },
            )
        )
        if page.password_field:
            raise InvalidAuth
        if page.stay_signed_in:
            raise UnexpectedResponse("Stay-signed-in choice was not accepted")
        page = LoginPage(await self._request("GET"))
        if page.password_field:
            raise InvalidAuth
        if page.stay_signed_in:
            raise UnexpectedResponse("Stay-signed-in choice was not accepted")
        cookies = self.session.cookie_jar.filter_cookies(URL(BASE_URL))
        if not cookies.get("sessionid") or not cookies.get("csrftoken"):
            raise UnexpectedResponse("Expected cookies missing")

    async def async_login(self, username, password):
        async with self._lock:
            await self._login(username, password)

    async def async_get(self, path):
        """Fetch a page using the saved session."""
        async with self._lock:
            html = await self._request("GET", path)
            if LoginPage(html).password_field:
                raise InvalidAuth
            return html

    async def async_get_prices(self):
        """Discover the active account and read its published price charts."""
        if self.pricing_path is None:
            dashboard = DashboardPage(await self.async_get("/"))
            if not dashboard.pricing_path:
                raise UnexpectedResponse(
                    "Electricity pricing link not found on dashboard"
                )
            self.pricing_path = dashboard.pricing_path
        for _ in range(2):
            today = datetime.now(TIME_ZONE).date()
            html = await self.async_get(self.pricing_path)
            if datetime.now(TIME_ZONE).date() != today:
                continue  # Refetch if the request crossed local midnight.
            try:
                prices = parse_prices(html, today)
                gas_path = DashboardPage(html).gas_pricing_path
                # Only use the gas link belonging to the same selected location.
                expected = self.pricing_path.replace(
                    "pricing-electricity/", "pricing-gas/"
                )
                self.gas_pricing_path = gas_path if gas_path == expected else None
                return prices
            except PriceParseError as err:
                raise UnexpectedResponse(str(err)) from err
        raise UnexpectedResponse("Price request crossed midnight")

    async def async_get_gas_prices(self):
        """Read gas tariffs only from an advertised pricing link."""
        if not self.gas_pricing_path:
            raise UnexpectedResponse("Gas pricing link not found")
        html = await self.async_get(self.gas_pricing_path)
        try:
            return parse_gas_prices(html)
        except PriceParseError as err:
            raise UnexpectedResponse(str(err)) from err
