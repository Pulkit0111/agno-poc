"""todos table

Revision ID: f7c9e1a3b5d7
Revises: 0bbc20d4b859
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7c9e1a3b5d7'
down_revision: Union[str, Sequence[str], None] = '0bbc20d4b859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same gap as the action_items.source migration above: on a fresh DB init_schema()'s
    # idempotent create_all() at app startup already creates `todos` (schema.py carries the
    # full table shape), so there is nothing for THIS migration to create. Guarding keeps
    # `alembic upgrade head` from trying — and failing on a table that isn't there yet — on
    # a DB where init_schema hasn't run.
    if sa.inspect(op.get_bind()).has_table('todos'):
        return
    op.create_table(
        'todos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('done', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('updated', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_todos_user', 'todos', ['user_id', 'done', 'id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if not sa.inspect(op.get_bind()).has_table('todos'):
        return
    op.drop_index('idx_todos_user', table_name='todos')
    op.drop_table('todos')
