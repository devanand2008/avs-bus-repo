"""Explicit database selection. Never switch databases after writes or on failure."""
from sqlalchemy import create_engine, event, MetaData
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from fleet.config import settings

class Base(DeclarativeBase):
    metadata = MetaData(schema=settings.DATABASE_SCHEMA or None)

def selected_url():
    if settings.DATABASE_MODE == 'mysql':
        url = settings.MYSQL_DATABASE_URL
        if not url.startswith('mysql+pymysql://'):
            raise RuntimeError('Configure MYSQL_DATABASE_URL=mysql+pymysql://... for explicit MySQL mode.')
        return url
    if settings.DATABASE_MODE == 'test' and settings.ALLOW_TEST_SQLITE:
        return settings.DATABASE_URL or 'sqlite:///:memory:'
    url = settings.DATABASE_URL
    if not url.startswith(('postgresql://', 'postgresql+psycopg2://')):
        raise RuntimeError('Configure a Supabase Postgres DATABASE_URL, or explicitly select DATABASE_MODE=mysql. No automatic SQLite fallback.')
    if settings.ENVIRONMENT == 'production' and 'sslmode=' not in url:
        raise RuntimeError('Supabase production connections require sslmode=verify-full (or require).')
    return url

def make_engine(url):
    if url.startswith('sqlite'):
        from sqlalchemy.pool import StaticPool
        engine = create_engine(url, connect_args={'check_same_thread': False}, **({'poolclass': StaticPool} if ':memory:' in url else {}))
        @event.listens_for(engine, 'connect')
        def fk_on(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
        return engine
    if settings.SERVERLESS:
        from sqlalchemy.pool import NullPool
        result=create_engine(url, pool_pre_ping=True, poolclass=NullPool, connect_args={'connect_timeout': 8})
    else:
        result=create_engine(url, pool_pre_ping=True, pool_recycle=1200, pool_size=5, max_overflow=5, connect_args={'connect_timeout': 8})
    if settings.DATABASE_SCHEMA:
        import re
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',settings.DATABASE_SCHEMA):raise RuntimeError('Invalid private database schema.')
        if result.dialect.name!='postgresql':raise RuntimeError('Private schemas require PostgreSQL.')
        quoted=result.dialect.identifier_preparer.quote(settings.DATABASE_SCHEMA)
        @event.listens_for(result,'begin')
        def private_schema(connection):
            # Transaction-scoped, safe with Supavisor transaction pooling. Metadata
            # also qualifies ORM tables; raw SQL and Alembic stay in this schema.
            connection.exec_driver_sql(f'SET LOCAL search_path TO {quoted}')
    return result

missing_cloud_database = settings.SERVERLESS and not (settings.MYSQL_DATABASE_URL if settings.DATABASE_MODE=='mysql' else settings.DATABASE_URL)
engine = None if missing_cloud_database else make_engine(selected_url())
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    if engine is None:
        from fastapi import HTTPException
        raise HTTPException(503, 'Deployment awaits its dedicated database connection. Configure DATABASE_URL and apply migrations; no fallback database is used.')
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
