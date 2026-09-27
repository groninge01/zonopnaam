"""Gas tariffs follow the website's explicit dates and 06:00 boundaries."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from zonopnaam_test.gas import parse_gas_prices
from zonopnaam_test.prices import TIME_ZONE, PriceParseError

FIXTURE = Path(__file__).parent / "fixtures/pricing_gas.html"


def test_live_demo_gas_table():
    data = parse_gas_prices(FIXTURE.read_text())
    now = datetime(2026, 9, 27, 12, tzinfo=TIME_ZONE)
    assert data.value("current_gas_price", now) == 1.6523
    assert data.value("next_gas_price", now) == 1.6524
    attrs = data.attributes(now)
    assert attrs["price_type"] == "all_in"
    assert attrs["valid_from"] == "2026-09-27T06:00:00+02:00"
    assert attrs["valid_until"] == "2026-09-28T06:00:00+02:00"


def test_price_changes_at_six_not_midnight():
    data = parse_gas_prices(FIXTURE.read_text())
    assert (
        data.value("current_gas_price", datetime(2026, 9, 26, 0, tzinfo=TIME_ZONE))
        == 1.7054
    )
    assert (
        data.value(
            "current_gas_price", datetime(2026, 9, 26, 5, 59, 59, tzinfo=TIME_ZONE)
        )
        == 1.7054
    )
    assert (
        data.value("current_gas_price", datetime(2026, 9, 26, 6, tzinfo=TIME_ZONE))
        == 1.6523
    )


def test_missing_gas_future_not_fabricated():
    data = parse_gas_prices(FIXTURE.read_text())
    assert (
        data.value("next_gas_price", datetime(2026, 9, 28, 6, tzinfo=TIME_ZONE)) is None
    )
    assert (
        data.value("current_gas_price", datetime(2026, 9, 29, 6, tzinfo=TIME_ZONE))
        is None
    )


@pytest.mark.parametrize("day,hours", [("28 maart 2026", 23), ("24 oktober 2026", 25)])
def test_gas_dst_day(day, hours):
    html = f"""<div class="pricing-info">Prijsweergave: all-in-prijs</div>
    <table class="pricing-table"><tr><td class="column-date">{day}</td>
    <td class="column-tariff">1,5</td></tr></table>
    €/m<sup>3</sup> Een gasdag begint om 06:00 uur."""
    data = parse_gas_prices(html)
    assert data.intervals[0].end - data.intervals[0].start == timedelta(hours=hours)


@pytest.mark.parametrize(
    "old,new",
    [
        ("1,6524", "NaN"),
        ("28 september 2026", "28 unknown 2026"),
        ("&euro;/m<sup>3</sup>", "EUR/kWh"),
        ("begint om 06:00", "begint om 07:00"),
        ("28 september 2026", "27 september 2026"),
    ],
)
def test_reject_bad_gas_data(old, new):
    with pytest.raises(PriceParseError):
        parse_gas_prices(FIXTURE.read_text().replace(old, new))
