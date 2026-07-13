"""action_items.source column

Revision ID: 0bbc20d4b859
Revises: c3e5a7b9d1f2
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0bbc20d4b859'
down_revision: Union[str, Sequence[str], None] = 'c3e5a7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('action_items', sa.Column('source', sa.Text(), nullable=False,
                                             server_default=sa.text("'user'")))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('action_items', 'source')
