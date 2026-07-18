from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture(autouse=True)
def clean_live_database() -> Iterator[None]:
    admin_url = os.environ["VANTIX_ADMIN_DATABASE_URL"]
    engine = create_engine(admin_url)
    with engine.begin() as connection:
        tables = connection.execute(
            text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename <> 'alembic_version'
                """
            )
        ).scalars()
        quoted = ", ".join(f'"{table}"' for table in tables)
        if quoted:
            connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
    yield
    engine.dispose()
