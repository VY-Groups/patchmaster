"""Policy templates, install-after/expiry, draft/publish, auto-deploy rules, decline (P1).

Revision ID: 20261026_0012
Revises: 20261026_0011
Create Date: 2026-10-26
"""

from alembic import op

revision: str = "20261026_0012"
down_revision = "20261026_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BulkPatchJob: install-after / expiry / deploy status
    op.execute("ALTER TABLE bulk_patch_jobs ADD COLUMN IF NOT EXISTS install_after TIMESTAMP")
    op.execute("ALTER TABLE bulk_patch_jobs ADD COLUMN IF NOT EXISTS expiry TIMESTAMP")
    op.execute("ALTER TABLE bulk_patch_jobs ADD COLUMN IF NOT EXISTS deploy_status VARCHAR(20) DEFAULT 'draft'")
    # Auto-deploy rules table
    op.execute("""
        CREATE TABLE IF NOT EXISTS auto_deploy_rules (
            id SERIAL PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            categories JSON DEFAULT '[]',
            severities JSON DEFAULT '[]',
            os_platforms JSON DEFAULT '[]',
            include_apps JSON DEFAULT '[]',
            exclude_apps JSON DEFAULT '[]',
            remote_offices JSON DEFAULT '[]',
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Declined patches
    op.execute("""
        CREATE TABLE IF NOT EXISTS declined_patches (
            id SERIAL PRIMARY KEY,
            patch_id VARCHAR(100) NOT NULL,
            reason TEXT DEFAULT '',
            declined_by VARCHAR(100) DEFAULT '',
            declined_at TIMESTAMP DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS declined_patches")
    op.execute("DROP TABLE IF EXISTS auto_deploy_rules")
    op.execute("ALTER TABLE bulk_patch_jobs DROP COLUMN IF EXISTS deploy_status")
    op.execute("ALTER TABLE bulk_patch_jobs DROP COLUMN IF EXISTS expiry")
    op.execute("ALTER TABLE bulk_patch_jobs DROP COLUMN IF EXISTS install_after")