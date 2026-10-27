"""Explicit GPS coverage denominator from approved service windows."""
from alembic import op
import sqlalchemy as sa
revision='0002_windows'
down_revision='0001_command'
branch_labels=None
depends_on=None
def upgrade():
    # The first baseline is metadata-based; support fresh and already-created databases safely.
    if 'service_windows' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('cfc_plans')}:
        op.add_column('cfc_plans',sa.Column('service_windows',sa.JSON(),nullable=True))
        op.execute(sa.text("UPDATE cfc_plans SET service_windows='[]' WHERE service_windows IS NULL"))
def downgrade():raise RuntimeError('Restore a backup into a separate database instead of destructive downgrades.')
