"""Phase 7 on a real database: filters, totals, CSV, questions and read-only access.

The exit check: "fuel in August" returns the right rows.
"""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_pipeline import process, upload
from tests.integration.test_review import SAMPLES, bill

pytestmark = pytest.mark.db

# (vendor, number, date, total, category): what a person confirmed for each file.
RECEIPTS = [
    ("Sector 12 Fuel Station", "SF-20431", "2026-08-03", "2400.00", "Fuel"),
    ("Ring Road Petrol Pump", "RR-77120", "2026-08-09", "1850.00", "Fuel"),
    ("Sector 12 Fuel Station", "SF-20502", "2026-08-14", "2100.00", "Fuel"),
    ("Sector 12 Fuel Station", "SF-19870", "2026-07-28", "2000.00", "Fuel"),  # July
    ("Blue Tokai Coffee Roasters", "BT-118", "2026-08-14", "540.00", "Food"),
    ("Raju Hardware", "5512", "2026-05-02", "210.00", "Maintenance"),
    ("=HYPERLINK(1)", "X-1", "2026-06-10", "99.00", "Other"),  # formula-like name
    ("Old Year Traders", "OY-1", "2025-12-20", "750.00", "Office"),  # last financial year
]


@pytest.fixture
def seeded(api: TestClient, storage_dir: str) -> dict[str, int]:
    categories = {c["name"]: c["id"] for c in api.get("/categories").json()}
    for index, (vendor, number, day, total, category) in enumerate(RECEIPTS):
        file = upload(api, bill(f"bill_{index}.xlsx", number=f"Q{index}", total=1, items=[1]))
        process(storage_dir, file["id"])
        receipt = {
            "vendor": vendor,
            "receipt_number": number,
            "receipt_date": day,
            "total": total,
            "category_id": categories[category],
        }
        response = api.put(f"/files/{file['id']}/receipts", json={"receipts": [receipt]})
        assert response.status_code == 200, response.text
    # One file still waiting for a person: its receipt is not counted.
    waiting = upload(api, SAMPLES["incomplete_bill.xlsx"])
    process(storage_dir, waiting["id"])
    return categories


def rows(page: dict) -> list[tuple[str, str, str]]:
    return [(r["receipt_date"], r["vendor"], r["total"]) for r in page["items"]]


