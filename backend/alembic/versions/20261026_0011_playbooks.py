"""Mitigation playbook table (S3-7).

Revision ID: 20261026_0011
Revises: 20261026_0010
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0011"
down_revision = "20261026_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.playbook import MitigationPlaybook  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[MitigationPlaybook.__table__],
    )


def downgrade() -> None:
    op.drop_table("mitigation_playbooks")