import pytest
from decimal import Decimal
from copy import deepcopy
from app.engine import evaluate, merge_overrides
from app.cadence import cadence_of
from app.compare import compare_runs, merge_unknown_periods, union_key
from app.modules.baseline.rules import estimate
from app.errors import BusinessError

@pytest.fixture
def mixed():
    return evaluate({'dataset':'mixed'})

# --- 设备级采样间隔 ---
def test_cadence_per_device(mixed):
    c=mixed['context']
    assert cadence_of(c,'INV-A')==300
    assert cadence_of(c,'INV-B')==600  # 保留旧频率的设备回落全局缺省

def test_cadence_invalid(mixed):
    for bad in (0,-300,90.5,'快',7200):
        c=deepcopy(mixed['context']);c['devices']['INV-A']['cadence_seconds']=bad
        with pytest.raises(BusinessError) as e: cadence_of(c,'INV-A')
        assert e.value.code=='BAD_CADENCE'

def test_overrides_deep_merge(mixed):
    c=deepcopy(mixed['context'])
    merge_overrides(c,{'devices':{'INV-B':{'cadence_seconds':300}}})
    assert cadence_of(c,'INV-B')==300 and c['devices']['INV-B']['capacity_kw']=='50'  # 嵌套归并不丢字段
    merge_overrides(c,{'min_references':3})
    assert c['min_references']==3  # 平键行为与旧版一致

# --- 事件边界与积分时长不因换频错位 ---
def test_mixed_union_boundaries_unchanged(mixed,clean):
    assert union_key(mixed)==union_key(clean)
    assert mixed['balance']['union_seconds']==clean['balance']['union_seconds']==3000
    assert mixed['balance']['time_balanced'] and mixed['balance']['slice_seconds']==3000

def test_mixed_five_minute_granularity(mixed):
    a=[s for s in mixed['segments'] if s['device']=='INV-A']
    assert len(a)==6 and all(s['seconds']==300 for s in a)
    b=[s for s in mixed['segments'] if s['device']=='INV-B']
    assert len(b)==2 and all(s['seconds']==600 for s in b)  # 旧频率设备切片不变

# --- 没有采到的分钟留作未测 ---
def test_mixed_gap_stays_undetermined(mixed):
    gaps=[s for s in mixed['segments'] if s['device']=='INV-A' and s['actual_kw'] is None]
    assert len(gaps)==1 and gaps[0]['start']=='2026-10-15T02:15:00+00:00' and gaps[0]['seconds']==300
    row=next(r for r in mixed['energy_rows'] if r['loss_kwh'] is None)
    assert row['code']=='TARGET_GAP' and row['loss_kwh'] is None  # 未定不填0
    assert mixed['balance']['unknown_seconds']==300 and mixed['balance']['unknown_segments']==1

def test_mixed_known_loss_cross_frequency(mixed):
    total=sum(Decimal(r['loss_kwh']) for r in mixed['energy_rows'] if r['loss_kwh'] is not None)
    assert total.quantize(Decimal('.0001'))==Decimal('23.3333')
    kept=sum(Decimal(r['loss_kwh']) for r in mixed['energy_rows'] if r['device']=='INV-B')
    assert kept.quantize(Decimal('.0001'))==Decimal('6.6667')  # 保留旧频率的设备结果与旧版一致

# --- 基线对照的覆盖窗口匹配 ---
def test_reference_window_covers_finer_target(clean):
    segment={'device':'INV-A','start':'2026-10-15T02:05:00+00:00','end':'2026-10-15T02:10:00+00:00',
             'seconds':300,'sample_id':'X','sample_at':'2026-10-15T02:05:00+00:00','actual_kw':'60',
             'irradiance':'800','status':'健康','zone':'东区','event_ids':['EA1','EA2']}
    est=estimate(segment,clean['records'],clean['context'])
    assert est['code']=='ESTIMATED' and est['baseline_kw']=='100'
    assert est['reference_ids']==['REF-A1-00','REF-A2-00']  # 10分钟参考的保持窗口覆盖10:05

def test_reference_beyond_window_stays_undetermined(clean):
    # 同一时点同一批读数: 参考保持窗口缩短到300秒后,10:05不再被10:00读数覆盖,超过窗口不外推
    segment={'device':'INV-A','start':'2026-10-15T02:05:00+00:00','end':'2026-10-15T02:10:00+00:00',
             'seconds':300,'sample_id':'X','sample_at':'2026-10-15T02:05:00+00:00','actual_kw':'60',
             'irradiance':'800','status':'健康','zone':'东区','event_ids':['EA1','EA2']}
    c=deepcopy(clean['context'])
    c['devices']['REF-A1']['cadence_seconds']=300;c['devices']['REF-A2']['cadence_seconds']=300
    assert estimate(segment,clean['records'],c)['code']=='NO_REFERENCE'

