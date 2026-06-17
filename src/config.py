"""
Bar Arbolada Analytics System - Configuration

Loads database connection settings from .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Database settings
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "bar_arbolada")
DB_USER = os.getenv("DB_USER", "bar_arbolada")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# Project paths
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_STAGING_DIR = PROJECT_ROOT / "data" / "staging"
RAW_CSVS_DIR = PROJECT_ROOT / "raw-csvs-before-pos-changes"
RAW_INVOICES_DIR = PROJECT_ROOT / "raw-invoices-unedited"

# SQLAlchemy engine and session
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    """Get a new database session. Caller is responsible for closing."""
    return SessionLocal()
