"""Create an admin account, for the first login (D-045).

Usage (the stack running):
    docker compose exec api python scripts/create_admin.py <username> "<Display name>"

The password is asked for twice and never shown. It is temporary: Parchi asks for a new
one at the first login. Use --password-stdin to read it from standard input instead.
"""

import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError

from parchi.auth import accounts
from parchi.db.enums import UserRole
from parchi.db.models import User
from parchi.db.session import get_engine, get_sessionmaker
from parchi.schemas.api import UserCreateIn


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        # Windows shells may add "\r\n" and a byte-order mark when piping.
        return sys.stdin.readline().lstrip("﻿").rstrip("\r\n")
    first = getpass.getpass("Temporary password (10 to 128 characters): ")
    if getpass.getpass("Again: ") != first:
        raise SystemExit("The two passwords do not match.")
    return first


async def create(details: UserCreateIn) -> None:
    try:
        async with get_sessionmaker()() as session:
            if await accounts.find_by_username(session, details.username) is not None:
                raise SystemExit(f'The username "{details.username}" is already taken.')
            user = User(
                username=details.username, display_name=details.display_name, role=details.role
            )
            accounts.set_password(user, details.temporary_password, temporary=True)
            session.add(user)
            await session.commit()
    finally:
        await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Parchi admin account.")
    parser.add_argument("username", help="3 to 50 of a-z 0-9 . _ -")
    parser.add_argument("display_name", help='The name shown in Parchi, e.g. "Manas Rai"')
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    try:
        details = UserCreateIn(
            username=args.username,
            display_name=args.display_name,
            role=UserRole.ADMIN,
            temporary_password=read_password(args.password_stdin),
        )
    except ValidationError as exc:
        problems = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
        raise SystemExit(f"Not created: {problems}") from exc
    # psycopg's async mode cannot run on Windows' default event loop.
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(create(details), loop_factory=loop)
    print(f'Admin "{details.username}" created. Log in and choose a new password.')


if __name__ == "__main__":
    main()
