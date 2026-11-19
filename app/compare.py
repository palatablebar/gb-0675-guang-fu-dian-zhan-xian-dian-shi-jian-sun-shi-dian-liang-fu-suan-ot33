from decimal import Decimal
from app.coerce import instant

def union_key(result):
    """事件并集签名: 同一时段的新旧批(无论采样频率)签名相同, 是对照对齐的基准。"""
    return sorted((u['device'],u['start'],u['end']) for u in result.get('event_unions',[]))

def _quantize(value):
    return str(value.quantize(Decimal('.0001')))

def _union_energy(result):
    unions={(u['device'],u['start'],u['end']):{'seconds':u['seconds'],'known':Decimal(0),'unknown_seconds':0} for u in result.get('event_unions',[])}
    for row in result.get('energy_rows',[]):
        start,end=instant(row['start']),instant(row['end'])
        for (device,us,ue),agg in unions.items():
            if device==row['device'] and instant(us)<=start and end<=instant(ue):
                if row['loss_kwh'] is None: agg['unknown_seconds']+=row['seconds']
                else: agg['known']+=Decimal(row['loss_kwh'])
                break
    return unions

def merge_unknown_periods(result):
    """当前批未定时段: 同设备同原因且时间相邻的片段合并,便于复核直读。"""
    rows=[r for r in result.get('energy_rows',[]) if r['loss_kwh'] is None]
    rows.sort(key=lambda r:(r['device'],r['code'],instant(r['start'])))
    merged=[]
    for r in rows:
        if merged and merged[-1]['device']==r['device'] and merged[-1]['code']==r['code'] and merged[-1]['end']==r['start']:
            merged[-1]['end']=r['end'];merged[-1]['seconds']+=r['seconds']
        else:
            merged.append({'device':r['device'],'start':r['start'],'end':r['end'],'seconds':r['seconds'],'code':r['code']})
    return merged

def compare_runs(current, other):
    """新旧批对照: 按设备+事件并集对齐,确定损失求差,未定秒数单列;对不上的并集单独列出。"""
    cur=_union_energy(current);oth=_union_energy(other)
    matched=sorted(set(cur)&set(oth))
    rows=[];totals={'current':Decimal(0),'other':Decimal(0),'current_unknown':0,'other_unknown':0}
    for key in matched:
        c,o=cur[key],oth[key]
        rows.append({'device':key[0],'start':key[1],'end':key[2],'seconds':c['seconds'],
            'current_loss_kwh':_quantize(c['known']),'other_loss_kwh':_quantize(o['known']),
            'delta_kwh':_quantize(c['known']-o['known']),
            'current_unknown_seconds':c['unknown_seconds'],'other_unknown_seconds':o['unknown_seconds']})
        totals['current']+=c['known'];totals['other']+=o['known']
        totals['current_unknown']+=c['unknown_seconds'];totals['other_unknown']+=o['unknown_seconds']
    return {'other_run_id':other['manifest']['run_id'],'other_source':other.get('source'),
            'matched_unions':rows,
            'unmatched_current':[{'device':k[0],'start':k[1],'end':k[2]} for k in sorted(set(cur)-set(oth))],
            'unmatched_other':[{'device':k[0],'start':k[1],'end':k[2]} for k in sorted(set(oth)-set(cur))],
            'unknown_periods':merge_unknown_periods(current),
            'totals':{'current_loss_kwh':_quantize(totals['current']),'other_loss_kwh':_quantize(totals['other']),
                      'delta_kwh':_quantize(totals['current']-totals['other']),
                      'current_unknown_seconds':totals['current_unknown'],'other_unknown_seconds':totals['other_unknown'],
                      'union_matched':len(matched),'union_current':len(cur),'union_other':len(oth)}}

def compare_view(path, state, selected):
    """页面/接口共用: 候选批次列表 + 默认对照选择(并集签名相同的最近批) + 对照结果。"""
    from app import store
    candidates=[s for s in store.summaries(path) if s['id']!=state['manifest']['run_id']]
    chosen=None
    if selected:
        chosen=next((c for c in candidates if c['id']==selected),None)
        if chosen is None:
            from app.errors import BusinessError
            raise BusinessError('NOT_FOUND','对照批次不存在',404)
    else:
        key=union_key(state)
        chosen=next((c for c in candidates if c['unions'] and sorted(c['unions'])==key),None)
    result=compare_runs(state,store.get(path,chosen['id'])) if chosen else None
    return {'candidates':candidates,'selected':chosen['id'] if chosen else None,
            'result':result,'unknown_periods':merge_unknown_periods(state)}
