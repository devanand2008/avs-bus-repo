import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from fleet.config import settings
from fleet.db import get_db
from fleet.models import User, Session as LoginSession, Assignment, now

ROLES = {'SYSTEM_ADMIN', 'DATA_ADMIN', 'CORRESPONDENT', 'FUELLER', 'TRANSPORT_VERIFIER', 'DRIVER', 'ACCOUNTS', 'AUDITOR'}
ADMIN = {'SYSTEM_ADMIN', 'DATA_ADMIN'}
APPROVERS = {'CORRESPONDENT', 'TRANSPORT_VERIFIER'}
PRIVILEGED = ADMIN | APPROVERS | {'ACCOUNTS'}

def aware(d):
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)

def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()
    return f'pbkdf2_sha256$310000${salt}${digest}'

def verify_password(password, stored):
    try:
        _, rounds, salt, expected = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def secret_box():
    if len(settings.SECRET_KEY) < 32:
        raise HTTPException(503, 'Set a random SECRET_KEY of at least 32 characters.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()))

def encrypt_secret(value): return secret_box().encrypt(value.encode()).decode()
def decrypt_secret(value): return secret_box().decrypt(value.encode()).decode()

def user_view(user):
    return {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role, 'driver_id': user.driver_id, 'mfa_enabled': user.mfa_enabled}

def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get('cfc_session')
    header = request.headers.get('authorization', '')
    if header.startswith('Bearer '): token = header[7:]
    if not token: raise HTTPException(401, 'Sign in to College Fleet Command.')
    session = db.query(LoginSession).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest(), archived=False).first()
    if not session or aware(session.expires_at) <= now(): raise HTTPException(401, 'Session expired. Sign in again.')
    user = db.get(User, session.user_id)
    if not user or user.archived: raise HTTPException(401, 'Account disabled.')
    if settings.MFA_ENABLED and settings.MFA_REQUIRED and user.role in PRIVILEGED and not user.mfa_enabled and not request.url.path.startswith('/api/v2/auth/'):
        raise HTTPException(403, 'Enrol MFA before accessing operational records.')
    return user

def require(user, allowed):
    if user.role not in allowed: raise HTTPException(403, 'Your role does not permit this action.')

def independent(user, creator):
    if user.id == creator: raise HTTPException(403, 'Independent review required: you cannot approve your own record.')

def vehicle_scope(db, user):
    if user.role != 'DRIVER': return None
    return {a.vehicle_id for a in db.query(Assignment).filter(Assignment.driver_id == user.driver_id).all()} if user.driver_id else set()

def check_vehicle(db, user, vehicle_id):
    scope = vehicle_scope(db, user)
    if scope is not None and vehicle_id not in scope: raise HTTPException(404, 'Vehicle not found in your access scope.')

def check_period(db,user,vehicle_id,start,end):
    check_vehicle(db,user,vehicle_id)
    if user.role!='DRIVER':return
    intervals=db.query(Assignment).filter(Assignment.vehicle_id==vehicle_id,Assignment.driver_id==user.driver_id,Assignment.starts_at<=start).all()
    if not any(aware(a.starts_at)<=start and (not a.ends_at or aware(a.ends_at)>=end) for a in intervals):raise HTTPException(403,'Select dates entirely within your historical bus assignment.')

def create_session(db, user, response, native=False):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now() + timedelta(hours=settings.SESSION_HOURS)))
    db.commit()
    response.set_cookie('cfc_session', token, httponly=True, secure=settings.COOKIE_SECURE, samesite='lax', max_age=settings.SESSION_HOURS*3600, path='/')
    return {'user': user_view(user), **({'access_token': token} if native else {})}
