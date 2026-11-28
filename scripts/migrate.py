"""Apply the SQL files in migrations/ to DATABASE_URL, in order, once each.

Usage (from the repo root):

    python scripts/migrate.py

Each file runs in its own transaction and is recorded in app.schema_migrations
with a checksum. Already-applied files are skipped; if one has been edited
since it was applied, the script stops -- add a new migration instead.
"""

import hashlib
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"

# Arbitrary number; a Postgres advisory lock on it stops two runs at once.
LOCK_ID = 727_001

BOOTSTRAP_SQL = """
create schema if not exists app;
create table if not exists app.schema_migrations (
    filename   text primary key,
    checksum   text not null,
    applied_at timestamptz not null default now()
);
"""


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    with psycopg.connect(settings.database_url.get_secret_value(), autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_ID,))
        conn.execute(BOOTSTRAP_SQL)
        applied = dict(conn.execute("select filename, checksum from app.schema_migrations").fetchall())

        for path in files:
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()

            if path.name in applied:
                if applied[path.name] != checksum:
                    print(
                        f"ERROR  {path.name} was edited after it was applied. "
                        "Put the change in a new migration file instead.",
                        file=sys.stderr,
                    )
                    return 1
                print(f"skip   {path.name}")
                continue

            try:
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "insert into app.schema_migrations (filename, checksum) values (%s, %s)",
                        (path.name, checksum),
                    )
            except psycopg.Error as exc:
                print(f"FAILED {path.name} (rolled back): {exc}", file=sys.stderr)
                return 1
            print(f"apply  {path.name}")

    print("Database is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
