"""Database layer.

SQL lives in ``migrations/`` as plain .sql files so it can be applied by any
runner (psycopg, Alembic, sqlx, psql). ``repository.py`` binds the pipeline
objects to that schema; psycopg is an optional dependency.
"""

from .repository import DocumentRecord, PostgresRepository, psycopg_available

__all__ = ["DocumentRecord", "PostgresRepository", "psycopg_available"]
