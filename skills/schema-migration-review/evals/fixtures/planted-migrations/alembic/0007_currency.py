"""Planted Alembic revision: every risky operation in one file."""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.execute("UPDATE orders SET currency = 'USD'")
    op.create_index("ix_orders_customer", "orders", ["customer_id"])
    op.alter_column("orders", "total", type_=sa.Integer())
    op.drop_column("orders", "notes")
    op.add_column("orders", sa.Column("currency", sa.String(3), nullable=False))


def downgrade():
    pass
