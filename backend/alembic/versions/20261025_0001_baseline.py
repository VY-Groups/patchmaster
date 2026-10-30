"""Baseline: the schema the ORM models declare.

Revision ID: 20261025_0001
Revises:
Create Date: 2026-10-25

First entry of the chain (plan.md S0-4). Fresh installs get the full model
schema here; databases that existed before alembic run it with checkfirst, so
it is a no-op for them before 20261025_0002 applies the converted dated SQL.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261025_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table, index and constraint the models declare."""
    from database import Base
    from models import db_models  # noqa: F401  (registers the metadata)

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Drop the model schema."""
    from database import Base
    from models import db_models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
