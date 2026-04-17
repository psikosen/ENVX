"""Database-layer helpers.

SQL lives in ``migrations/`` as plain .sql files so they can be applied by
any migration runner (psycopg, Alembic, sqlx). Nothing in Python depends on
a specific driver yet.
"""
