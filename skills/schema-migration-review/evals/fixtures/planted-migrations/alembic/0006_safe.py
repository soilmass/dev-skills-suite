"""Safe Alembic revision: nullable add, concurrent index, real downgrade."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.add_column("orders", sa.Column("region", sa.String(8), nullable=True))
    with op.get_context().autocommit_block():
        op.create_index("ix_orders_region", "orders", ["region"], postgresql_concurrently=True)


def downgrade():
    op.drop_index("ix_orders_region", table_name="orders")
    op.drop_column("orders", "region")
