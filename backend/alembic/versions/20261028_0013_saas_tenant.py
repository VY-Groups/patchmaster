"""SaaS tenant isolation + Windows onboarding fields (SaaS requirements).

Revision ID: 20261028_0013
Revises: 20261026_0012
Create Date: 2026-10-28
"""

from alembic import op

from database import Base
from models import db_models  # noqa: F401

revision: str = "20261028_0013"
down_revision = "20261026_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from models.db_models.tenant import Tenant  # noqa: F401

    Base.metadata.create_all(
        bind=op.get_bind(),
        checkfirst=True,
        tables=[Tenant.__table__],
    )
    op.execute("ALTER TABLE hosts ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
    op.execute("ALTER TABLE hosts ADD COLUMN IF NOT EXISTS management_mode VARCHAR(20) DEFAULT 'agent'")
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
    op.execute("ALTER TABLE evidence_bundles ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE evidence_bundles DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE hosts DROP COLUMN IF EXISTS management_mode")
    op.execute("ALTER TABLE hosts DROP COLUMN IF EXISTS tenant_id")
    op.drop_table("tenants")