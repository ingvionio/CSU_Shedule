"""feedback

Revision ID: 7c2e5a9d4f10
Revises: 1393967e1a81
Create Date: 2026-10-24 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c2e5a9d4f10'
down_revision: Union[str, None] = '1393967e1a81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('feedback_recipients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('emails', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), nullable=False),
    sa.CheckConstraint("kind IN ('dev','methodist','deanery')", name='ck_feedback_recipients_kind'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('feedback_recipients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_recipients_kind'), ['kind'], unique=False)

    op.create_table('feedback_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('recipient_id', sa.Integer(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('author_name', sa.String(length=200), nullable=True),
    sa.Column('contact', sa.String(length=200), nullable=True),
    sa.Column('author_token_hash', sa.String(length=64), nullable=True),
    sa.Column('ip_hash', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('admin_note', sa.String(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('dev','methodist','deanery','unknown')", name='ck_feedback_messages_kind'),
    sa.CheckConstraint("status IN ('new','in_progress','answered','archived')", name='ck_feedback_messages_status'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recipient_id'], ['feedback_recipients.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('feedback_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_messages_author_token_hash'), ['author_token_hash'], unique=False)
        batch_op.create_index('ix_feedback_messages_folder', ['kind', 'status'], unique=False)

    op.create_table('feedback_replies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('author_kind', sa.String(length=16), nullable=False),
    sa.Column('author_name', sa.String(length=200), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("author_kind IN ('staff','student')", name='ck_feedback_replies_author_kind'),
    sa.ForeignKeyConstraint(['message_id'], ['feedback_messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('feedback_replies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_replies_message_id'), ['message_id'], unique=False)

    op.create_table('email_outbox',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=True),
    sa.Column('to_address', sa.String(length=200), nullable=False),
    sa.Column('reply_to', sa.String(length=200), nullable=True),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.SmallInteger(), nullable=False),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending','sent','failed','skipped')", name='ck_email_outbox_status'),
    sa.ForeignKeyConstraint(['message_id'], ['feedback_messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('email_outbox', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_outbox_message_id'), ['message_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_email_outbox_status'), ['status'], unique=False)


def downgrade() -> None:
    op.drop_table('email_outbox')
    op.drop_table('feedback_replies')
    op.drop_table('feedback_messages')
    op.drop_table('feedback_recipients')
