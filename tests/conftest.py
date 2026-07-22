"""Shared pytest fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, ImportLog, PosPayment


@pytest.fixture
def sqlite_session():
    """
    In-memory SQLite session with just the tables the ingestion-correctness tests
    touch. The models use no Postgres-only column types, so importers run against
    SQLite unchanged.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[ImportLog.__table__, PosPayment.__table__]
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
