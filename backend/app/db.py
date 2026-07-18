from collections.abc import Generator
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def session_scope() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session


def set_tenant_context(
    session: Session,
    *,
    user_id: UUID,
    organisation_id: UUID,
    project_ids: tuple[UUID, ...],
    is_system_service: bool = False,
) -> None:
    """Set transaction-local PostgreSQL context consumed by restrictive RLS policies."""

    values = {
        "app.current_user_id": str(user_id),
        "app.current_org_id": str(organisation_id),
        "app.current_project_ids": ",".join(str(project_id) for project_id in project_ids),
        "app.is_system_service": "true" if is_system_service else "false",
    }
    for setting, value in values.items():
        session.execute(
            text("SELECT set_config(:setting, :value, true)"),
            {"setting": setting, "value": value},
        )
