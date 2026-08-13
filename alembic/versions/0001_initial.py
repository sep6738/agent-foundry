"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-10
"""

from agent_backend.app.storage.models import Base
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
