"""Cookie authentication for Zon op Naam."""
import asyncio
from html.parser import HTMLParser
from aiohttp import ClientError, ClientTimeout
from yarl import URL
from .const import BASE_URL


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
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            if attrs.get("name") == "csrfmiddlewaretoken":
                self.csrf = attrs.get("value")
            if attrs.get("name") == "password":
                self.password_field = True


class ZonopnaamClient:
    """Manage one account's cookies in an isolated session."""
    def __init__(self, session, username, password):
        self.session = session
        self._username = username
        self._password = password
        self._lock = asyncio.Lock()

    async def _request(self, method, path="/", data=None):
        url = URL(BASE_URL).join(URL(path))
        try:
            async with asyncio.timeout(60):
                for _ in range(6):
                    if url.origin() != URL(BASE_URL).origin():
                        raise UnexpectedResponse("Unexpected redirect origin")
                    async with self.session.request(
                        method, url, data=data, allow_redirects=False,
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

    async def _login(self):
        self.session.cookie_jar.clear()
        page = LoginPage(await self._request("GET"))
        if not page.csrf or not page.password_field:
            raise UnexpectedResponse("Login form not found")
        page = LoginPage(await self._request("POST", data={
            "username": self._username, "password": self._password,
            "csrfmiddlewaretoken": page.csrf,
        }))
        if page.password_field:
            raise InvalidAuth
        page = LoginPage(await self._request("GET"))
        if page.password_field:
            raise InvalidAuth
        cookies = self.session.cookie_jar.filter_cookies(URL(BASE_URL))
        if not cookies.get("sessionid") or not cookies.get("csrftoken"):
            raise UnexpectedResponse("Expected cookies missing")

    async def async_login(self):
        async with self._lock:
            await self._login()

    async def async_get(self, path):
        """Fetch a page, renewing an expired login once."""
        async with self._lock:
            try:
                html = await self._request("GET", path)
                if LoginPage(html).password_field:
                    raise InvalidAuth
            except InvalidAuth:
                await self._login()
                html = await self._request("GET", path)
                if LoginPage(html).password_field:
                    raise InvalidAuth
            return html
