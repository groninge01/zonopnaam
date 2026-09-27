"""Parse the website's price charts and calculate local-day sensor values."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TIME_ZONE = ZoneInfo("Europe/Amsterdam")
MONTHS = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


class PriceParseError(ValueError):
    """Price markup is missing, ambiguous, or inconsistent."""


class PricingPage(HTMLParser):
    """Extract only chart values, their date labels, and the price display label."""

    def __init__(self, html: str):
        super().__init__()
        self.rows = {}
        self.titles = {}
        self.price_label = ""
        self.text = []
        self._stack = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        # Only track containers relevant to the chart and its headings.
        if tag in {"div", "section", "h1", "h2", "svg"}:
            self._stack.append((tag, attrs))
        if "data-chart-day" in attrs:
            day = attrs["data-chart-day"]
            if day not in {"yesterday", "today", "tomorrow"}:
                raise PriceParseError("Unknown chart day")
            if day in self.rows:
                raise PriceParseError("Duplicate price chart")
            self.rows[day] = []
        if tag == "rect" and "data-price" in attrs:
            day = next(
                (
                    a["data-chart-day"]
                    for _, a in reversed(self._stack)
                    if "data-chart-day" in a
                ),
                None,
            )
            if day is None:
                raise PriceParseError("Price outside a dated chart")
            try:
                self.rows[day].append(
                    (attrs["data-hour"], attrs["data-hour-end"], attrs["data-price"])
                )
            except KeyError as err:
                raise PriceParseError("Price interval has no time labels") from err

    def handle_endtag(self, tag):
        if tag in {"div", "section", "h1", "h2", "svg"}:
            for index in range(len(self._stack) - 1, -1, -1):
                if self._stack[index][0] == tag:
                    del self._stack[index:]
                    break

    def handle_data(self, text):
        self.text.append(text)
        for _, attrs in self._stack:
            if "pricing-info" in attrs.get("class", "").split():
                self.price_label += text
            if "data-title-day" in attrs:
                day = attrs["data-title-day"]
                self.titles[day] = self.titles.get(day, "") + text


@dataclass(frozen=True)
class PriceInterval:
    """An interval represented in UTC, including repeated DST hours."""

    start: datetime
    end: datetime
    price: float

    def chart_value(self):
        return {
            "time": self.start.astimezone(TIME_ZONE).isoformat(),
            "price": self.price,
        }


@dataclass(frozen=True)
class PriceData:
    intervals: tuple[PriceInterval, ...]
    price_label: str

    @property
    def price_type(self):
        return (
            "all_in"
            if "all-in" in self.price_label.casefold()
            else "dashboard_selection"
        )

    def day(self, target: date):
        return tuple(
            p for p in self.intervals if p.start.astimezone(TIME_ZONE).date() == target
        )

    def current(self, now: datetime):
        now = now.astimezone(UTC)
        return next((p for p in self.intervals if p.start <= now < p.end), None)

    def value(self, key: str, now: datetime):
        today = self.day(now.astimezone(TIME_ZONE).date())
        current = self.current(now)
        if key == "current_price":
            return current.price if current else None
        if key == "next_hour_price":
            return next(
                (p.price for p in self.intervals if current and p.start == current.end),
                None,
            )
        if not today:
            return None
        low = min(today, key=lambda p: p.price)
        high = max(today, key=lambda p: p.price)
        if key == "min_price":
            return low.price
        if key == "max_price":
            return high.price
        if key == "avg_price":
            seconds = sum((p.end - p.start).total_seconds() for p in today)
            return (
                sum(p.price * (p.end - p.start).total_seconds() for p in today)
                / seconds
            )
        if key == "lowest_price_time_today":
            return low.start
        if key == "highest_price_time_today":
            return high.start
        if key == "percentage_of_max":
            return (
                current.price / high.price * 100
                if current and high.price != 0
                else None
            )
        if key == "percentage_of_range":
            return (
                (current.price - low.price) / (high.price - low.price) * 100
                if current and high.price != low.price
                else None
            )
        raise ValueError(f"Unknown sensor key: {key}")

    def attributes(self, now: datetime):
        today = now.astimezone(TIME_ZONE).date()
        today_rows = self.day(today)
        tomorrow_rows = self.day(today + timedelta(days=1))
        return {
            "prices_today": [p.chart_value() for p in today_rows],
            "prices_tomorrow": [p.chart_value() for p in tomorrow_rows],
            "prices": [p.chart_value() for p in (*today_rows, *tomorrow_rows)],
            "tomorrow_available": bool(tomorrow_rows),
            "price_type": self.price_type,
            "price_display": self.price_label,
        }


def parse_prices(html: str, reference_date: date) -> PriceData:
    """Read complete local days, rejecting gaps and unsafe DST assumptions."""
    page = PricingPage(html)
    if "€/kWh" not in "".join(page.text):
        raise PriceParseError("Expected prices in EUR/kWh")
    label = (
        " ".join(page.price_label.split()).removeprefix("Prijsweergave:").strip(" *")
    )
    if not label:
        raise PriceParseError("Price display label is missing")
    if not page.rows.get("today"):
        raise PriceParseError("Today's prices are missing")
    # The observed yesterday heading contains an explicit Dutch calendar date.
    # Check it to prevent assigning stale responses to the wrong date.
    for day, offset in (("yesterday", -1), ("today", 0), ("tomorrow", 1)):
        title = page.titles.get(day, "").casefold()
        match = re.search(
            r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", title
        )
        if match:
            try:
                actual = date(int(match[3]), MONTHS.index(match[2]) + 1, int(match[1]))
            except ValueError as err:
                raise PriceParseError("Invalid price date") from err
            if actual != reference_date + timedelta(days=offset):
                raise PriceParseError("Price page dates do not match the current day")
    intervals = []
    for day, offset in (("today", 0), ("tomorrow", 1)):
        rows = page.rows.get(day, [])
        if not rows:
            continue  # Tomorrow may not have been published yet.
        target = reference_date + timedelta(days=offset)
        start = datetime.combine(target, time(), TIME_ZONE).astimezone(UTC)
        end = datetime.combine(
            target + timedelta(days=1), time(), TIME_ZONE
        ).astimezone(UTC)
        step_seconds = (end - start).total_seconds() / len(rows)
        if step_seconds not in (900, 3600):
            raise PriceParseError("Incomplete day or unsupported price interval")
        step = timedelta(seconds=step_seconds)
        for hour, hour_end, raw_price in rows:
            next_start = start + step
            if hour != start.astimezone(TIME_ZONE).strftime(
                "%H:%M"
            ) or hour_end != next_start.astimezone(TIME_ZONE).strftime("%H:%M"):
                raise PriceParseError(
                    "Price times are not a complete chronological day"
                )
            try:
                price = Decimal(raw_price.strip().replace(",", "."))
                if not price.is_finite() or not float("-inf") < float(price) < float(
                    "inf"
                ):
                    raise InvalidOperation
            except (InvalidOperation, ValueError, OverflowError) as err:
                raise PriceParseError("Invalid price value") from err
            intervals.append(PriceInterval(start, next_start, float(price)))
            start = next_start
    return PriceData(tuple(intervals), label)
