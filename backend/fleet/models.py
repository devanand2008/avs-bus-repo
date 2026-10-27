"""UUID identity, decimal quantities, effective history and append-only operational records."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Date, DateTime as SADateTime, Numeric, Integer, Boolean, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index, LargeBinary
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column
from fleet.db import Base

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)

class DateTime(TypeDecorator):
    """UTC everywhere, including MySQL/SQLite which discard timezone information."""
    impl = SADateTime
    cache_ok = True
    def process_bind_param(self,value,dialect):
        if value is None:return None
        value=value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value if dialect.name=='postgresql' else value.replace(tzinfo=None)
    def process_result_value(self,value,dialect):
        if value is None:return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)

class College(Record, Base):
    __tablename__ = 'cfc_college'
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(50), default='AVSEC')
    timezone: Mapped[str] = mapped_column(String(50), default='Asia/Kolkata')
    week_start: Mapped[int] = mapped_column(Integer, default=0)
    primary_color: Mapped[str] = mapped_column(String(10), default='#0e847d')
    logo_url: Mapped[str | None] = mapped_column(String(500))
    report_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    rules: Mapped[dict] = mapped_column(JSON, default=lambda: {'residual_l': '10', 'gps_gap_seconds': 300, 'max_speed_kph': 120, 'route_tolerance_m': 500, 'rule_version': '1.0'})

class User(Record, Base):
    __tablename__ = 'cfc_users'
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(255))
    driver_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('cfc_drivers.id'))
    mfa_secret: Mapped[str | None] = mapped_column(String(255))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Session(Record, Base):
    __tablename__ = 'cfc_sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Vehicle(Record, Base):
    __tablename__ = 'cfc_vehicles'
    bus_number: Mapped[str] = mapped_column(String(40), unique=True)
    registration: Mapped[str] = mapped_column(String(50), unique=True)
    make_model: Mapped[str] = mapped_column(String(100), default='')
    status: Mapped[str] = mapped_column(String(20), default='active')
    tank_capacity_l: Mapped[object] = mapped_column(Numeric(12,3))
    safe_fill_l: Mapped[object] = mapped_column(Numeric(12,3))
    operating_target_l: Mapped[object] = mapped_column(Numeric(12,3))
    odometer_km: Mapped[object] = mapped_column(Numeric(14,3), default=0)
    depot: Mapped[str] = mapped_column(String(100), default='Salem campus')
    __table_args__ = (CheckConstraint('tank_capacity_l > 0 AND safe_fill_l > 0 AND safe_fill_l <= tank_capacity_l AND operating_target_l >= 0 AND operating_target_l <= safe_fill_l', name='cfc_valid_tank'),)

class Driver(Record, Base):
    __tablename__ = 'cfc_drivers'
    employee_id: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    mobile: Mapped[str | None] = mapped_column(String(30))
    licence_number: Mapped[str | None] = mapped_column(String(60))
    licence_expiry: Mapped[object | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Route(Record, Base):
    __tablename__ = 'cfc_routes'
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    direction: Mapped[str] = mapped_column(String(40), default='round trip')
    depot: Mapped[str] = mapped_column(String(100), default='Salem campus')
    stops: Mapped[list] = mapped_column(JSON, default=list)
    geometry: Mapped[dict] = mapped_column(JSON, default=dict)
    trip_km: Mapped[object] = mapped_column(Numeric(12,3))
    scope: Mapped[str] = mapped_column(String(40), default='round_trip')
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))

class Assignment(Record, Base):
    __tablename__ = 'cfc_assignments'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_drivers.id'))
    route_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_routes.id'))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint('ends_at IS NULL OR ends_at > starts_at', name='cfc_assignment_interval'),)

class DeviceMapping(Record, Base):
    __tablename__ = 'cfc_device_mappings'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cadence_seconds: Mapped[int] = mapped_column(Integer, default=30)
    speed_unit: Mapped[str] = mapped_column(String(10), default='kmh')
    supports_ignition: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_fuel: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health: Mapped[str] = mapped_column(String(30), default='unknown')

class Evidence(Record, Base):
    __tablename__ = 'cfc_evidence'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(150))

class EvidenceContent(Base):
    """Private transactional evidence bytes for deployments without an object store."""
    __tablename__ = 'cfc_evidence_content'
    evidence_id: Mapped[str] = mapped_column(ForeignKey('cfc_evidence.id'), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), 'mysql'))

class Survey(Record, Base):
    __tablename__ = 'cfc_surveys'
    route_id: Mapped[str] = mapped_column(ForeignKey('cfc_routes.id'), index=True)
    date: Mapped[object] = mapped_column(Date)
    b1_km: Mapped[object] = mapped_column(Numeric(12,3))
    b2_km: Mapped[object] = mapped_column(Numeric(12,3))
    b3_km: Mapped[object] = mapped_column(Numeric(12,3))
    scope: Mapped[str] = mapped_column(String(40))
    readings: Mapped[list] = mapped_column(JSON, default=list)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_evidence.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))

class Mileage(Record, Base):
    __tablename__ = 'cfc_mileage'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_routes.id'))
    kmpl: Mapped[object] = mapped_column(Numeric(9,4))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    includes_idling: Mapped[bool] = mapped_column(Boolean, default=True)
    idle_lph: Mapped[object] = mapped_column(Numeric(9,4), default=0)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_evidence.id'))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    __table_args__ = (CheckConstraint('kmpl > 0', name='cfc_positive_mileage'),)

class PlannedTrip(Record, Base):
    __tablename__ = 'cfc_plans'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_routes.id'))
    service_date: Mapped[object] = mapped_column(Date, index=True)
    trips: Mapped[int] = mapped_column(Integer, default=2)
    trip_km: Mapped[object] = mapped_column(Numeric(12,3))
    scope: Mapped[str] = mapped_column(String(40), default='round_trip')
    kind: Mapped[str] = mapped_column(String(30), default='service')
    reason: Mapped[str] = mapped_column(Text, default='')
    service_windows: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))

class GPSPoint(Record, Base):
    __tablename__ = 'cfc_gps_points'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    provider: Mapped[str] = mapped_column(String(50))
    device_id: Mapped[str] = mapped_column(String(100))
    event_id: Mapped[str] = mapped_column(String(120))
    fix_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lat: Mapped[object] = mapped_column(Numeric(11,7))
    lon: Mapped[object] = mapped_column(Numeric(11,7))
    speed: Mapped[object | None] = mapped_column(Numeric(10,3))
    source_unit: Mapped[str] = mapped_column(String(10), default='kmh')
    speed_kph: Mapped[object | None] = mapped_column(Numeric(10,3))
    ignition: Mapped[bool | None] = mapped_column(Boolean)
    accuracy_m: Mapped[object | None] = mapped_column(Numeric(10,2))
    odometer_km: Mapped[object | None] = mapped_column(Numeric(14,3))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[str] = mapped_column(String(40), default='unprocessed')
    __table_args__ = (UniqueConstraint('provider', 'device_id', 'event_id', name='cfc_gps_dedup'), Index('cfc_gps_vehicle_time', 'vehicle_id', 'fix_at'))

class Trip(Record, Base):
    __tablename__ = 'cfc_trips'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(40))
    distance_km: Mapped[object] = mapped_column(Numeric(14,5))
    driver_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_drivers.id'))
    reason: Mapped[str] = mapped_column(Text, default='')
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    created_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))

class FuelEvent(Record, Base):
    __tablename__ = 'cfc_fuel'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    litres: Mapped[object] = mapped_column(Numeric(12,3))
    price_per_l: Mapped[object | None] = mapped_column(Numeric(12,4))
    price_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    supplier: Mapped[str] = mapped_column(String(120))
    invoice: Mapped[str] = mapped_column(String(120))
    pump_transaction: Mapped[str | None] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    pre_stock_l: Mapped[object | None] = mapped_column(Numeric(12,3))
    post_stock_l: Mapped[object | None] = mapped_column(Numeric(12,3))
    stock_quality: Mapped[str] = mapped_column(String(20), default='unknown')
    override_reason: Mapped[str] = mapped_column(Text, default='')
    authorised_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_evidence.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    reversed_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    correction_of: Mapped[str | None] = mapped_column(ForeignKey('cfc_fuel.id'))
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('supplier','invoice', name='cfc_invoice_unique'), CheckConstraint('litres > 0', name='cfc_positive_fill'), Index('cfc_fuel_vehicle_time', 'vehicle_id','occurred_at'))

class Calibration(Record, Base):
    __tablename__ = 'cfc_calibrations'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    curve: Mapped[list] = mapped_column(JSON)
    uncertainty_l: Mapped[object] = mapped_column(Numeric(10,3))
    stable_seconds: Mapped[int] = mapped_column(Integer, default=120)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))

class TankReading(Record, Base):
    __tablename__ = 'cfc_tank_readings'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    litres: Mapped[object] = mapped_column(Numeric(12,3))
    quality: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30))
    stable: Mapped[bool] = mapped_column(Boolean, default=False)
    calibration_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_calibrations.id'))
    uncertainty_l: Mapped[object] = mapped_column(Numeric(10,3), default=0)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_evidence.id'))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    __table_args__ = (Index('cfc_stock_vehicle_time','vehicle_id','occurred_at'), CheckConstraint('litres >= 0', name='cfc_nonnegative_stock'))

class Transfer(Record, Base):
    __tablename__ = 'cfc_transfers'
    from_vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    to_vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    litres: Mapped[object] = mapped_column(Numeric(12,3))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))

class DailySnapshot(Record, Base):
    __tablename__ = 'cfc_daily'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'))
    service_date: Mapped[object] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    calculation_version: Mapped[str] = mapped_column(String(30))
    input_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('vehicle_id','service_date', name='cfc_daily_unique'),)

class Case(Record, Base):
    __tablename__ = 'cfc_cases'
    vehicle_id: Mapped[str] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    rule: Mapped[str] = mapped_column(String(60))
    rule_version: Mapped[str] = mapped_column(String(30), default='1.0')
    state: Mapped[str] = mapped_column(String(30), default='New')
    severity: Mapped[str] = mapped_column(String(20), default='review')
    explanation: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str | None] = mapped_column(String(150), unique=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    decision: Mapped[str | None] = mapped_column(Text)
    approved_amount: Mapped[object | None] = mapped_column(Numeric(14,2))
    financial_approved_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    invoice_matched_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))

class Approval(Record, Base):
    __tablename__ = 'cfc_approvals'
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)

class Report(Record, Base):
    __tablename__ = 'cfc_reports'
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_vehicles.id'))
    kind: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[object] = mapped_column(Date)
    end_date: Mapped[object] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_reports.id'))
    status: Mapped[str] = mapped_column(String(30), default='frozen_provisional')
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(ForeignKey('cfc_users.id'))
    verified_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_revision: Mapped[bool] = mapped_column(Boolean, default=False)

class Audit(Record, Base):
    __tablename__ = 'cfc_audit'
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_users.id'))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey('cfc_vehicles.id'), index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
