from fleet.config import settings
from fleet.models import User
from fleet.auth import encrypt_secret
from test_workflows import request


def test_disabled_mfa_allows_password_login_for_enrolled_user(env,monkeypatch):
    monkeypatch.setattr(settings,'MFA_ENABLED',False)
    monkeypatch.setattr(settings,'MFA_REQUIRED',True)
    with env['db']() as db:
        user=db.get(User,env['users']['SYSTEM_ADMIN'])
        user.mfa_enabled=True;user.mfa_secret=encrypt_secret('JBSWY3DPEHPK3PXP')
        db.commit()
    response=env['client'].post('/api/v2/auth/login',json={'email':'system_admin@example.com','password':'test-password-123'})
    assert response.status_code==200
    assert request(env,'GET','/dashboard?start=2026-09-01&end=2026-10-01').status_code==200
    config=request(env,'GET','/public/config').json()
    assert config['mfa_available'] is False and config['mfa_required'] is False


def test_disabling_mfa_preserves_password_and_role_checks(env,monkeypatch):
    monkeypatch.setattr(settings,'MFA_ENABLED',False)
    assert env['client'].post('/api/v2/auth/login',json={'email':'system_admin@example.com','password':'incorrect'}).status_code==401
    assert env['client'].get('/api/v2/dashboard?start=2026-09-01&end=2026-10-01').status_code==401
    assert request(env,'GET','/users','FUELLER').status_code==403


def test_mfa_cannot_be_enrolled_or_confirmed_when_disabled(env,monkeypatch):
    monkeypatch.setattr(settings,'MFA_ENABLED',False)
    assert request(env,'POST','/auth/mfa/enrol').status_code==403
    assert request(env,'POST','/auth/mfa/confirm',data={'otp':'123456'}).status_code==403


def test_enabled_mfa_still_requires_code_for_enrolled_user(env,monkeypatch):
    monkeypatch.setattr(settings,'MFA_ENABLED',True)
    with env['db']() as db:
        user=db.get(User,env['users']['SYSTEM_ADMIN'])
        user.mfa_enabled=True;user.mfa_secret=encrypt_secret('JBSWY3DPEHPK3PXP')
        db.commit()
    assert env['client'].post('/api/v2/auth/login',json={'email':'system_admin@example.com','password':'test-password-123'}).status_code==401
