"""Relay + site + network tables (S2-5, S2-6).

Revision ID: 20261026_0006
Revises: 20261026_0005
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0006"
down_revision = "20261026_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.relay import Relay, Site, Network  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[Relay.__table__, Site.__table__, Network.__table__],
    )


def downgrade() -> None:
    op.drop_table("networks")
    op.drop_table("sites")
    op.drop_table("relays")