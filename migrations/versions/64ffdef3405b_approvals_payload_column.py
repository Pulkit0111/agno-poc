"""approvals.payload column

Revision ID: 64ffdef3405b
Revises: db8adee52d1d
Create Date: 2026-06-30 14:55:51.877550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64ffdef3405b'
down_revision: Union[str, Sequence[str], None] = 'db8adee52d1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Trimmed: autogenerate emitted spurious create_table ops for tables added to schema
    # after the baseline (settings, github_deliveries, reviewed_commits, review_traces).
    # Only the intended change — adding the payload column to approvals — is kept.
    op.add_column('approvals', sa.Column('payload', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('approvals', 'payload')
