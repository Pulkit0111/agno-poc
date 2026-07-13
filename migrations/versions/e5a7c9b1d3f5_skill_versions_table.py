"""skill_versions table

Revision ID: e5a7c9b1d3f5
Revises: f7c9e1a3b5d7
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f5'
down_revision: Union[str, Sequence[str], None] = 'f7c9e1a3b5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same gap as the todos/action_items migrations above: on a fresh DB init_schema()'s
    # idempotent create_all() at app startup already creates `skill_versions` (schema.py
    # carries the full table shape), so there is nothing for THIS migration to create.
    # Guarding keeps `alembic upgrade head` from failing on a table that isn't there yet.
    if sa.inspect(op.get_bind()).has_table('skill_versions'):
        return
    op.create_table(
        'skill_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('slug', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('author', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_skill_versions_slug', 'skill_versions', ['slug', 'id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if not sa.inspect(op.get_bind()).has_table('skill_versions'):
        return
    op.drop_index('idx_skill_versions_slug', table_name='skill_versions')
    op.drop_table('skill_versions')
