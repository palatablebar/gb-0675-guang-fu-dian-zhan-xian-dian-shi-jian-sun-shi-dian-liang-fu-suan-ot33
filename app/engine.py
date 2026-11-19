from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES
from app.errors import BusinessError
from app.manifest import digest, make_manifest

def datasets():
    return {p.stem for p in (ROOT/'sample_data').glob('*.csv')}

def load_context(dataset):
    specific=ROOT/'sample_data'/f'{dataset}.context.json'
    return json.loads((specific if specific.exists() else ROOT/'sample_data/context.json').read_text())

def merge_overrides(base, overrides):
    # 深合并: 嵌套字典(如 devices.INV-A.cadence_seconds)按键归并, 其余整体替换。
    for key,value in overrides.items():
        if isinstance(value,dict) and isinstance(base.get(key),dict): merge_overrides(base[key],value)
        else: base[key]=deepcopy(value)

def evaluate(payload=None, until=7, snapshot=None):
    payload=payload or {}
    dataset=payload.get('dataset','dirty')
    if dataset not in datasets(): raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    raw=(base64.b64decode(snapshot['bytes_b64'],validate=True) if snapshot is not None else (str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes()))
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    context=deepcopy(snapshot['context']) if snapshot is not None else load_context(dataset)
    merge_overrides(context,payload.get('overrides',{}))
    start=time.perf_counter()
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset}
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':deepcopy(context)}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,context),dataset,time.perf_counter()-start)
    return state
