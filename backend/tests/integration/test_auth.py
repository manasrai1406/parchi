"""Login, sessions, roles and user management on a real database (D-043 to D-045)."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from tests.integration.conftest import PASSWORD, log_in

pytestmark = pytest.mark.db

# Routes anyone may call, and routes that change nothing although they are not GETs.
OPEN = {("GET", "/health"), ("GET", "/health/ready"), ("POST", "/auth/login")}
READ_ONLY_POSTS = {("POST", "/query/ask")}
# A logged-in user may always log out and change their own password.
OWN_ACCOUNT = {("POST", "/auth/logout"), ("PUT", "/auth/password"), ("GET", "/auth/me")}


def every_route(api: TestClient) -> list[tuple[str, str]]:
    spec = api.get("/openapi.json").json()
    return [
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    ]


def call(api: TestClient, method: str, path: str):
    url = re.sub(r"\{file_key\}", "REF-2026-000001", path)
    url = re.sub(r"\{[a-z_]+\}", "1", url)
    return api.request(method, url, json={} if method != "GET" else None)


def test_every_route_needs_a_login(api: TestClient) -> None:
    api.cookies.clear()
    checked = 0
    for method, path in every_route(api):
        if (method, path) in OPEN:
            continue
        response = call(api, method, path)
        assert response.status_code == 401, (method, path, response.status_code)
        checked += 1
    assert checked > 25


def test_viewers_cannot_change_anything(api: TestClient) -> None:
    log_in(api, "viewer")
    for method, path in every_route(api):
        if method == "GET" or (method, path) in OPEN | READ_ONLY_POSTS | OWN_ACCOUNT:
            continue
        response = call(api, method, path)
        assert response.status_code == 403, (method, path, response.status_code)
        assert response.json()["code"] == "forbidden"


def test_viewers_can_look_and_query(api: TestClient) -> None:
    log_in(api, "viewer")
    assert api.get("/files").status_code == 200
    assert api.get("/receipts").status_code == 200
    assert api.post("/query/ask", json={"question": "fuel in august"}).status_code == 200
    assert api.get("/receipts/export.csv").status_code == 200


def test_reviewers_work_on_files_but_cannot_delete_or_manage_users(api: TestClient) -> None:
    log_in(api, "reviewer")
    assert api.post("/batches").status_code == 201
    assert api.post("/categories", json={"name": "Client gifts"}).status_code == 201
    assert api.delete("/files/REF-2026-000001").status_code == 403
    assert api.get("/users").status_code == 403


# --- logging in and out ---------------------------------------------------------------------


def test_login_sets_a_safe_cookie_and_me_says_who(api: TestClient) -> None:
    response = log_in(api, "Reviewer")  # usernames ignore case

    cookie = response.headers["set-cookie"]
    assert "parchi_session=" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert response.json()["role"] == "reviewer"
    me = api.get("/auth/me").json()
    assert (me["username"], me["display_name"], me["must_change_password"]) == (
        "reviewer",
        "Reviewer",
        False,
    )


def test_the_database_only_keeps_a_hash_of_the_session(api: TestClient, engine: Engine) -> None:
    log_in(api, "viewer")
    token = api.cookies.get("parchi_session")
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM sessions")).scalars().all()
    assert token not in stored
    assert all(len(value) == 64 for value in stored)


@pytest.mark.parametrize("username", ["admin", "nobody"])
def test_wrong_details_get_the_same_answer(api: TestClient, username: str) -> None:
    api.cookies.clear()
    response = api.post("/auth/login", json={"username": username, "password": "wrong password"})
    assert response.status_code == 401
    assert response.json()["message"] == "Wrong username or password."


def test_five_wrong_passwords_lock_the_account(api: TestClient) -> None:
    api.cookies.clear()
    for _ in range(5):
        api.post("/auth/login", json={"username": "viewer", "password": "wrong password"})
    locked = api.post("/auth/login", json={"username": "viewer", "password": PASSWORD})
    assert locked.status_code == 401
    assert "15 minutes" in locked.json()["message"]
    log_in(api, "reviewer")  # other accounts are unaffected


def test_logging_out_ends_the_session(api: TestClient) -> None:
    log_in(api, "viewer")
    old = api.cookies.get("parchi_session")
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/auth/me").status_code == 401
    api.cookies.set("parchi_session", old)
    assert api.get("/files").status_code == 401  # the old token is no longer valid


# --- passwords --------------------------------------------------------------------------------


def new_user(api: TestClient, username: str = "priya", role: str = "reviewer") -> dict:
    log_in(api, "admin")
    response = api.post(
        "/users",
        json={
            "username": username,
            "display_name": "Priya Sharma",
            "role": role,
            "temporary_password": "temporary pass 1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_temporary_password_must_be_changed_first(api: TestClient) -> None:
    created = new_user(api)
    assert created["must_change_password"] is True
    log_in(api, "priya", "temporary pass 1")

    blocked = api.get("/files")
    assert (blocked.status_code, blocked.json()["code"]) == (403, "password_change_required")
    assert api.get("/auth/me").json()["must_change_password"] is True

    changed = api.put(
        "/auth/password",
        json={"current_password": "temporary pass 1", "new_password": "my own password 7"},
    )
    assert changed.status_code == 200, changed.text
    assert api.get("/files").status_code == 200
    api.cookies.clear()
    wrong = api.post("/auth/login", json={"username": "priya", "password": "temporary pass 1"})
    assert wrong.status_code == 401
    log_in(api, "priya", "my own password 7")


@pytest.mark.parametrize(
    ("current", "new", "code"),
    [
        ("wrong password", "another password 9", "wrong_password"),
        (PASSWORD, PASSWORD, "same_password"),
    ],
)
def test_bad_password_changes_are_refused(
    api: TestClient, current: str, new: str, code: str
) -> None:
    log_in(api, "reviewer")
    response = api.put("/auth/password", json={"current_password": current, "new_password": new})
    assert (response.status_code, response.json()["code"]) == (400, code)


def test_the_password_cannot_be_the_username(api: TestClient) -> None:
    new_user(api, username="longusername")
    log_in(api, "longusername", "temporary pass 1")
    response = api.put(
        "/auth/password",
        json={"current_password": "temporary pass 1", "new_password": "LongUsername"},
    )
    assert (response.status_code, response.json()["code"]) == (400, "weak_password")


def test_short_passwords_are_refused(api: TestClient) -> None:
    log_in(api, "reviewer")
    response = api.put(
        "/auth/password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert response.status_code == 422


# --- managing users ---------------------------------------------------------------------------


def test_admins_list_and_create_users(api: TestClient) -> None:
    new_user(api, username="Priya.S")
    users = {user["username"]: user for user in api.get("/users").json()}
    assert set(users) == {"admin", "reviewer", "viewer", "priya.s"}
    assert "password_hash" not in users["priya.s"]
    again = api.post(
        "/users",
        json={
            "username": "PRIYA.S",
            "display_name": "Someone else",
            "role": "viewer",
            "temporary_password": "temporary pass 2",
        },
    )
    assert (again.status_code, again.json()["code"]) == (409, "username_taken")


def test_changing_a_role_takes_effect_at_once(api: TestClient) -> None:
    user = new_user(api, role="viewer")
    log_in(api, "priya", "temporary pass 1")
    api.put(
        "/auth/password",
        json={"current_password": "temporary pass 1", "new_password": "my own password 7"},
    )
    assert api.post("/batches").status_code == 403
    their_cookie = api.cookies.get("parchi_session")

    log_in(api, "admin")
    assert api.patch(f"/users/{user['id']}", json={"role": "reviewer"}).status_code == 200

    api.cookies.clear()
    api.cookies.set("parchi_session", their_cookie)  # the same session, not a new login
    assert api.post("/batches").status_code == 201


def test_deactivating_a_user_logs_them_out(api: TestClient) -> None:
    user = new_user(api)
    log_in(api, "priya", "temporary pass 1")
    their_cookie = api.cookies.get("parchi_session")

    log_in(api, "admin")
    response = api.patch(f"/users/{user['id']}", json={"active": False})
    assert response.json()["active"] is False

    api.cookies.clear()
    api.cookies.set("parchi_session", their_cookie)
    assert api.get("/auth/me").status_code == 401
    api.cookies.clear()
    refused = api.post("/auth/login", json={"username": "priya", "password": "temporary pass 1"})
    assert refused.status_code == 401


def test_a_reset_password_is_temporary(api: TestClient) -> None:
    user = new_user(api)
    response = api.post(
        f"/users/{user['id']}/password", json={"temporary_password": "fresh start 42"}
    )
    assert response.json()["must_change_password"] is True
    log_in(api, "priya", "fresh start 42")
    assert api.get("/auth/me").json()["must_change_password"] is True


def test_admins_cannot_demote_or_deactivate_themselves(api: TestClient) -> None:
    me = api.get("/auth/me").json()
    for change in ({"role": "reviewer"}, {"active": False}):
        response = api.patch(f"/users/{me['id']}", json=change)
        assert (response.status_code, response.json()["code"]) == (409, "own_account")
    assert api.patch(f"/users/{me['id']}", json={"display_name": "The Admin"}).status_code == 200
