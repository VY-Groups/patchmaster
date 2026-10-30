"""Add 'held' and 'rolled_back' values to the ring_rollout_status enum.

Revision ID: 20261026_0003
Revises: 20261025_0002
Create Date: 2026-10-26

S1-2 (Proof Loop decision engine) needs 'held' and 'rolled_back' as
RingRolloutRun statuses. Fresh installs get them via create_all; existing
databases need the enum values added explicitly.
"""

from alembic import op

revision: str = "20261026_0003"
down_revision = "20261025_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE ringrolloutstatus ADD VALUE IF NOT EXISTS 'held'")
    op.execute("ALTER TYPE ringrolloutstatus ADD VALUE IF NOT EXISTS 'rolled_back'")


def downgrade() -> None:
    # Removing enum values is not supported without recreating the type.
    pass