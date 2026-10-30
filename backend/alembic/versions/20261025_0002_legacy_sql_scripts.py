"""Convert the dated backend/migrations/*.sql scripts into the chain.

Revision ID: 20261025_0002
Revises: 20261025_0001
Create Date: 2026-10-25

These scripts predate alembic and were applied by hand with ``psql -f``
(docs/internal/PRODUCTION_HARDENING_RUNBOOK.md). They now run here, in
filename (date) order, on both paths: a fresh install and an existing
database that already ran them manually, which is why every statement in
them is idempotent.
"""

from pathlib import Path

from alembic import op

from schema_migrations import split_sql_statements

# revision identifiers, used by Alembic.
revision: str = "20261025_0002"
down_revision = "20261025_0001"
branch_labels = None
depends_on = None

# alembic/versions/<file> -> backend/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def upgrade() -> None:
    """Run every dated script in date order."""
    for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
        for statement in split_sql_statements(script.read_text(encoding="utf-8")):
            op.execute(statement)


def downgrade() -> None:
    """No-op: the scripts were one-way under the manual process they replace.

    shortcut: duplicate-host DELETEs and constraint swaps are not reversible
    retroactively; from here on, reversible or data-transforming changes ship
    as their own revision with a real downgrade.
    """
    pass
