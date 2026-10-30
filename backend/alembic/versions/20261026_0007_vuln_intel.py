"""Normalized vulnerability intelligence tables (S3-1).

Revision ID: 20261026_0007
Revises: 20261026_0006
Create Date: 2026-10-26
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261026_0007"
down_revision = "20261026_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.vuln_intel import (
        VulnSource, Vulnerability, VulnAffected, ExploitSignal, VulnPatchMap,
    )  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[VulnSource.__table__, Vulnerability.__table__, VulnAffected.__table__,
                ExploitSignal.__table__, VulnPatchMap.__table__],
    )


def downgrade() -> None:
    for t in ("vuln_patch_map", "exploit_signals", "vuln_affected", "vulnerabilities", "vuln_sources"):
        op.drop_table(t)