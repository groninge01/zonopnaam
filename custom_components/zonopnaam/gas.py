"""Read daily gas tariffs with the website's 06:00 gas-day boundary."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from .prices import (
    MONTHS,
    TIME_ZONE,
    PriceData,
    PriceInterval,
    PriceParseError,
    PricingPage,
)


class GasTable(HTMLParser):
    """Collect only dated rows inside the gas pricing table."""

    def __init__(self, html):
        super().__init__()
        self.rows = []
        self._in_table = False
        self._row = None
        self._cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "pricing-table" in attrs.get("class", "").split():
            self._in_table = True
        if self._in_table and tag == "tr":
            self._row = {}
        if self._row is not None and tag == "td":
            classes = attrs.get("class", "").split()
            self._cell = next(
                (c for c in classes if c in {"column-date", "column-tariff"}), None
            )
            if self._cell:
                self._row[self._cell] = ""

    def handle_data(self, text):
        if self._row is not None and self._cell:
            self._row[self._cell] += text

    def handle_endtag(self, tag):
        if tag == "td":
            self._cell = None
        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        if tag == "table":
            self._in_table = False


@dataclass(frozen=True)
class GasPriceData(PriceData):
    """Gas values are daily tariffs, not electricity calendar-day statistics."""

    def value(self, key, now):
        current = self.current(now)
        if key == "current_gas_price":
            return current.price if current else None
        if key == "next_gas_price":
            return next(
                (p.price for p in self.intervals if current and p.start == current.end),
                None,
            )
        raise ValueError(f"Unknown gas sensor key: {key}")

    def attributes(self, now):
        current = self.current(now)
        return {
            "price_type": self.price_type,
            "price_display": self.price_label,
            "valid_from": current.start.astimezone(TIME_ZONE).isoformat()
            if current
            else None,
            "valid_until": current.end.astimezone(TIME_ZONE).isoformat()
            if current
            else None,
            "prices": [
                dict(p.chart_value(), end=p.end.astimezone(TIME_ZONE).isoformat())
                for p in self.intervals
            ],
        }


def parse_gas_prices(html):
    """Parse the explicit gas dates and unit; do not infer a rate from row order."""
    page = PricingPage(html)
    text = "".join(page.text)
    if not re.search(r"€/m(?:3|³)", text):
        raise PriceParseError("Expected gas prices in EUR/m³")
    if not re.search(r"begint om\s+06:00\s+uur", text):
        raise PriceParseError("Gas-day boundary is missing or changed")
    label = (
        " ".join(page.price_label.split()).removeprefix("Prijsweergave:").strip(" *")
    )
    if not label:
        raise PriceParseError("Gas price display label is missing")
    rows = GasTable(html).rows
    if not rows:
        raise PriceParseError("Gas price table is missing")
    intervals = {}
    for row in rows:
        try:
            day, month, year = row["column-date"].strip().casefold().split()
            start = datetime(
                int(year), MONTHS.index(month) + 1, int(day), 6, tzinfo=TIME_ZONE
            )
            end = datetime.combine(start.date() + timedelta(days=1), time(6), TIME_ZONE)
            price = Decimal(row["column-tariff"].strip().replace(",", "."))
            if not price.is_finite() or not float("-inf") < float(price) < float("inf"):
                raise InvalidOperation
        except (KeyError, ValueError, InvalidOperation, OverflowError) as err:
            raise PriceParseError("Invalid gas tariff row") from err
        if start in intervals:
            raise PriceParseError("Duplicate gas date")
        intervals[start] = PriceInterval(
            start.astimezone(UTC), end.astimezone(UTC), float(price)
        )
    return GasPriceData(tuple(intervals[k] for k in sorted(intervals)), label)
