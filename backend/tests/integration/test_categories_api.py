"""D-026: built-in and user-added categories through the API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

BUILTIN = ["Fuel", "Travel", "Food", "Office", "Utilities", "Maintenance", "Services", "Other"]


def names(api: TestClient) -> list[str]:
    return [c["name"] for c in api.get("/categories").json()]


def test_the_builtin_categories_are_listed_first(api: TestClient) -> None:
    api.post("/categories", json={"name": "Zoo tickets"})
    api.post("/categories", json={"name": "Client visits"})

    listed = api.get("/categories").json()
    assert [c["name"] for c in listed] == [*BUILTIN, "Client visits", "Zoo tickets"]
    assert [c["builtin"] for c in listed] == [True] * 8 + [False] * 2
    assert all(c["in_use"] == 0 for c in listed)


def test_adding_a_category_tidies_its_name(api: TestClient) -> None:
    response = api.post("/categories", json={"name": "  Client   visits "})
    assert response.status_code == 201
    assert response.json()["name"] == "Client visits"
    assert response.json()["builtin"] is False


@pytest.mark.parametrize("name", ["fuel", "FUEL", " Fuel "])
def test_a_name_that_exists_in_any_case_is_refused(api: TestClient, name: str) -> None:
    response = api.post("/categories", json={"name": name})
    assert response.status_code == 409
    assert response.json()["code"] == "category_exists"


@pytest.mark.parametrize(("name", "reason"), [("   ", "needs a name"), ("x" * 51, "at most 50")])
def test_bad_names_are_refused_with_a_reason(api: TestClient, name: str, reason: str) -> None:
    response = api.post("/categories", json={"name": name})
    assert response.status_code == 422
    assert reason in response.json()["message"]


def test_tabs_and_newlines_count_as_spaces(api: TestClient) -> None:
    response = api.post("/categories", json={"name": "Client" + chr(9) + "visits" + chr(10)})
    assert response.json()["name"] == "Client visits"


def test_a_control_character_is_refused(api: TestClient) -> None:
    response = api.post("/categories", json={"name": "bell" + chr(7)})
    assert response.status_code == 422
    assert "control characters" in response.json()["message"]


def test_custom_categories_can_be_renamed(api: TestClient) -> None:
    created = api.post("/categories", json={"name": "Client visits"}).json()

    response = api.patch(f"/categories/{created['id']}", json={"name": "Client meetings"})
    assert response.status_code == 200
    assert "Client meetings" in names(api)
    assert api.patch(f"/categories/{created['id']}", json={"name": "travel"}).status_code == 409


def test_builtin_categories_cannot_be_renamed_or_deleted(api: TestClient) -> None:
    fuel = api.get("/categories").json()[0]
    assert api.patch(f"/categories/{fuel['id']}", json={"name": "Petrol"}).json()["code"] == (
        "builtin_category"
    )
    assert api.delete(f"/categories/{fuel['id']}").json()["code"] == "builtin_category"
    assert "Fuel" in names(api)


def test_an_unused_custom_category_can_be_deleted(api: TestClient) -> None:
    created = api.post("/categories", json={"name": "Client visits"}).json()
    assert api.delete(f"/categories/{created['id']}").status_code == 204
    assert "Client visits" not in names(api)
    assert api.delete(f"/categories/{created['id']}").status_code == 404


def test_a_category_in_use_cannot_be_deleted(api: TestClient, engine: Engine) -> None:
    created = api.post("/categories", json={"name": "Client visits"}).json()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vendors (raw_name, normalized_name, default_category_id)"
                " VALUES ('Taj Hotel', 'Taj Hotel', :c)"
            ),
            {"c": created["id"]},
        )

    response = api.delete(f"/categories/{created['id']}")

    assert response.status_code == 409
    assert response.json()["code"] == "category_in_use"
    assert "1 vendor" in response.json()["message"]
    in_use = {c["name"]: c["in_use"] for c in api.get("/categories").json()}
    assert in_use["Client visits"] == 1
