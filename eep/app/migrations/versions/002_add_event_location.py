"""Add camera_id column to events table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable camera_id to events — IEP1 real-mode populates it; stub leaves it NULL."""
    op.add_column("events", sa.Column("camera_id", sa.String(64), nullable=True))


def downgrade() -> None:
    """Drop camera_id column from events."""
    op.drop_column("events", "camera_id")
