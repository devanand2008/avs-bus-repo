from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo
from math import isfinite
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, EmailStr

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    @field_validator('*', mode='after')
    @classmethod
    def aware_times(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None: raise ValueError('Timestamp must include timezone, e.g. +05:30.')
        return v

class VehicleInput(Input):
    bus_number: str = Field(min_length=1, max_length=40)
    registration: str = Field(min_length=3, max_length=50)
    make_model: str = Field(default='', max_length=100)
    status: Literal['active','maintenance','inactive'] = 'active'
    tank_capacity_l: Decimal = Field(gt=0, le=2000, decimal_places=3)
    safe_fill_l: Decimal = Field(gt=0, le=2000, decimal_places=3)
    operating_target_l: Decimal = Field(ge=0, le=2000, decimal_places=3)
    odometer_km: Decimal = Field(default=0, ge=0, le=99999999)
    depot: str = Field(default='Salem campus', max_length=100)
    @model_validator(mode='after')
    def limits(self):
        if not self.operating_target_l <= self.safe_fill_l <= self.tank_capacity_l:
            raise ValueError('Operating target ≤ safe fill limit ≤ physical capacity.')
        return self

class DriverInput(Input):
    employee_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=150)
    mobile: str | None = Field(default=None, max_length=30)
    licence_number: str | None = Field(default=None, max_length=60)
    licence_expiry: date | None = None
    active: bool = True

class RouteInput(Input):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=150)
    direction: str = Field(default='round trip', max_length=40)
    depot: str = Field(default='Salem campus', max_length=100)
    stops: list[str] = Field(default_factory=list, max_length=100)
    geometry: dict = Field(default_factory=dict)
    trip_km: Decimal = Field(gt=0, le=2000)
    scope: Literal['one_way','round_trip','full_day'] = 'round_trip'
    @field_validator('geometry')
    @classmethod
    def geometry_check(cls, v):
        if v:
            if v.get('type') != 'LineString' or not isinstance(v.get('coordinates'), list) or not 2 <= len(v['coordinates']) <= 10000: raise ValueError('Use GeoJSON LineString with 2–10,000 coordinates.')
            for p in v['coordinates']:
                if not isinstance(p, (list, tuple)) or len(p)!=2 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not isfinite(n) for n in p) or not (-180<=p[0]<=180 and -90<=p[1]<=90): raise ValueError('Invalid GeoJSON longitude/latitude.')
        return v

class AssignmentInput(Input):
    vehicle_id: str
    driver_id: str | None = None
    route_id: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    reason: str = Field(min_length=3)
    @model_validator(mode='after')
    def valid_interval(self):
        if self.ends_at and self.ends_at <= self.starts_at: raise ValueError('End must follow start.')
        if not self.driver_id and not self.route_id: raise ValueError('Select a driver or route.')
        return self

class DeviceInput(Input):
    vehicle_id: str
    provider: str = Field(min_length=1, max_length=50)
    device_id: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    ends_at: datetime | None = None
    cadence_seconds: int = Field(default=30, ge=1, le=3600)
    speed_unit: Literal['kmh','mph','mps'] = 'kmh'
    supports_ignition: bool = False
    supports_fuel: bool = False
    @model_validator(mode='after')
    def interval(self):
        if self.ends_at and self.ends_at <= self.starts_at: raise ValueError('End must follow start.')
        return self

class SurveyInput(Input):
    route_id: str
    date: date
    b1_km: Decimal = Field(gt=0, le=2000)
    b2_km: Decimal = Field(gt=0, le=2000)
    b3_km: Decimal = Field(gt=0, le=2000)
    scope: Literal['one_way','round_trip','full_day']
    readings: list[dict] = Field(default_factory=list, max_length=3)
    evidence_id: str | None = None

class MileageInput(Input):
    vehicle_id: str
    route_id: str | None = None
    kmpl: Decimal = Field(gt=0, le=50, decimal_places=4)
    effective_from: datetime
    effective_to: datetime | None = None
    includes_idling: bool = True
    idle_lph: Decimal = Field(default=0, ge=0, le=20)
    evidence_id: str | None = None
    reason: str = Field(min_length=3)
    @model_validator(mode='after')
    def interval(self):
        if self.effective_to and self.effective_to <= self.effective_from: raise ValueError('Invalid mileage interval.')
        if self.includes_idling and self.idle_lph: raise ValueError('Idling is already included in this mileage standard.')
        return self

class PlanInput(Input):
    vehicle_id: str
    route_id: str | None = None
    service_date: date
    trips: int = Field(default=2, ge=0, le=20)
    trip_km: Decimal = Field(ge=0, le=2000)
    scope: Literal['one_way','round_trip','full_day'] = 'round_trip'
    kind: Literal['service','holiday','extra','workshop','detour'] = 'service'
    reason: str = Field(min_length=3)
    service_windows: list[dict] = Field(default_factory=list, max_length=20)
    @model_validator(mode='after')
    def holiday(self):
        if self.kind == 'holiday' and self.trips: raise ValueError('Holiday must have zero planned trips.')
        windows=[]
        for window in self.service_windows:
            try:
                a=datetime.fromisoformat(window['start']);b=datetime.fromisoformat(window['end'])
                if a.tzinfo is None or b.tzinfo is None or b<=a:raise ValueError()
            except Exception:raise ValueError('Service windows require timezone-aware start/end timestamps with end after start.')
            if a.astimezone(ZoneInfo('Asia/Kolkata')).date()!=self.service_date or b.astimezone(ZoneInfo('Asia/Kolkata')).date()!=self.service_date:raise ValueError('Service windows must be within the IST service date; split midnight schedules into daily portions.')
            if any(a<y and b>x for x,y in windows):raise ValueError('Service windows cannot overlap.')
            windows.append((a,b))
        return self

