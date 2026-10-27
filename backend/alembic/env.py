from logging.config import fileConfig
from alembic import context
from fleet.db import Base, engine, selected_url
from fleet.config import settings
import fleet.models
config=context.config
if config.config_file_name: fileConfig(config.config_file_name)
target_metadata=Base.metadata
if context.is_offline_mode():
    context.configure(url=selected_url(),target_metadata=target_metadata,literal_binds=True,compare_type=True,version_table_schema=settings.DATABASE_SCHEMA or None)
    with context.begin_transaction():context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True,version_table_schema=settings.DATABASE_SCHEMA or None)
        with context.begin_transaction():context.run_migrations()
