"""Evidence Ledger tables (S1-5).

Revision ID: 20261026_0004
Revises: 20261026_0003
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401  registers metadata

revision: str = "20261026_0004"
down_revision = "20261026_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.evidence import EvidenceBundle, EvidenceItem  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[EvidenceBundle.__table__, EvidenceItem.__table__],
    )


def downgrade() -> None:
    op.drop_table("evidence_items")
    op.drop_table("evidence_bundles")