def test_uniform_cadence_selection_unchanged(clean):
    # 均匀频率下覆盖窗口与旧版"同一采样时刻"逐位等价
    first=clean['estimates'][0]
    assert first['baseline_kw']=='100' and first['reference_ids']==['REF-A1-00','REF-A2-00']
    assert [e['code'] for e in clean['estimates']]==['ESTIMATED']*5

# --- 新旧批对照 ---
def test_compare_clean_vs_mixed(mixed,clean):
    result=compare_runs(mixed,clean)
    assert result['totals']['current_loss_kwh']=='23.3333'
    assert result['totals']['other_loss_kwh']=='26.6667'
    assert result['totals']['delta_kwh']=='-3.3333'
    assert result['totals']['current_unknown_seconds']==300 and result['totals']['other_unknown_seconds']==0
    assert result['totals']['union_matched']==2 and not result['unmatched_current'] and not result['unmatched_other']
    a=next(r for r in result['matched_unions'] if r['device']=='INV-A')
    assert a['delta_kwh']=='-3.3333' and a['current_unknown_seconds']==300

def test_merge_unknown_periods(mixed):
    periods=merge_unknown_periods(mixed)
    assert periods==[{'device':'INV-A','start':'2026-10-15T02:15:00+00:00','end':'2026-10-15T02:20:00+00:00','seconds':300,'code':'TARGET_GAP'}]

def test_merge_unknown_periods_adjacent(clean):
    s=deepcopy(clean)
    for row in s['energy_rows']:
        if row['device']=='INV-A':row['loss_kwh']=None
    periods=merge_unknown_periods(s)
    assert periods==[{'device':'INV-A','start':'2026-10-15T02:00:00+00:00','end':'2026-10-15T02:30:00+00:00','seconds':1800,'code':'LOSS'}]

# --- 重跑幂等 / 换频回滚 / 页面 ---
from fastapi.testclient import TestClient
from app import main

def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB_PATH',str(tmp_path/'test.sqlite'));return TestClient(main.app)

def test_rerun_keeps_confirmed_loss(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    old=c.post('/api/runs',json={'dataset':'clean'}).json();rid=old['manifest']['run_id']
    assert c.post(f'/api/runs/{rid}/review',json={'revision':1}).status_code==200
    again=c.post(f'/api/runs/{rid}/rerun',json={}).json()
    assert again['manifest']['run_id']==rid  # 重跑同批不新增批次
    assert again['balance']['loss_kwh']==old['balance']['loss_kwh']=='26.6667'  # 已确认损失不变
    assert len(c.get('/api/runs').json())==1

def test_frequency_switch_and_rollback(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    old=c.post('/api/runs',json={'dataset':'clean'}).json();old_id=old['manifest']['run_id']
    switched=c.post('/api/runs',json={'dataset':'clean','overrides':{'cadence_seconds':300}}).json()
    new_id=switched['manifest']['run_id']
    assert new_id!=old_id  # 换频生成新批次
    assert switched['balance']['unknown_seconds']>0  # 数据未跟上新频率的分钟保持未定
    back=c.post('/api/runs',json={'dataset':'clean'}).json()
    assert back['manifest']['run_id']==old_id  # 换频中断恢复旧版结果
    assert back['balance']['loss_kwh']==old['balance']['loss_kwh']
    ids={r['id'] for r in c.get('/api/runs').json()}
    assert {old_id,new_id}<=ids  # 无数据丢失,两批共存

def test_compare_endpoint_and_page(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    old=c.post('/api/runs',json={'dataset':'clean'}).json()
    new=c.post('/api/runs',json={'dataset':'mixed'}).json();new_id=new['manifest']['run_id']
    r=c.get(f'/api/runs/{new_id}/compare',params={'other':old['manifest']['run_id']})
    assert r.status_code==200
    assert r.json()['totals']['delta_kwh']=='-3.3333' and r.json()['totals']['current_unknown_seconds']==300
    auto=c.get(f'/api/runs/{new_id}/compare')  # 缺省自动选中同一时段的旧批
    assert auto.status_code==200 and auto.json()['other_run_id']==old['manifest']['run_id']
    html=c.get('/loss',params={'run_id':new_id}).text
    assert '新旧对照' in html and '未定时段' in html and '-3.3333' in html and '02:15' in html
    missing=c.get(f'/api/runs/{new_id}/compare',params={'other':'none'})
    assert missing.status_code==404
