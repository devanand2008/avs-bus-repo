"""Private durable evidence content for serverless deployments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMBLOB

revision = '0005_evidence'
down_revision = '0004_mfa'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('cfc_evidence_content',
        sa.Column('evidence_id', sa.String(36), sa.ForeignKey('cfc_evidence.id'), primary_key=True),
        sa.Column('content', sa.LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'), nullable=False))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE cfc_evidence_content ENABLE ROW LEVEL SECURITY')
        op.execute('REVOKE ALL ON cfc_evidence_content FROM PUBLIC')

def downgrade():
    raise RuntimeError('Evidence is retained. Restore a verified backup instead of dropping private content.')
