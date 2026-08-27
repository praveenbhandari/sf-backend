from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    """Create tables. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """
    Add columns that `create_all` cannot: it creates missing tables but never
    alters existing ones, so a database written by an older version would be
    missing newly mapped columns. This project ships no migration tool, so
    reconcile the additive case here and let anything else surface loudly.
    """
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or not column.nullable:
                    continue
                type_sql = column.type.compile(engine.dialect)
                # A sibling worker can add the column between inspect and ALTER.
                # Use a savepoint so a duplicate-column error does not abort
                # this transaction (PostgreSQL would otherwise fail startup).
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}')
                        )
                except (OperationalError, ProgrammingError) as exc:
                    if not _is_duplicate_column(exc):
                        raise


# PostgreSQL `duplicate_column` — see https://www.postgresql.org/docs/current/errcodes-appendix.html
_PG_DUPLICATE_COLUMN = "42701"


def _is_duplicate_column(exc: BaseException) -> bool:
    """True only for a racing ADD COLUMN, not for other 'already exists' errors."""
    orig = getattr(exc, "orig", None) or exc
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == _PG_DUPLICATE_COLUMN:
        return True
    # SQLite has no SQLSTATE; its OperationalError text is the dialect's contract.
    return "duplicate column name" in str(orig).lower()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
