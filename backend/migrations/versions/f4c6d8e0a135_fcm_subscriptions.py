"""Подписки Android FCM рядом с существующими Web Push."""

from alembic import op
import sqlalchemy as sa

revision: str = "f4c6d8e0a135"
down_revision: str = "f3b5c7d9e024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("push_subscriptions") as batch:
        batch.add_column(sa.Column("platform", sa.String(8), server_default="web", nullable=False))
        batch.alter_column("p256dh", existing_type=sa.String(200), nullable=True)
        batch.alter_column("auth", existing_type=sa.String(100), nullable=True)
        batch.create_check_constraint("ck_push_subscriptions_platform", "platform IN ('web','fcm')")


def downgrade() -> None:
    # Старый контракт не умеет FCM; историю доставок оставляем без подписки.
    op.execute("UPDATE push_deliveries SET subscription_id=NULL WHERE subscription_id IN (SELECT id FROM push_subscriptions WHERE platform='fcm')")
    op.execute("DELETE FROM push_subscriptions WHERE platform='fcm'")
    with op.batch_alter_table("push_subscriptions") as batch:
        batch.drop_constraint("ck_push_subscriptions_platform", type_="check")
        batch.drop_column("platform")
        batch.alter_column("p256dh", existing_type=sa.String(200), nullable=False)
        batch.alter_column("auth", existing_type=sa.String(100), nullable=False)
