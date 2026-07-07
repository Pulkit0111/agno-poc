"""standup rounds + responses tables

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c1e3
Create Date: 2026-07-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5a7b9d1f2'
down_revision: Union[str, Sequence[str], None] = 'b2d4f6a8c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('standup_rounds',
    sa.Column('team', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('thread_ts', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('team', 'date')
    )
    op.create_table('standup_responses',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('team', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('yesterday', sa.Text(), nullable=True),
    sa.Column('today', sa.Text(), nullable=True),
    sa.Column('blockers', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_standup_responses', 'standup_responses', ['team', 'date', 'id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_standup_responses', table_name='standup_responses')
    op.drop_table('standup_responses')
    op.drop_table('standup_rounds')
