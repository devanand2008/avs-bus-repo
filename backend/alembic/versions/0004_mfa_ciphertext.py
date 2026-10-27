"""Allow full encrypted TOTP ciphertext in strict SQL databases."""
from alembic import op
import sqlalchemy as sa
revision='0004_mfa'
down_revision='0003_signoffs'
branch_labels=None
depends_on=None
def upgrade():
    if op.get_bind().dialect.name!='sqlite':op.alter_column('cfc_users','mfa_secret',type_=sa.String(255),existing_type=sa.String(100),existing_nullable=True)
def downgrade():raise RuntimeError('Ciphertexts cannot be safely truncated. Restore a tested backup separately.')
