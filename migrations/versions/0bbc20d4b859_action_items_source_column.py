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
    # Pre-existing gap: the action_items table itself postdates the Alembic baseline
    # (db8adee52d1d) and no migration ever created it — every real deployment gets it from
    # init_schema()'s idempotent create_all() at app startup. On a DB where init_schema
    # hasn't run yet there is nothing to alter, and nothing to create here either:
    # init_schema owns table creation and will create action_items WITH the source column
    # (schema.py already carries it). Guarding keeps `alembic upgrade head` from crashing
    # on such a DB.
    if not sa.inspect(op.get_bind()).has_table('action_items'):
        return
    op.add_column('action_items', sa.Column('source', sa.Text(), nullable=False,
                                             server_default=sa.text("'user'")))


def downgrade() -> None:
    """Downgrade schema."""
    if not sa.inspect(op.get_bind()).has_table('action_items'):
        return
    op.drop_column('action_items', 'source')
