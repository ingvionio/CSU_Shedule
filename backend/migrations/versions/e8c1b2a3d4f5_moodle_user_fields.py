"""moodle user fields

Revision ID: e8c1b2a3d4f5
Revises: f1c3a5d7e902
Create Date: 2026-11-04 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8c1b2a3d4f5'
down_revision: Union[str, None] = 'f1c3a5d7e902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('moodle_username', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('moodle_encrypted_password', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('moodle_session_cookie', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('moodle_sesskey', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('moodle_session_expires_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('moodle_auth_error', sa.Boolean(), server_default='false', nullable=False))
        
        # Индексы Moodle
        batch_op.create_index(batch_op.f('ix_users_moodle_id'), ['moodle_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_moodle_username'), ['moodle_username'], unique=True)
        
        # Смягчение уникальности device_key_hash для поддержки множества устройств у одного студента
        try:
            batch_op.drop_constraint('users_device_key_hash_key', type_='unique')
        except Exception:
            pass
        batch_op.create_index(batch_op.f('ix_users_device_key_hash'), ['device_key_hash'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_device_key_hash'))
        batch_op.drop_index(batch_op.f('ix_users_moodle_username'))
        batch_op.drop_index(batch_op.f('ix_users_moodle_id'))
        batch_op.drop_column('moodle_auth_error')
        batch_op.drop_column('moodle_session_expires_at')
        batch_op.drop_column('moodle_sesskey')
        batch_op.drop_column('moodle_session_cookie')
        batch_op.drop_column('moodle_encrypted_password')
        batch_op.drop_column('moodle_username')
        batch_op.create_unique_constraint('users_device_key_hash_key', ['device_key_hash'])
