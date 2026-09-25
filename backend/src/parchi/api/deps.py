"""Shared FastAPI dependencies."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.config import Settings, get_settings
from parchi.db.session import get_session
from parchi.ingestion.storage import Storage


@lru_cache
def _storage_for(root: Path) -> Storage:
    storage = Storage(root)
    storage.ensure_dirs()
    return storage


def get_storage(settings: Annotated[Settings, Depends(get_settings)]) -> Storage:
    return _storage_for(settings.storage_dir)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[Storage, Depends(get_storage)]
