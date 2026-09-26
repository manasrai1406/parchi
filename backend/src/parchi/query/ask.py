"""Plain-English questions, read by rules into the Query page's filters (D-037).

Nothing here calls an AI provider. The question only ever becomes filter values; the SQL
is built from those, never from the question's text.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from parchi.schemas.api import ReceiptQuery, Understood
from parchi.validation.rules import financial_year_start

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4,
    "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11,
    "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip
MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
DAY = r"\d{1,2}(?:st|nd|rd|th)?"
YEAR = r"(?:19|20)\d{2}"
# 2026-08-01, 1/8/2026, 1 Aug, 1 Aug 2026, Aug 1, Aug 1, 2026
DATE = (
    rf"(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}"
    rf"|{DAY}\s+(?:of\s+)?{MONTH}(?:,?\s+{YEAR})?|{MONTH}\s+{DAY}(?:,?\s+{YEAR})?)"
)
AMOUNT = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k|lakhs?|lacs?)?(?:\s*(?:rupees|rs|inr))?"

# Words for the built-in categories (D-009), beyond their names.
SYNONYMS = {
    "fuel": ("petrol", "diesel", "cng", "fuel station", "petrol pump"),
    "travel": ("taxi", "cab", "cabs", "flight", "flights", "train", "hotel", "hotels", "uber"),
    "food": ("restaurant", "restaurants", "meal", "meals", "lunch", "dinner", "snacks"),
    "office": ("stationery", "office supplies"),
    "utilities": ("electricity", "internet", "broadband", "water bill", "phone bill"),
    "maintenance": ("repair", "repairs"),
}

# Words that carry no filter. Anything else that is left over is reported back.
FILLER = set(
    """
    a all an and any are at by did do does expense expenses find for from get give how i
    in is list me much many my of on our paid pay payments please purchases receipt
    receipts bill bills show spend spending spent sum that the there to total totals was
    we were what which with amount amounts cost costs value rupees rs inr ₹ average
    what's whats during between order sorted sort first only
    """.split()
)

EXAMPLES = (
    "fuel in August",
    "food over ₹500 last month",
    "top 5 receipts this financial year",
)


class NotUnderstood(ValueError):
    """The question has nothing the reader can turn into a filter."""


@dataclass
class Reading:
    query: ReceiptQuery
    understood: list[Understood]
    ignored: list[str]


@dataclass
class _State:
    today: date
    period: tuple[date | None, date | None, str] | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    vendor: str | None = None
    category: tuple[int, str] | None = None
    sort: str = "date"
    limit: int | None = None
    notes: list[str] = field(default_factory=list)

    def set_period(self, start: date | None, end: date | None, label: str) -> None:
        if self.period is not None:
            raise NotUnderstood("Ask about one period at a time.")
        self.period = (start, end, label)


# --- small helpers ---------------------------------------------------------------------


def label(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def span(start: date, end: date) -> str:
    return f"{label(start)} to {label(end)}"


def month_end(year: int, month: int) -> date:
    following = date(year + (month == 12), month % 12 + 1, 1)
    return following - timedelta(days=1)


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, month_end(year, month + 1).day))


def rupees(amount: Decimal) -> str:
    """₹1,23,456.50, with Indian digit grouping."""
    whole, _, cents = f"{amount:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{sign}₹{digits}.{cents}"


def parse_amount(number: str, unit: str | None) -> Decimal:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation as exc:
        raise NotUnderstood(f'"{number}" is not an amount.') from exc
    if unit == "k":
        value *= 1_000
    elif unit:
        value *= 100_000  # lakh
    return value


def latest(month: int, day: int, today: date) -> date:
    """A day with no year: this year's, or last year's if that has not come yet."""
    year = today.year if (month, day) <= (today.month, today.day) else today.year - 1
    return date(year, month, day)


def has_year(text: str) -> bool:
    return re.search(rf"\b{YEAR}\b|\d[/.-]\d{{1,2}}[/.-]\d{{2}}", text) is not None


def parse_date(text: str, today: date) -> date:
    """One date as written. With no year, the latest one that has come."""
    text = text.strip().rstrip(".")
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", text):
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(year, int(m[2]), int(m[1]))  # Indian order: day first
        m = re.fullmatch(rf"({DAY})\s+(?:of\s+)?({MONTH})(?:,?\s+({YEAR}))?", text)
        if m:
            day, month, year = int(m[1].rstrip("stndrh")), MONTHS[m[2].rstrip(".")], m[3]
        else:
            m = re.fullmatch(rf"({MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+({YEAR}))?", text)
            if not m:
                raise NotUnderstood(f'"{text}" is not a date.')
            day, month, year = int(m[2]), MONTHS[m[1].rstrip(".")], m[3]
        if year:
            return date(int(year), month, day)
        return latest(month, day, today)
    except ValueError as exc:
        if isinstance(exc, NotUnderstood):
            raise
        raise NotUnderstood(f'"{text}" is not a real date.') from exc


# --- the rules, applied in order; each consumes what it reads ---------------------------

Rule = tuple[str, Callable[[re.Match[str], _State], None]]


def _range(m: re.Match[str], s: _State) -> None:
    start, end = parse_date(m["a"], s.today), parse_date(m["b"], s.today)
    if start > end:  # "1 Sep to 30 Aug": the start is in the year before
        if not has_year(m["a"]):
            start = start.replace(year=start.year - 1)
        elif not has_year(m["b"]):
            end = end.replace(year=end.year + 1)
    s.set_period(start, end, span(start, end))


def _since(m: re.Match[str], s: _State) -> None:
    day = parse_date(m["a"], s.today)
    word = m["word"]
    if word == "before":
        s.set_period(None, day - timedelta(days=1), f"before {label(day)}")
    elif word == "after":
        start = day + timedelta(days=1)
        s.set_period(start, s.today, span(start, s.today))
    elif word == "since":
        s.set_period(day, s.today, span(day, s.today))
    else:  # on
        s.set_period(day, day, label(day))


def _one_day(m: re.Match[str], s: _State) -> None:
    day = parse_date(m["a"], s.today)
    s.set_period(day, day, label(day))


def _relative_day(m: re.Match[str], s: _State) -> None:
    day = s.today if m[1] == "today" else s.today - timedelta(days=1)
    s.set_period(day, day, f"{m[1].capitalize()}, {label(day)}")


def _last_n(m: re.Match[str], s: _State) -> None:
    n, unit = int(m[1]), m[2].rstrip("s")
    if not 1 <= n <= 3660:
        raise NotUnderstood("Choose a period of up to about ten years.")
    if unit == "month":
        start = add_months(s.today, -n) + timedelta(days=1)
    else:
        start = s.today - timedelta(days=n * (7 if unit == "week" else 1) - 1)
    s.set_period(start, s.today, span(start, s.today))


def _financial_year(m: re.Match[str], s: _State) -> None:
    this = financial_year_start(s.today)
    if m["which"] in ("last", "previous", "prev"):
        start = this.replace(year=this.year - 1)
        end = this - timedelta(days=1)
        s.set_period(start, end, f"Last financial year, {span(start, end)}")
    else:
        s.set_period(this, s.today, f"This financial year, {span(this, s.today)}")


def _fy_named(m: re.Match[str], s: _State) -> None:
    first = int(m[1])
    first += 2000 if first < 100 else 0
    start, end = date(first, 4, 1), date(first + 1, 3, 31)
    s.set_period(start, end, f"Financial year {first}-{str(first + 1)[2:]}, {span(start, end)}")


def _relative(m: re.Match[str], s: _State) -> None:
    which, unit = m["which"], m["unit"]
    last = which in ("last", "previous", "prev")
    t = s.today
    if unit == "week":
        monday = t - timedelta(days=t.weekday())
        start, end = monday, t
        if last:
            start, end = monday - timedelta(days=7), monday - timedelta(days=1)
    elif unit == "month":
        start, end = t.replace(day=1), t
        if last:
            end = start - timedelta(days=1)
            start = end.replace(day=1)
    else:  # calendar year
        start, end = date(t.year, 1, 1), t
        if last:
            start, end = date(t.year - 1, 1, 1), date(t.year - 1, 12, 31)
    s.set_period(start, end, span(start, end))


def _set_month(month: int, year_text: str | None, s: _State) -> None:
    """A whole month. With no year, the latest one that has started."""
    if year_text:
        year = int(year_text)
    else:
        year = s.today.year if month <= s.today.month else s.today.year - 1
    start, end = date(year, month, 1), month_end(year, month)
    s.set_period(start, end, span(start, end))


def _month(m: re.Match[str], s: _State) -> None:
    _set_month(MONTHS[m["month"].rstrip(".")], m["year"], s)


def _year(m: re.Match[str], s: _State) -> None:
    year = int(m[1])
    s.set_period(date(year, 1, 1), date(year, 12, 31), f"The year {year}")


def _amount_between(m: re.Match[str], s: _State) -> None:
    low, high = parse_amount(m[1], m[2]), parse_amount(m[3], m[4])
    s.min_total, s.max_total = min(low, high), max(low, high)


def _amount_min(m: re.Match[str], s: _State) -> None:
    s.min_total = parse_amount(m[1], m[2])


def _amount_max(m: re.Match[str], s: _State) -> None:
    s.max_total = parse_amount(m[1], m[2])


def _top(m: re.Match[str], s: _State) -> None:
    s.sort = "amount"
    number = m["n"] or m["n2"]
    if number:
        s.limit = min(int(number), 500)


RULES: Sequence[Rule] = (
    (rf"\b(?:from|between)\s+(?P<a>{DATE})\s+(?:and|to|till|until|-)\s+(?P<b>{DATE})", _range),
    (rf"(?P<a>{DATE})\s+(?:to|till|until|-)\s+(?P<b>{DATE})", _range),
    (rf"\b(?P<word>since|after|before|on)\s+(?P<a>{DATE})", _since),
    (r"\b(today|yesterday)\b", _relative_day),
    (r"\b(?:last|past|previous)\s+(\d{1,4})\s+(days?|weeks?|months?)\b", _last_n),
    (
        r"\b(?P<which>this|current|last|previous|prev)\s+(?:financial\s+year|fin(?:ancial)?\s*year|fy)\b",
        _financial_year,
    ),
    (r"\bfy\s*(\d{2}|\d{4})\s*[-/]\s*\d{2,4}\b", _fy_named),
    (r"\b(?P<which>this|current|last|previous|prev)\s+(?P<unit>week|month|year)\b", _relative),
    (rf"(?<![\w/.-])(?P<a>{DATE})(?![\w/.-])", _one_day),
    # "may" is also a verb, so as a month it needs a year or a word like "in" before it.
    (
        rf"\b(?:(?:in|for|of|during)\s+(?:the\s+month\s+of\s+)?may(?:\s+(?P<y1>{YEAR}))?"
        rf"|may\s+(?P<y2>{YEAR}))\b",
        lambda m, s: _set_month(5, m["y1"] or m["y2"], s),
    ),
    (
        rf"\b(?:the\s+month\s+of\s+)?(?P<month>(?!may\b){MONTH})(?:\s+(?P<year>{YEAR}))?(?![\w])",
        _month,
    ),
    (rf"\b(?:in|during|for|of|year)\s+({YEAR})\b", _year),
    (rf"\bbetween\s+{AMOUNT}\s+(?:and|to|-)\s+{AMOUNT}", _amount_between),
    (
        rf"(?:\b(?:over|above|more\s+than|greater\s+than|at\s+least|exceeding|minimum(?:\s+of)?|min)|>=?)\s*{AMOUNT}",
        _amount_min,
    ),
    (
        rf"(?:\b(?:under|below|less\s+than|at\s+most|up\s+to|upto|maximum(?:\s+of)?|max)|<=?)\s*{AMOUNT}",
        _amount_max,
    ),
    (
        r"\b(?:top(?:\s+(?P<n>\d{1,3}))?|(?:(?P<n2>\d{1,3})\s+)?(?:largest|biggest|highest|costliest|most\s+expensive))\b",
        _top,
    ),
)


def _consume(pattern: str, text: str, apply: Callable[[re.Match[str]], None]) -> str:
    def replace(m: re.Match[str]) -> str:
        apply(m)
        return " "

    return re.sub(pattern, replace, text)


def _vendor_name(text: str, vendors: Sequence[str], s: _State) -> str:
    """A vendor's full name, anywhere in the question. Read first, so a vendor called
    "Sector 12 Fuel Station" is not taken for the Fuel category."""
    for name in sorted(vendors, key=len, reverse=True):
        pattern = rf"(?<!\w){re.escape(name.lower())}(?!\w)"
        if re.search(pattern, text):
            s.vendor = name
            return re.sub(rf"\b(?:from|at)\s+{pattern}|{pattern}", " ", text, count=1)
    return text


def _vendor_start(text: str, vendors: Sequence[str], s: _State) -> str:
    """The start of a vendor's name after "from" or "at", if only one vendor fits. Read
    after the dates and amounts, so "from 1 Aug" and "at least" are already gone."""
    if s.vendor:
        return text
    m = re.search(r"\b(?:from|at)\s+([a-z0-9&'.\-]+(?:\s+[a-z0-9&'.\-]+){0,4})", text)
    if m:
        words = m[1].split()
        for size in range(len(words), 0, -1):
            phrase = " ".join(words[:size])
            if len(phrase) < 3 or phrase in FILLER:
                continue
            fits = [n for n in vendors if re.match(rf"{re.escape(phrase)}(?!\w)", n.lower())]
            if len(fits) == 1:
                s.vendor = fits[0]
                start = m.start()
                end = m.start(1) + len(phrase)
                return text[:start] + " " + text[end:]
    return text


def _category(text: str, categories: Sequence[tuple[int, str]], s: _State) -> str:
    terms: list[tuple[str, tuple[int, str]]] = []
    for category_id, name in categories:
        lower = name.lower()
        terms += [(lower, (category_id, name)), (f"{lower}s", (category_id, name))]
        terms += [(word, (category_id, name)) for word in SYNONYMS.get(lower, ())]
    found: dict[int, str] = {}
    for term, (category_id, name) in sorted(terms, key=lambda t: len(t[0]), reverse=True):
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        if re.search(pattern, text):
            found[category_id] = name
            text = re.sub(pattern, " ", text)
    if len(found) > 1:
        names = " and ".join(sorted(found.values()))
        raise NotUnderstood(f"Ask about one category at a time (found {names}).")
    if found:
        s.category = next(iter(found.items()))
    return text


def read_question(
    question: str,
    *,
    today: date,
    categories: Sequence[tuple[int, str]],
    vendors: Sequence[str],
) -> Reading:
    """The question as filters, what was understood, and any words that were not."""
    text = " " + question.lower().replace("’", "'") + " "  # noqa: RUF001 (curly apostrophe)
    text = re.sub(r"[?!;:\"()]|,(?=\s)", " ", text)
    text = re.sub(r"\s+", " ", text)
    s = _State(today=today)

    text = _vendor_name(text, vendors, s)
    for pattern, rule in RULES:
        text = _consume(pattern, text, lambda m, rule=rule: rule(m, s))
    text = _vendor_start(text, vendors, s)
    text = _category(text, categories, s)
    text = re.sub(r"(?<!\w)'s\b", " ", text)  # left from "last month's"

    ignored = [
        word.strip(".,'-")
        for word in re.findall(r"[a-z0-9₹][\w'.&-]*", text)
        if word.strip(".,'-") and word.strip(".,'-") not in FILLER
    ]
    found_something = (
        any((s.period, s.min_total is not None, s.max_total is not None, s.vendor, s.category))
        or s.sort != "date"
    )
    if not found_something and ignored:
        examples = "; ".join(f'"{e}"' for e in EXAMPLES)
        raise NotUnderstood(
            f"Could not understand that question. Try a category, vendor, month or amount, "
            f"for example {examples}."
        )

    understood: list[Understood] = []
    if s.vendor:
        understood.append(Understood(label="Vendor", value=s.vendor))
    if s.category:
        understood.append(Understood(label="Category", value=s.category[1]))
    if s.period:
        start, end, period_label = s.period
    else:
        start, end = financial_year_start(today), today
        period_label = f"This financial year, {span(start, end)} (default)"
    understood.append(Understood(label="Dates", value=period_label))
    if s.min_total is not None and s.max_total is not None:
        amount = f"{rupees(s.min_total)} to {rupees(s.max_total)}"
        understood.append(Understood(label="Amount", value=amount))
    elif s.min_total is not None:
        understood.append(Understood(label="Amount", value=f"{rupees(s.min_total)} or more"))
    elif s.max_total is not None:
        understood.append(Understood(label="Amount", value=f"{rupees(s.max_total)} or less"))
    if s.sort == "amount":
        order = f"Largest first, top {s.limit}" if s.limit else "Largest first"
        understood.append(Understood(label="Order", value=order))
    understood.append(Understood(label="Status", value="Parsed or Resolved"))

    try:
        query = ReceiptQuery(
            date_from=start,
            date_to=end,
            vendor=s.vendor,
            category_id=s.category[0] if s.category else None,
            min_total=s.min_total,
            max_total=s.max_total,
            sort=s.sort,  # type: ignore[arg-type]
            limit=s.limit,
        )
    except ValidationError as exc:
        message = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise NotUnderstood(message) from exc
    return Reading(query=query, understood=understood, ignored=list(dict.fromkeys(ignored)))
