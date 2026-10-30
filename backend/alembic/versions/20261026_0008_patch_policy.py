"""Structured patch policy table (S4-1).

Revision ID: 20261026_0008
Revises: 20261026_0007
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0008"
down_revision = "20261026_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.patch_policy import PatchPolicy  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[PatchPolicy.__table__],
    )


def downgrade() -> None:
    op.drop_table("patch_policies")