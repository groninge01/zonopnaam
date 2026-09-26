"""Obtain Zonopnaam cookies interactively using only the Python standard library."""

import argparse
import getpass
import http.cookiejar
from html.parser import HTMLParser
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = "https://zonopnaam.app/"


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


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme, parsed.netloc) != ("https", "zonopnaam.app"):
            raise RuntimeError("Unexpected redirect outside Zonopnaam; stopped.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def login(username, password):
    jar = http.cookiejar.MozillaCookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), SameOriginRedirect()
    )
    with opener.open(URL, timeout=30) as response:
        page = LoginPage(response.read().decode("utf-8"))
    if not page.csrf or not page.password_field:
        raise RuntimeError("Expected login form was not found; the site may have changed.")
    data = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "csrfmiddlewaretoken": page.csrf,
    }).encode()
    request = urllib.request.Request(URL, data=data, headers={
        "Referer": URL,
        "Origin": URL.rstrip("/"),
    })
    with opener.open(request, timeout=30) as response:
        page = LoginPage(response.read().decode("utf-8"))
    if page.password_field:
        raise RuntimeError("Login form was returned. Check your credentials in the browser.")
    if not any(c.name == "sessionid" and not c.is_expired() for c in jar):
        raise RuntimeError("No current session cookie was received.")
    return jar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".secrets/cookies.txt"))
    args = parser.parse_args()
    username = input("Zonopnaam username: ").strip()
    password = getpass.getpass("Zonopnaam password: ")
    if not username or not password:
        parser.error("Username and password are required.")
    try:
        jar = login(username, password)
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Refuse to overwrite an existing file or follow a destination symlink.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        jar.save(str(args.output), ignore_discard=True, ignore_expires=False)
    except (OSError, urllib.error.URLError, RuntimeError) as exc:
        print(f"Login/export failed: {exc}", file=sys.stderr)
        return 1
    print(f"Login form cleared; cookies saved to {args.output} (owner access only).")
    print("Account data access still needs verification against a protected endpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
