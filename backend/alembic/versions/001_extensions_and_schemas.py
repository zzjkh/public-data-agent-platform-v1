"""extensions and schemas

Revision ID: 001_extensions_and_schemas
Revises:
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op

revision = "001_extensions_and_schemas"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS reporting")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS reporting CASCADE")
    op.execute("DROP EXTENSION IF EXISTS vector")

