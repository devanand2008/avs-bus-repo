from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    DATABASE_URL: str = ''
    MYSQL_DATABASE_URL: str = ''
    DATABASE_MODE: str = 'supabase'
    DATABASE_SCHEMA: str = ''
    ALLOW_TEST_SQLITE: bool = False
    ENVIRONMENT: str = 'development'
    SECRET_KEY: str = ''
    COLLEGE_NAME: str = 'AVS Engineering College'
    COLLEGE_SHORT_NAME: str = 'AVSEC'
    CORS_ORIGINS: str = 'http://localhost:3000,http://127.0.0.1:3000'
    COOKIE_SECURE: bool = False
    SESSION_HOURS: int = 8
    REDIS_URL: str = 'redis://localhost:6379/0'
    PRIVATE_STORAGE_DIR: str = str(ROOT / 'private-evidence')
    S3_BUCKET: str = ''
    S3_ENDPOINT_URL: str = ''
    S3_ACCESS_KEY: str = ''
    S3_SECRET_KEY: str = ''
    S3_REGION: str = 'ap-south-1'
    GPS_PROVIDER_URL: str = ''
    GPS_PROVIDER_TOKEN: str = ''
    GPS_WEBHOOK_SECRET: str = ''
    MAP_STYLE_URL: str = 'https://demotiles.maplibre.org/style.json'
    MAP_ATTRIBUTION: str = '© OpenStreetMap contributors'
    BOOTSTRAP_EMAIL: str = ''
    BOOTSTRAP_PASSWORD: str = ''
    MFA_REQUIRED: bool = False
    MFA_ENABLED: bool = True
    SERVERLESS: bool = False
    CRON_SECRET: str = ''
    EVIDENCE_STORAGE: str = 'local'

settings = Settings()
