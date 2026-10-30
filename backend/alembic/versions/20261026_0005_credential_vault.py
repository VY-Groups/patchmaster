"""Credential Vault table (S2-1).

Revision ID: 20261026_0005
Revises: 20261026_0004
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.vault import Credential  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[Credential.__table__],
    )


def downgrade() -> None:
    op.drop_table("credentials")