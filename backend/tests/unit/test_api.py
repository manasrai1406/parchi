"""API behaviour that does not need PostgreSQL or Redis."""

import pytest
from fastapi.testclient import TestClient

from parchi.api.main import create_app
from parchi.api.routes import health


@pytest.fixture
def app():
    app = create_app()

    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("receipt text must not leak")

    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_health_is_ok_without_services(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_has_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert len(response.headers["x-request-id"]) == 32


def test_a_safe_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-abc-12345"})
    assert response.headers["x-request-id"] == "trace-abc-12345"


def test_an_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["x-request-id"] != "bad id\nwith newline"


def test_not_found_uses_the_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["x-request-id"]


def test_unhandled_error_uses_the_error_shape_and_hides_details(client: TestClient) -> None:
    response = client.get("/_boom")
    assert response.status_code == 500
    body = response.json()
    assert body == {
        "code": "internal_error",
        "message": "Something went wrong.",
        "request_id": response.headers["x-request-id"],
    }


def test_ready_reports_which_services_are_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down() -> None:
        raise ConnectionError

    async def up() -> None:
        return None

    monkeypatch.setattr(health, "_check_database", down)
    monkeypatch.setattr(health, "_check_redis", up)

    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "not_ready"
    assert response.json()["message"] == "Unavailable: database"


def test_ready_is_ok_when_services_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def up() -> None:
        return None

    monkeypatch.setattr(health, "_check_database", up)
    monkeypatch.setattr(health, "_check_redis", up)

    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}