def test_fuel_in_august_returns_the_right_rows(api: TestClient, seeded: dict) -> None:
    response = api.post("/query/ask", json={"question": "fuel in August"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert rows(body["result"]) == [
        ("2026-08-03", "Sector 12 Fuel Station", "2400.00"),
        ("2026-08-09", "Ring Road Petrol Pump", "1850.00"),
        ("2026-08-14", "Sector 12 Fuel Station", "2100.00"),
    ]
    assert (body["result"]["count"], body["result"]["sum_total"]) == (3, "6350.00")
    assert body["result"]["average_total"] == "2116.67"
    assert body["result"]["waiting_for_review"] == 1
    understood = {item["label"]: item["value"] for item in body["understood_as"]}
    assert understood == {
        "Category": "Fuel",
        "Dates": "1 Aug 2026 to 31 Aug 2026",
        "Status": "Parsed or Resolved",
    }
    assert body["ignored"] == []
    assert "BETWEEN '2026-08-01' AND '2026-08-31'" in body["sql"]
    assert f"category_id = {seeded['Fuel']}" in body["sql"]
    assert body["filters"]["category_id"] == seeded["Fuel"]


def test_the_same_filters_give_the_same_rows(api: TestClient, seeded: dict) -> None:
    asked = api.post("/query/ask", json={"question": "fuel in August"}).json()
    params = {k: v for k, v in asked["filters"].items() if v is not None}
    assert rows(api.get("/receipts", params=params).json()) == rows(asked["result"])


def test_no_dates_means_this_financial_year(api: TestClient, seeded: dict) -> None:
    page = api.get("/receipts").json()

    assert (page["date_from"], page["date_to"]) == ("2026-04-01", "2026-09-26")
    assert page["count"] == 7  # everything but last December's
    assert "Old Year Traders" not in {r["vendor"] for r in page["items"]}


def test_filters_combine(api: TestClient, seeded: dict) -> None:
    page = api.get(
        "/receipts",
        params={
            "date_from": "2026-07-01",
            "date_to": "2026-08-31",
            "vendor": "Sector 12 Fuel Station",
            "min_total": "2050",
        },
    ).json()
    assert rows(page) == [
        ("2026-08-03", "Sector 12 Fuel Station", "2400.00"),
        ("2026-08-14", "Sector 12 Fuel Station", "2100.00"),
    ]


def test_largest_first_and_top_n(api: TestClient, seeded: dict) -> None:
    body = api.post("/query/ask", json={"question": "top 2 this financial year"}).json()
    assert [r["total"] for r in body["result"]["items"]] == ["2400.00", "2100.00"]
    assert body["result"]["count"] == 2
    assert body["result"]["sum_total"] == "4500.00"


def test_pages_of_fifty_and_totals_over_everything(api: TestClient, seeded: dict) -> None:
    second = api.get("/receipts", params={"page": 2}).json()
    assert (second["items"], second["count"], second["page_size"]) == ([], 7, 50)
    assert second["sum_total"] == "9199.00"


def test_bad_filters_are_refused(api: TestClient, seeded: dict) -> None:
    backwards = api.get("/receipts", params={"date_from": "2026-09-01", "date_to": "2026-08-01"})
    assert backwards.status_code == 422
    assert "From cannot be later than To" in backwards.json()["message"]
    assert api.get("/receipts", params={"min_total": "-1"}).status_code == 422
    assert api.get("/receipts", params={"sql": "DROP TABLE files"}).status_code == 422


def test_questions_it_cannot_read_say_so(api: TestClient, seeded: dict) -> None:
    response = api.post("/query/ask", json={"question": "hello there"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "question_not_understood"
    assert "fuel in August" in body["message"]


def test_words_it_skips_are_listed(api: TestClient, seeded: dict) -> None:
    body = api.post("/query/ask", json={"question": "fuel in august urgently"}).json()
    assert body["ignored"] == ["urgently"]
    assert body["result"]["count"] == 3


def test_a_question_cannot_inject_sql(api: TestClient, seeded: dict) -> None:
    question = "fuel from x'; DROP TABLE receipts; -- in august"
    response = api.post("/query/ask", json={"question": question})
    assert response.status_code == 200
    assert "DROP" not in response.json()["sql"]
    assert api.get("/receipts").json()["count"] == 7


def test_vendors_for_the_filter(api: TestClient, seeded: dict) -> None:
    vendors = api.get("/vendors").json()
    assert sorted(vendors) == sorted({receipt[0] for receipt in RECEIPTS})
    assert len(vendors) == len(set(vendors))


def test_csv_export_has_every_matching_row(api: TestClient, seeded: dict) -> None:
    response = api.get("/receipts/export.csv", params={"date_from": "2026-04-01"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    table = list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))
    assert table[0] == [
        "Date", "Vendor", "Receipt no.", "Category", "Subtotal", "Tax", "Total", "Reference",
        "File",
    ]  # fmt: skip
    assert len(table) == 1 + 7
    first = table[1]
    assert first[:4] == ["2026-05-02", "Raju Hardware", "5512", "Maintenance"]
    assert first[6] == "210.00"
    assert first[7].endswith("-01") and first[8].startswith("REF-")
    formula = next(row for row in table if "HYPERLINK" in row[1])
    assert formula[1] == "'=HYPERLINK(1)"  # not run by a spreadsheet


# --- read-only access (D-038) ------------------------------------------------------------


def as_reader(engine: Engine, sql: str) -> None:
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET LOCAL ROLE parchi_reader"))
        connection.execute(text(sql))


def test_the_reader_can_only_read_the_view(engine: Engine, seeded: dict) -> None:
    as_reader(engine, "SELECT count(*) FROM receipt_view")
    for sql in (
        "SELECT * FROM files",
        "SELECT * FROM receipts",
        "SELECT * FROM extraction_runs",
        "DELETE FROM receipt_view",
        "CREATE TABLE sneaky (id int)",
    ):
        with pytest.raises(DBAPIError, match=r"permission denied|cannot delete"):
            as_reader(engine, sql)


@pytest.mark.parametrize(
    ("sql", "refusal"),
    [
        # Even a temporary table, which any role may normally create.
        ("CREATE TEMP TABLE scratch (id int)", "read-only transaction"),
        ("SELECT * FROM files", "permission denied"),
        ("SELECT count(*) FROM receipt_view", None),
    ],
)
def test_query_sessions_are_read_only_and_run_as_the_reader(
    api: TestClient, seeded: dict, sql: str, refusal: str | None
) -> None:
    import asyncio
    import sys

    from parchi.query.readonly import reader_session

    async def attempt() -> None:
        async with reader_session() as session:
            await session.execute(text(sql))

    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        if refusal is None:
            loop.run_until_complete(attempt())
        else:
            with pytest.raises(DBAPIError, match=refusal):
                loop.run_until_complete(attempt())
    finally:
        loop.close()
