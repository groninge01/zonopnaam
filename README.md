# Zon op Naam Home Assistant integration

Work in progress: authentication exploration. This is not yet an installable HACS integration.

## Obtain cookies

Run locally with Python 3 (no dependencies):

```sh
python3 scripts/login.py
```

Enter your Zon op Naam username and password at the prompts. The password is
hidden and is not saved. Cookies are saved in Netscape cookie-jar format to
`.secrets/cookies.txt`, excluded from Git, with owner-only permissions. Existing
files are not overwritten; use `--output .secrets/cookies-new.txt` for another run.
Treat this file as a credential and do not share or commit it.

The public [login page](https://zonopnaam.app/) was inspected on 2026-09-26:

- GET `/` sets `csrftoken` and an anonymous `sessionid`.
- POST `/` submits `username`, `password`, and the hidden `csrfmiddlewaretoken`,
  retaining the cookies and sending the same-origin Referer.
- Keep the cookies received after login: authentication may rotate them.
- Both cookies are HttpOnly; browser JavaScript cannot read them.

`sessionid` identifies the session; `csrftoken` supports CSRF checks on modifying
requests and is not itself proof of authentication. The observed anonymous
session cookie had a one-day lifetime; authenticated session expiry is unverified.

The helper checks that the password form disappears and a current session cookie
exists. Successful account login and access to a protected data endpoint still
need to be verified with a real account. Additional authentication steps, if any,
are not implemented.

Alternatively, log in in your browser, open Developer Tools → Application
(Chrome/Edge) or Storage (Firefox) → Cookies → `https://zonopnaam.app`, and inspect
`csrftoken` and `sessionid` there.

Next: identify the authenticated energy-data endpoints, then implement an async
client and Home Assistant config flow with session renewal.
# zonopnaam
# zonopnaam
# zonopnaam
