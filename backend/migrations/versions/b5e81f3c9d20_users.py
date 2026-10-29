"""users

Revision ID: b5e81f3c9d20
Revises: a41d6c0e2b77
Create Date: 2026-10-26 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5e81f3c9d20'
down_revision: Union[str, None] = 'a41d6c0e2b77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('device_key_hash', sa.String(length=64), nullable=True),
    sa.Column('moodle_id', sa.String(length=64), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('student')", name='ck_users_role'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_key_hash')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_group_id'), ['group_id'], unique=False)


def downgrade() -> None:
    op.drop_table('users')
