from test_workflows import request
from fleet.config import settings
from fleet.models import EvidenceContent, Evidence

def test_public_deployment_and_protected_cron(env):
    response=request(env,'GET','/public/deployment')
    assert response.status_code==200 and response.json()=={'ready':True}
    assert env['client'].get('/api/cron/daily').status_code==401

def test_database_evidence_is_private_and_durable(fleet,monkeypatch):
    monkeypatch.setattr(settings,'EVIDENCE_STORAGE','database')
    monkeypatch.setattr(settings,'SERVERLESS',True)
    response=request(fleet,'POST','/evidence','FUELLER',data={'vehicle_id':fleet['vehicle']},files={'file':('private.png',fleet['image'],'image/png')})
    assert response.status_code==201,response.text
    evidence=response.json()
    assert 'content' not in evidence and 'storage_key' not in evidence
    with fleet['db']() as db:
        assert db.get(EvidenceContent,evidence['id']).content==fleet['image']
    download=request(fleet,'GET',f"/evidence/{evidence['id']}/download",'TRANSPORT_VERIFIER')
    assert download.status_code==200 and download.content==fleet['image']
    assert request(fleet,'GET',f"/evidence/{evidence['id']}/download",'DRIVER').status_code==403
    assert fleet['client'].get(f"/api/v2/evidence/{evidence['id']}/download").status_code==401

def test_serverless_rejects_ephemeral_uploads(fleet,monkeypatch):
    monkeypatch.setattr(settings,'SERVERLESS',True)
    monkeypatch.setattr(settings,'EVIDENCE_STORAGE','local')
    response=request(fleet,'POST','/evidence','FUELLER',data={'vehicle_id':fleet['vehicle']},files={'file':('private.png',fleet['image'],'image/png')})
    assert response.status_code==503

def test_serverless_evidence_size(fleet,monkeypatch):
    monkeypatch.setattr(settings,'SERVERLESS',True)
    monkeypatch.setattr(settings,'EVIDENCE_STORAGE','database')
    response=request(fleet,'POST','/evidence','FUELLER',data={'vehicle_id':fleet['vehicle']},files={'file':('large.png',b'a'*(3*1024*1024+1),'image/png')})
    assert response.status_code==413
