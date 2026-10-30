"""Compliance control/finding tables (S5).

Revision ID: 20261026_0009
Revises: 20261026_0008
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0009"
down_revision = "20261026_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.compliance import ComplianceControl, ComplianceFinding  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[ComplianceControl.__table__, ComplianceFinding.__table__],
    )


def downgrade() -> None:
    op.drop_table("compliance_findings")
    op.drop_table("compliance_controls")