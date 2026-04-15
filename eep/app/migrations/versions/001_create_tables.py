"""Create initial tables: pipeline_runs, events, hotspots, reports.

Revision ID: 001
Revises:
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all four core tables for the InfraGuard pipeline."""
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column("video_path", sa.Text, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.Text, nullable=True),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "run_id",
            sa.Text,
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(50), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("violation_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "hotspots",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "run_id",
            sa.Text,
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hotspot_id", sa.String(50), nullable=False),
        sa.Column("center_lat", sa.Float, nullable=False),
        sa.Column("center_lon", sa.Float, nullable=False),
        sa.Column("radius_meters", sa.Float, nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("risk_score", sa.Float, nullable=False),
        sa.Column("dominant_violation", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "run_id",
            sa.Text,
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pdf_url", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("reports")
    op.drop_table("hotspots")
    op.drop_table("events")
    op.drop_table("pipeline_runs")
