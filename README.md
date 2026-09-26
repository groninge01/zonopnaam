# Zon op Naam for Home Assistant

A custom integration intended to replace ENTSO-e price sensors with prices from
Zon op Naam. The first implemented step is account login in Home Assistant.
**Price sensors are not implemented yet.**

## Installation and login

1. Copy `custom_components/zonopnaam` into Home Assistant's
   `/config/custom_components/zonopnaam` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Zon op Naam**.
4. Enter your Zon op Naam username and password.

The integration obtains the CSRF token, submits the login form, and retains
`csrftoken` and `sessionid` in an isolated cookie jar for each account. Credentials
are stored in Home Assistant's config entry so it can log in after a restart.
Cookies remain in memory and are never exposed as entities or logged. The client
retries a data request once after an expired login; rejected credentials during
setup trigger Home Assistant's reauthentication flow. Network failures retry setup.

Authentication checks that the login form disappears, the landing page remains
accessible, and both cookies are present. This still needs validation with a real
account; additional authentication challenges are not supported yet.

The repository has a HACS layout and `hacs.json`. Once hosted on GitHub it can be
added as a HACS custom repository of type **Integration**. Before publishing,
set the manifest's documentation URL to the repository and add its maintainer to
`codeowners`. This project has not been published or installed into your HA instance.

## Price compatibility target

Reference: [JaccoR/hass-entso-e](https://github.com/JaccoR/hass-entso-e).

Planned sensors: current and next-period electricity price, average, minimum,
maximum, relative-price percentages, and times of minimum/maximum prices.
The reference uses `prices`, `prices_today`, and `prices_tomorrow` attributes;
chart entries have `time` and `price` fields. We will preserve that format for
existing charts, with new Zon op Naam entity IDs. The reference's `next_hour_price`
key may represent the next 15-minute or 60-minute period.

Before implementing sensors, verify the authenticated Zon op Naam price endpoint,
timezone, interval duration, units, and whether taxes/supplier charges are already
included. Do not apply an existing ENTSO-e cost template without checking this.
The public demo offers a dynamic-price option and can help inspect the data format.

## Development

```sh
uv venv
uv pip install aiohttp pytest pytest-asyncio
.venv/bin/pytest -q
python3 -m compileall -q custom_components scripts
```

Client tests use a local HTTP server to verify cookies and CSRF submission,
rotation, invalid credentials, session renewal, server errors, and redirect
restrictions. Home Assistant UI/setup tests and real-account testing remain pending.

`scripts/login.py` is an optional standalone debugging helper; it is not needed
for integration setup. Its cookie exports are ignored by Git.