class FuelInput(Input):
    vehicle_id: str
    occurred_at: datetime
    litres: Decimal = Field(gt=0, le=2000, decimal_places=3)
    price_per_l: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=4)
    supplier: str = Field(min_length=1, max_length=120)
    invoice: str = Field(min_length=1, max_length=120)
    pump_transaction: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)
    pre_stock_l: Decimal | None = Field(default=None, ge=0)
    post_stock_l: Decimal | None = Field(default=None, ge=0)
    stock_quality: Literal['measured','estimated','unknown'] = 'unknown'
    override_reason: str = ''
    evidence_id: str | None = None
    correction_of: str | None = None

class TankInput(Input):
    vehicle_id: str
    occurred_at: datetime
    litres: Decimal = Field(ge=0, le=2000, decimal_places=3)
    quality: Literal['measured','estimated']
    source: Literal['dip','sensor','manual_estimate']
    stable: bool = False
    calibration_id: str | None = None
    uncertainty_l: Decimal = Field(default=0, ge=0, le=200)
    evidence_id: str | None = None
    reason: str = Field(min_length=3)

class CalibrationInput(Input):
    vehicle_id: str
    effective_from: datetime
    curve: list[list[float]] = Field(min_length=2, max_length=1000)
    uncertainty_l: Decimal = Field(ge=0, le=100)
    stable_seconds: int = Field(default=120, ge=30, le=1800)
    @field_validator('curve')
    @classmethod
    def monotonic(cls, v):
        if any(len(p)!=2 or any(not isfinite(x) for x in p) for p in v) or any(v[i][0] <= v[i-1][0] or v[i][1] < v[i-1][1] for i in range(1,len(v))): raise ValueError('Calibration curve must contain finite values and increase monotonically.')
        return v

class TransferInput(Input):
    from_vehicle_id: str
    to_vehicle_id: str
    occurred_at: datetime
    litres: Decimal = Field(gt=0, le=2000)
    reason: str = Field(min_length=3)
    @model_validator(mode='after')
    def different(self):
        if self.from_vehicle_id == self.to_vehicle_id: raise ValueError('Transfer requires two different vehicles.')
        return self

class ManualTripInput(Input):
    vehicle_id: str
    starts_at: datetime
    ends_at: datetime
    distance_km: Decimal = Field(gt=0, le=3000)
    reason: str = Field(min_length=5)
    @model_validator(mode='after')
    def interval(self):
        if self.ends_at <= self.starts_at: raise ValueError('Trip end must follow start.')
        return self

class GPSInput(Input):
    provider: str = Field(min_length=1, max_length=50)
    device_id: str = Field(min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=120)
    fix_at: datetime
    lat: Decimal = Field(ge=-90, le=90, decimal_places=7)
    lon: Decimal = Field(ge=-180, le=180, decimal_places=7)
    speed: Decimal | None = Field(default=None, ge=0, le=1000)
    source_unit: Literal['kmh','mph','mps'] = 'kmh'
    ignition: bool | None = None
    accuracy_m: Decimal | None = Field(default=None, ge=0, le=99999)
    odometer_km: Decimal | None = Field(default=None, ge=0)
    raw: dict = Field(default_factory=dict)

class Decision(Input):
    version: int = Field(ge=1)
    reason: str = Field(min_length=3)

class CaseDecision(Decision):
    state: Literal['New','Acknowledged','Investigating','Explained','Confirmed discrepancy','Closed']
    approved_amount: Decimal | None = Field(default=None, ge=0, le=10000000)

class LoginInput(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    otp: str | None = None

class UserInput(Input):
    email: EmailStr
    name: str = Field(min_length=2, max_length=200)
    role: Literal['SYSTEM_ADMIN','DATA_ADMIN','CORRESPONDENT','FUELLER','TRANSPORT_VERIFIER','DRIVER','ACCOUNTS','AUDITOR']
    password: str = Field(min_length=12, max_length=128)
    driver_id: str | None = None

class CollegeInput(Input):
    name: str = Field(min_length=2, max_length=200)
    short_name: str = Field(min_length=1, max_length=50)
    week_start: int = Field(default=0, ge=0, le=6)
    primary_color: str = Field(default='#0e847d', pattern=r'^#[0-9a-fA-F]{6}$')
    logo_url: str | None = None
    report_fields: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    @field_validator('logo_url')
    @classmethod
    def safe_logo(cls,v):
        if v and not v.startswith('https://'): raise ValueError('Logo must use HTTPS.')
        return v
    @field_validator('rules')
    @classmethod
    def safe_rules(cls, v):
        allowed = {'residual_l','gps_gap_seconds','max_speed_kph','route_tolerance_m','park_drop_l','standard_change_pct','rule_version'}
        if set(v)-allowed: raise ValueError('Unknown rule setting.')
        for k in allowed-{'rule_version'}:
            if k in v:
                try: number = Decimal(str(v[k]))
                except (InvalidOperation, ValueError): raise ValueError('Rule thresholds must be numeric.')
                if not number.is_finite() or not 0 < number <= 10000: raise ValueError('Rule thresholds must be finite, positive and at most 10000.')
        return v

SCHEMAS = {'vehicles': VehicleInput, 'drivers': DriverInput, 'routes': RouteInput, 'assignments': AssignmentInput, 'devices': DeviceInput, 'surveys': SurveyInput, 'mileage': MileageInput, 'plans': PlanInput, 'tank-readings': TankInput, 'calibrations': CalibrationInput, 'transfers': TransferInput, 'manual-trips': ManualTripInput}
