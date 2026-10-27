"""Developer utility to freeze the initial DDL. Run only when creating a fresh baseline revision."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.autogenerate import produce_migrations,render_python_code
from fleet.db import Base
from fleet.models import DateTime
def render(kind,obj,context):
    if kind=='type' and isinstance(obj,DateTime):return 'sa.DateTime(timezone=True)'
    return False
with sa.create_engine('sqlite:///:memory:').connect() as conn:
    operations=produce_migrations(MigrationContext.configure(conn),Base.metadata).upgrade_ops
    code=render_python_code(operations,render_item=render)
tables=repr(sorted(Base.metadata.tables))
source='''"""Immutable initial College Fleet Command schema; legacy tables are untouched."""
from alembic import op
import sqlalchemy as sa
revision='0001_command'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
'''+code+f'''
    if connection.dialect.name=='postgresql':
        for name in {tables}:
            op.execute(f'ALTER TABLE "{{name}}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL ON "{{name}}" FROM PUBLIC')
            for role in ('anon','authenticated'):
                if connection.execute(sa.text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{{'role':role}}).scalar():
                    op.execute(f'REVOKE ALL ON "{{name}}" FROM "{{role}}"')

def downgrade():
    raise RuntimeError('Destructive downgrade disabled. Restore a backup into a separate database.')
'''
(root/'backend/alembic/versions/0001_command.py').write_text(source,encoding='utf-8')
print('Initial DDL frozen as explicit Alembic operations. No operational database changes made.')
