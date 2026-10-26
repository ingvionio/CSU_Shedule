"""messages

Revision ID: c9a3d27e1f44
Revises: b5e81f3c9d20
Create Date: 2026-10-26 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9a3d27e1f44'
down_revision: Union[str, None] = 'b5e81f3c9d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('importance', sa.String(length=8), nullable=False),
    sa.Column('target', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_reminded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("importance IN ('low','normal','high')", name='ck_messages_importance'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_messages_sent_at'), ['sent_at'], unique=False)

    op.create_table('message_recipients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id', 'user_id', name='uq_message_recipients_message_user')
    )
    with op.batch_alter_table('message_recipients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_message_recipients_message_id'), ['message_id'], unique=False)
        batch_op.create_index('ix_message_recipients_user_read', ['user_id', 'read_at'], unique=False)


def downgrade() -> None:
    op.drop_table('message_recipients')
    op.drop_table('messages')
