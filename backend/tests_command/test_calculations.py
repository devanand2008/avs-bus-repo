from datetime import datetime,date,timedelta,timezone
from types import SimpleNamespace as Point
from decimal import Decimal
import pytest
from fleet.calculations import *

def test_bike_mean_and_scope():
    assert bike_mean([79,80,81],['trip']*3)==D(80)
    assert bike_mean([79,80,81],['trip']*3)*2==160
    with pytest.raises(ValueError):bike_mean([79,80,81],['one_way','round_trip','round_trip'])

def test_four_80km_trips():
    assert sum([80]*4)==320
    assert expected_use([(80,4)]*4)==80

def test_topup_unknown_zero():
    assert recommendation(100,18)==82
    assert recommendation(100,None) is None
    assert recommendation(100,0)==100
    assert recommendation(100,120)==0

def test_disappearance_and_zero_residual():
    assert stock_reconcile(40,200,60,expected_use([(720,4)]))==(D(180),D(0))

def test_standard_range_shortfall():
    assert range_variance(720,200,4)==(D(800),D(80),D(20))

def test_monthly_example():
    assert stock_reconcile(120,2000,180,expected_use([(7600,4)]))==(D(1940),D(40))

def test_missing_stock_and_mileage():
    assert stock_reconcile(None,0,0,0)==(None,None)
    assert stock_reconcile(0,0,0,None)==(D(0),None)
    assert expected_use([(100,None)]) is None
    assert expected_use([(100,4),(100,5)])==45
    assert aggregate_mileage(720,200)==D('3.6')

def test_transfers_and_mileage_weighting():
    assert stock_reconcile(100,50,40,100,20,30)==(D(100),D(0))
    assert aggregate_mileage(100+900,25+150)==D(1000)/D(175)

def test_periods_and_midnight_split():
    a=datetime(2026,9,30,18,20,tzinfo=timezone.utc);b=a+timedelta(minutes=20)
    portions=split_interval(a,b,20)
    assert len(portions)==2 and sum(x[2] for x in portions)==20
    assert portions[0][0].astimezone(IST).date()==date(2026,9,30)
    assert portions[1][0].astimezone(IST).date()==date(2026,10,1)
    assert period('this_week',date(2026,10,22))==(date(2026,10,19),date(2026,10,26))
    assert period('last_month',date(2026,10,22))==(date(2026,9,1),date(2026,10,1))
    assert boundaries(date(2026,10,1),date(2026,11,1))[0].hour==18

def point(t,lat='11.65',lon='78.16',event='a',**kw):
    defaults={'fix_at':t,'lat':D(lat),'lon':D(lon),'event_id':event,'device_id':'device','provider':'test','accuracy_m':D(5),'odometer_km':None,'speed_kph':D(30),'ignition':True,'quality':'raw'};defaults.update(kw);return Point(**defaults)

def test_gaps_jumps_jitter_and_units():
    t=datetime(2026,10,1,tzinfo=timezone.utc)
    segments,flags=accepted_segments([point(t),point(t+timedelta(hours=1),lat='11.7',event='b')])
    assert not segments and flags['gaps']==1
    segments,flags=accepted_segments([point(t),point(t+timedelta(seconds=10),lat='12.7',event='b')])
    assert not segments and flags['jumps']==1
    segments,flags=accepted_segments([point(t),point(t+timedelta(seconds=30),lat='11.650001',event='b',speed_kph=0,ignition=False)])
    assert sum(x[2] for x in segments)==0 and flags['jitter']==1
    assert speed_kph(10,'mph')==D('16.093440')
    assert speed_kph(10,'mps')==36

def test_out_of_order_device_swaps_and_bad_accuracy():
    t=datetime(2026,10,1,tzinfo=timezone.utc)
    p1=point(t);p2=point(t+timedelta(seconds=30),lat='11.651',event='b')
    segments,_=accepted_segments([p2,p1]);assert len(segments)==1 and segments[0][2]>0
    segments,flags=accepted_segments([p1,point(t+timedelta(seconds=30),lat='11.651',device_id='other')]);assert not segments and flags['gaps']==1
    segments,flags=accepted_segments([p1,point(t+timedelta(seconds=30),accuracy_m=D(100))]);assert not segments and flags['poor_accuracy']==1
