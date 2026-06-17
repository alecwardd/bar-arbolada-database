"""
Bar Arbolada - Database Setup Script

Creates the PostgreSQL database and user if they don't exist,
then runs Alembic migrations to create all tables.

Usage:
    python scripts/setup_db.py

Prerequisites:
    1. PostgreSQL is installed and running
    2. You have a .env file with DB credentials (copy from .env.example)
    3. pip install -r requirements.txt
"""

import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATABASE_URL, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT


def check_postgres_connection():
    """Verify PostgreSQL is running and accessible."""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user="postgres",  # default superuser
            password="",  # try without password first
            dbname="postgres",
        )
        conn.close()
        print(f"[OK] PostgreSQL is running at {DB_HOST}:{DB_PORT}")
        return True
    except Exception as e:
        print(f"[!!] Cannot connect to PostgreSQL at {DB_HOST}:{DB_PORT}")
        print(f"     Error: {e}")
        print()
        print("Make sure PostgreSQL is installed and running.")
        print("On Windows: Check Services for 'postgresql' or run:")
        print("  pg_ctl start -D \"C:\\Program Files\\PostgreSQL\\16\\data\"")
        return False


def create_database():
    """Create database and user if they don't exist."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    try:
        # Connect as superuser
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user="postgres",
            dbname="postgres",
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Check if user exists
        cur.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (DB_USER,)
        )
        if not cur.fetchone():
            cur.execute(
                f"CREATE USER {DB_USER} WITH PASSWORD '{DB_PASSWORD}'"
            )
            print(f"[OK] Created user: {DB_USER}")
        else:
            print(f"[OK] User already exists: {DB_USER}")

        # Check if database exists
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
        )
        if not cur.fetchone():
            cur.execute(
                f"CREATE DATABASE {DB_NAME} OWNER {DB_USER}"
            )
            print(f"[OK] Created database: {DB_NAME}")
        else:
            print(f"[OK] Database already exists: {DB_NAME}")

        # Grant privileges
        cur.execute(
            f"GRANT ALL PRIVILEGES ON DATABASE {DB_NAME} TO {DB_USER}"
        )

        cur.close()
        conn.close()
        return True

    except Exception as e:
        print(f"[!!] Error creating database: {e}")
        print()
        print("You may need to create the database manually:")
        print(f"  CREATE USER {DB_USER} WITH PASSWORD '<your-password>';")
        print(f"  CREATE DATABASE {DB_NAME} OWNER {DB_USER};")
        return False


def run_migrations():
    """Run Alembic migrations to create all tables."""
    project_root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[OK] Alembic migrations applied successfully")
        if result.stdout:
            print(result.stdout)
        return True
    else:
        print("[!!] Alembic migration failed:")
        print(result.stderr)
        return False


def verify_tables():
    """Verify all expected tables were created."""
    from sqlalchemy import inspect
    from src.config import engine
    from src.models import Base

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    expected_tables = sorted(Base.metadata.tables.keys())

    missing = [t for t in expected_tables if t not in tables]
    found = [t for t in expected_tables if t in tables]

    print(f"\n[OK] Found {len(found)}/{len(expected_tables)} expected tables")
    if missing:
        print(f"[!!] Missing tables: {', '.join(missing)}")
    else:
        print("[OK] All tables created successfully!")

    return len(missing) == 0


if __name__ == "__main__":
    print("=" * 60)
    print("Bar Arbolada - Database Setup")
    print("=" * 60)
    print()

    print(f"Database URL: {DATABASE_URL.replace(DB_PASSWORD, '***')}")
    print()

    if not check_postgres_connection():
        sys.exit(1)

    if not create_database():
        print("\nSkipping auto-creation. Please create the database manually.")
        print("Then re-run this script to apply migrations.")

    print()
    if run_migrations():
        verify_tables()
    else:
        print("\nMigrations failed. Check the error above.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("Setup complete! Next step: import your CSV data.")
    print("  python scripts/import_all.py")
    print("=" * 60)
