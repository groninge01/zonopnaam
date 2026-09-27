"""Price parsing and calculations, including unpublished days and DST."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from zonopnaam_test.prices import TIME_ZONE, PriceParseError, parse_prices

FIXTURE = Path(__file__).parent / "fixtures/pricing_today.html"


def chart(target, day="today", minutes=60, price_fn=lambda i: i / 100):
    start = datetime.combine(target, time(), TIME_ZONE).astimezone(UTC)
    end = datetime.combine(target + timedelta(days=1), time(), TIME_ZONE).astimezone(
        UTC
    )
    rows = []
    i = 0
    while start < end:
        after = start + timedelta(minutes=minutes)
        rows.append(
            f'<rect data-hour="{start.astimezone(TIME_ZONE):%H:%M}" '
            f'data-hour-end="{after.astimezone(TIME_ZONE):%H:%M}" '
            f'data-price="{price_fn(i):.5f}"></rect>'
        )
        start = after
        i += 1
    return f'<div data-chart-day="{day}"><svg>{"".join(rows)}</svg></div>'


def page(charts, label="all-in-prijs"):
    return f'<div class="pricing-info">Prijsweergave: {label}</div>€/kWh{charts}'


def test_observed_demo_markup():
    data = parse_prices(FIXTURE.read_text(), date(2026, 9, 27))
    now = datetime(2026, 9, 27, 0, tzinfo=TIME_ZONE)
    assert len(data.intervals) == 24
    assert data.value("current_price", now) == 0.35278
    assert data.value("next_hour_price", now) == 0.34656
    assert round(data.value("avg_price", now), 5) == 0.27214
    attrs = data.attributes(now)
    assert attrs["price_type"] == "all_in"
    assert attrs["prices_today"][0] == {
        "time": "2026-09-27T00:00:00+02:00",
        "price": 0.35278,
    }
    assert attrs["prices_tomorrow"] == []
    assert not attrs["tomorrow_available"]
    assert len(attrs["prices"]) == 24


@pytest.mark.parametrize(
    "target,hours",
    [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25), (date(2026, 9, 27), 24)],
)
@pytest.mark.parametrize("minutes", [15, 60])
def test_full_days_across_dst(target, hours, minutes):
    data = parse_prices(page(chart(target, minutes=minutes)), target)
    assert len(data.intervals) == hours * 60 // minutes
    assert all(p.end - p.start == timedelta(minutes=minutes) for p in data.intervals)
    assert len({p.chart_value()["time"] for p in data.intervals}) == len(data.intervals)
    for p in data.intervals:
        assert data.value("current_price", p.start) == p.price


def test_tomorrow_arrives_and_rolls_over_without_network():
    today = date(2026, 9, 27)
    html = page(chart(today) + chart(today + timedelta(days=1), "tomorrow"))
    data = parse_prices(html, today)
    late = datetime(2026, 9, 27, 23, 45, tzinfo=TIME_ZONE)
    assert data.value("current_price", late) == 0.23
    assert data.value("next_hour_price", late) == 0
    assert data.attributes(late)["tomorrow_available"]
    midnight = datetime(2026, 9, 28, tzinfo=TIME_ZONE)
    assert data.value("current_price", midnight) == 0
    assert len(data.attributes(midnight)["prices_today"]) == 24
    assert data.attributes(midnight)["prices_tomorrow"] == []


def test_missing_tomorrow_never_reuses_today():
    data = parse_prices(page(chart(date(2026, 9, 27))), date(2026, 9, 27))
    assert (
        data.value("next_hour_price", datetime(2026, 9, 27, 23, tzinfo=TIME_ZONE))
        is None
    )
    tomorrow = datetime(2026, 9, 28, tzinfo=TIME_ZONE)
    assert data.value("current_price", tomorrow) is None
    assert data.value("avg_price", tomorrow) is None
    assert data.attributes(tomorrow)["prices"] == []


def test_negative_prices_and_summary():
    data = parse_prices(
        page(chart(date(2026, 9, 27), price_fn=lambda i: (i - 12) / 100)),
        date(2026, 9, 27),
    )
    now = datetime(2026, 9, 27, 6, tzinfo=TIME_ZONE)
    assert data.value("min_price", now) == -0.12
    assert data.value("max_price", now) == 0.11
    assert data.value("avg_price", now) == pytest.approx(-0.005)
    assert data.value("percentage_of_range", now) == pytest.approx(0.06 / 0.23 * 100)
    assert data.value("lowest_price_time_today", now).astimezone(TIME_ZONE).hour == 0
    assert data.value("highest_price_time_today", now).astimezone(TIME_ZONE).hour == 23


def test_zero_denominators_are_unknown():
    data = parse_prices(
        page(chart(date(2026, 9, 27), price_fn=lambda i: 0)), date(2026, 9, 27)
    )
    now = datetime(2026, 9, 27, tzinfo=TIME_ZONE)
    assert data.value("current_price", now) == 0
    assert data.value("percentage_of_max", now) is None
    assert data.value("percentage_of_range", now) is None


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace('data-hour="01:00"', 'data-hour="02:00"'),
        lambda s: s.replace('data-price="0,35278"', 'data-price="NaN"'),
        lambda s: s.replace("€/kWh", "€/MWh"),
        lambda s: s.replace("pricing-info", "other"),
        lambda s: s.replace("26 september 2026", "25 september 2026"),
        lambda s: s.replace('data-chart-day="today"', 'data-chart-day="unknown"'),
    ],
)
def test_invalid_pages_are_rejected(change):
    with pytest.raises(PriceParseError):
        parse_prices(change(FIXTURE.read_text()), date(2026, 9, 27))


def test_incomplete_day_rejected():
    import re

    html = re.sub(r"<rect\b[^>]*></rect>", "", FIXTURE.read_text(), count=1)
    with pytest.raises(PriceParseError):
        parse_prices(html, date(2026, 9, 27))


def test_other_price_selection_preserved_without_extra_charges():
    data = parse_prices(
        page(chart(date(2026, 9, 27)), label="kale inkoopprijs"), date(2026, 9, 27)
    )
    assert data.price_type == "dashboard_selection"
    assert data.price_label == "kale inkoopprijs"
    assert data.intervals[1].price == 0.01
