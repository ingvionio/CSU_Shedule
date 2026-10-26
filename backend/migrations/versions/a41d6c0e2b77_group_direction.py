"""group direction

Revision ID: a41d6c0e2b77
Revises: 7c2e5a9d4f10
Create Date: 2026-10-26 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.services.groups import direction_of


revision: str = 'a41d6c0e2b77'
down_revision: Union[str, None] = '7c2e5a9d4f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('direction', sa.String(length=8), nullable=True))
        batch_op.create_index(batch_op.f('ix_groups_direction'), ['direction'], unique=False)

    # Бэкфилл из названия — тем же правилом, что и при импорте.
    connection = op.get_bind()
    groups = sa.table('groups', sa.column('id', sa.Integer), sa.column('name', sa.String), sa.column('direction', sa.String))
    for group_id, name in connection.execute(sa.select(groups.c.id, groups.c.name)).all():
        connection.execute(groups.update().where(groups.c.id == group_id).values(direction=direction_of(name)))


def downgrade() -> None:
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_groups_direction'))
        batch_op.drop_column('direction')
