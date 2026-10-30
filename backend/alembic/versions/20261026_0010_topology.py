"""Topology service graph tables (S6).

Revision ID: 20261026_0010
Revises: 20261026_0009
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0010"
down_revision = "20261026_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.topology import ServiceNode, ServiceDependency  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[ServiceNode.__table__, ServiceDependency.__table__],
    )


def downgrade() -> None:
    op.drop_table("service_dependencies")
    op.drop_table("service_nodes")