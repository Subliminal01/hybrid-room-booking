from collections.abc import Generator
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, echo=settings.sql_echo)


def create_db_and_tables() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
