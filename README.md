# Zonopnaam for Home Assistant

See your Zonopnaam electricity and gas prices in Home Assistant. Use the prices
in dashboards, automations, or the Home Assistant Energy dashboard.

## Install

Requires **Home Assistant 2026.9.3 or newer** and a Zonopnaam account.

1. In HACS, open **Custom repositories** from the menu.
2. Add `https://github.com/groninge01/zonopnaam` and select **Integration**.
3. Find and download **Zonopnaam** in HACS, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and choose **Zonopnaam**.
5. Sign in with your Zonopnaam username and password. The integration automatically
   answers **Ja** to the website's **Aangemeld blijven?** question after login
   and checks **Vraag me dit niet opnieuw**.

The integration uses the location selected in your Zonopnaam account. If you
have more than one location, select the one you want on the Zonopnaam website.
Your username and password are used only to sign in and are not saved. Home
Assistant saves the active session cookie so the integration can reconnect after
a restart. If the session expires, you will be asked to sign in again.

## What you get

The integration checks for updated prices every two hours. It adds sensors for:

- Current and next electricity prices
- Today's average, lowest, and highest electricity prices
- When today's lowest and highest prices occur
- Current and next gas prices, when your account provides gas prices

Electricity prices are shown in **EUR/kWh** and gas prices in **EUR/m³**. Prices
follow the price option selected in your Zonopnaam account. Home Assistant also
shows which price option is being used.

## Energy dashboard

To see estimated costs in the Energy dashboard, choose **Use an entity with the
current price** and select:

| Energy source | Price sensor |
| --- | --- |
| Electricity from the grid | Zonopnaam **Current electricity price** |
| Gas | Zonopnaam **Current gas price** |

You still need your own electricity and gas consumption sensors. Prices are per
unit and do not include fixed daily or monthly charges.

## Development

Install [uv](https://docs.astral.sh/uv/), then run:

```sh
uv venv --python 3.14
uv pip install --python .venv/bin/python -r requirements-test.txt
uv run --python .venv/bin/python pytest -q
uv run --python .venv/bin/python ruff check custom_components tests
uv run --python .venv/bin/python -m compileall -q custom_components scripts
```
