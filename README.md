# Zonopnaam for Home Assistant

A HACS custom integration that provides electricity and gas prices from your Zonopnaam
account, with chart attributes compatible with
[JaccoR/hass-entso-e](https://github.com/JaccoR/hass-entso-e).

## Install through HACS

Requires **Home Assistant 2026.9.3 or newer**.

1. In HACS, open **Custom repositories** from the menu.
2. Add `https://github.com/groninge01/zonopnaam` with type **Integration**.
3. Download **Zonopnaam** and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → Zonopnaam**.
5. Enter your Zonopnaam username and password.

For manual installation, copy `custom_components/zonopnaam` into
`/config/custom_components/zonopnaam` and follow steps 3–5.

The account identifier is discovered from the dashboard's electricity pricing
link (`/mc/<identifier>/pricing-electricity/`). If you have multiple locations,
the integration uses the location selected by the website at login. Location
selection within Home Assistant is not implemented.

Credentials are stored in Home Assistant's config entry to log in after restart.
Cookies stay in a separate in-memory session for each account. Expired sessions
are renewed automatically; rejected credentials trigger reauthentication.
No separate Python installation, cookie export, or ENTSO-e API key is needed.

## Electricity prices

The integration fetches the pricing page at startup and **every two hours**.
Current and next-period sensors advance from cached data at each interval boundary,
without additional network requests. Tomorrow's prices appear when Zonopnaam
publishes them, usually in the afternoon, and are picked up on the next fetch.
Until then, `prices_tomorrow` is empty and `tomorrow_available` is false.
Missing next-period prices produce an unknown value, never a fabricated zero.

| Sensor | Value |
| --- | --- |
| Current electricity price | Price for the active interval |
| Next period electricity price | Next interval, including tomorrow when available |
| Average electricity price | Duration-weighted mean for today; includes chart attributes |
| Lowest / highest energy price | Minimum / maximum for today |
| Time of lowest / highest price | Start of today's first matching interval |
| Current percentage of highest electricity price | Current price divided by today's maximum × 100 |
| Current percentage in electricity price range | Position between today's minimum and maximum |

Price units are **EUR/kWh**. Calendar days use **Europe/Amsterdam**, including
summer/winter time. The observed demo uses hourly prices; the parser also accepts
complete quarter-hourly days. It rejects incomplete or inconsistent charts rather
than assigning prices to guessed times. Percentages with a zero denominator are
unknown; negative prices are retained.

The Zonopnaam dashboard has a setting to display different price variants. The
account used for this project currently displays **all-in prices**. The integration
reads the values and price-display label returned by the website without modifying
your account preferences or adding charges. The inspected demo page explicitly
defines all-in prices as the market price plus purchase fee and energy tax
(first band), including VAT. **Do not apply your old ENTSO-e tax/fee template again.**
Changing the dashboard setting is reflected when the server returns the new variant;
this preference change has not been tested on a real account.

Every price sensor includes `price_type` and `price_display`. The average-price
sensor additionally exposes `prices_today`, `prices_tomorrow`, `prices`, and
`tomorrow_available`. Chart arrays contain entries like:

```json
{"time": "2026-09-27T00:00:00+02:00", "price": 0.35278}
```

## Replace ENTSO-e sensors

Update dashboards and automations to use the new Zonopnaam entity IDs shown in
Home Assistant. The integration does not overwrite existing ENTSO-e entities.
For ApexCharts, change the entity to the Zonopnaam average-price sensor and keep:

```javascript
return entity.attributes.prices.map((entry) => {
  return [new Date(entry.time), entry.price];
});
```

Daily statistics use today's Amsterdam calendar day, equivalent to the reference
integration's rotation mode. Its sliding/on-publish calculation modes, other
currencies, and price-modifier templates are not implemented. Next period means
the next published interval, which can be 15 or 60 minutes.

## Validation and limitations

The parser has been checked against the public demo's actual hourly HTML and
average price. Tomorrow's electricity publication, quarter-hour data, and DST transitions are
covered by synthetic fixtures; they have not yet been observed live. Gas tariffs,
including the next gas day, have been checked against the public demo. Platform/setup tests pass against Home Assistant 2026.9.3. Real-account
login and installation in your running Home Assistant instance still need validation.
The integration depends on website HTML rather than a documented API, so a site
layout change may require an update.

## Gas prices and the Energy dashboard

Gas prices are read from `/mc/<identifier>/pricing-gas/` when the electricity page
advertises that link. **Current gas price** and **Next gas day price** use
**EUR/m³**. The website defines a gas day as **06:00–06:00 the next day**; the
integration uses Europe/Amsterdam and keeps the previous day's tariff until 06:00.
Gas is also fetched every two hours. A gas-fetch failure does not disable the
electricity sensors. Missing/unpublished gas rates are unknown, not zero.

In the Energy dashboard configuration, choose **Use an entity with the current
price** for each consumption source:

| Source | Consumption meter | Price entity |
| --- | --- | --- |
| Electricity from the grid | Your electricity import meter (kWh) | Zonopnaam **Current electricity price** (EUR/kWh) |
| Gas | Your gas consumption meter (m³) | Zonopnaam **Current gas price** (EUR/m³) |

Use the **current all-in price**, not the average or next-period sensor, to track
consumption costs. Keep your existing consumption meters; this integration only
supplies tariffs. Set Home Assistant's currency to EUR. For gas meters reporting
energy in kWh rather than volume, a supplier-specific conversion is needed before
using the EUR/m³ rate. Fixed daily/monthly charges are not included in these
per-unit sensors. The import tariff should not be used as a solar export tariff.

Home Assistant documents using current-price entities for both electricity and
gas in its [easyEnergy integration guide](https://www.home-assistant.io/integrations/easyenergy/#use-cases).
Its [Energy cost implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/components/energy/sensor.py)
multiplies consumption increments by the current per-unit price.

## Development

```sh
uv venv --python 3.14
uv pip install -r requirements-test.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests
.venv/bin/python -m compileall -q custom_components scripts
```

Tests cover authentication, cookie rotation, renewal, account discovery, price
parsing, negative prices, missing tomorrow data, interval transitions, and DST.
`scripts/login.py` is an optional debugging helper, not part of HACS setup.
