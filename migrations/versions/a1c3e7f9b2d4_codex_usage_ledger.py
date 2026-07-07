"""codex usage ledger

Revision ID: a1c3e7f9b2d4
Revises: ff2fba0db239
Create Date: 2026-07-07 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3e7f9b2d4'
down_revision: Union[str, Sequence[str], None] = 'ff2fba0db239'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('codex_usage',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Text(), nullable=True),
    sa.Column('model_id', sa.Text(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False, server_default=sa.text('0')),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_codex_usage_created', 'codex_usage', ['created'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_codex_usage_created', table_name='codex_usage')
    op.drop_table('codex_usage')
