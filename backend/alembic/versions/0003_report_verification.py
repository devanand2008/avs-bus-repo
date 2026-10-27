"""Independent prepared, verified and approved report stages."""
from alembic import op
import sqlalchemy as sa
revision='0003_signoffs'
down_revision='0002_windows'
branch_labels=None
depends_on=None
def upgrade():
    names={c['name'] for c in sa.inspect(op.get_bind()).get_columns('cfc_reports')}
    if 'verified_by' not in names:
        op.add_column('cfc_reports',sa.Column('verified_by',sa.String(36),nullable=True))
        op.add_column('cfc_reports',sa.Column('verified_at',sa.DateTime(timezone=True),nullable=True))
        if op.get_bind().dialect.name!='sqlite':op.create_foreign_key('cfc_report_verifier','cfc_reports','cfc_users',['verified_by'],['id'])
def downgrade():raise RuntimeError('Restore a backup into a separate database instead of destructive downgrade.')
