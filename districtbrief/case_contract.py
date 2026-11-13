"""Closed IA-1 request contract; validation always precedes analytical dispatch."""
from __future__ import annotations
from .contract import RE_FINDING_ID
import datetime
import re
import uuid

SCHEMA_VERSION = 'haic-investigation/1'
OPERATION_VERSION = 'ia-core/1'
HASH = re.compile(r'^sha256:[0-9a-f]{64}$', re.ASCII)
SERVICES = {'statewide','oahu','hawaii_island','maui','molokai','lanai','kauai','kalawao'}
TOKEN_KEYS = ('request_id','case_id','branch_id','revision','snapshot_id','schema_version','operation_version','recipe_version')

class InvestigationError(ValueError):
    def __init__(self, status=400, code='invalid_request', message='The request failed contract validation.', path='', retry_action='correct_fields'):
        super().__init__(message)
        self.status,self.code,self.message,self.retry_action=status,code,message,retry_action
        self.issues=[{'path':path,'code':code,'message':message}]
    def envelope(self, request=None):
        out={'status':'error','code':self.code,'message':self.message,'issues':self.issues,'retry_action':self.retry_action,'model_calls':0}
        if isinstance(request,dict):
            tokens={k:request[k] for k in TOKEN_KEYS if k in request}
            try:
                for key in ('request_id','case_id','branch_id'):uuid4(tokens.get(key),key)
                integer(tokens.get('revision'),0,2147483647,'revision')
                if len(tokens)==len(TOKEN_KEYS) and all(type(tokens[k]) is str for k in ('snapshot_id','schema_version','operation_version','recipe_version')):
                    out['tokens']=tokens
            except InvestigationError:
                pass
        return out

def fail(path, message, code='invalid_request', status=400):
    raise InvestigationError(status,code,message,path)

def obj(value, required, optional=(), path=''):
    if type(value) is not dict: fail(path,'An object is required.')
    if set(value)-set(required)-set(optional): fail(path,'Unknown fields are not accepted.')
    if set(required)-set(value): fail(path,'Required fields are missing.')

def integer(value, minimum, maximum, path):
    if type(value) is not int or not minimum <= value <= maximum: fail(path,'An integer in the admitted range is required.')

def text(value, maximum, path, minimum=0):
    if type(value) is not str or not minimum<=len(value)<=maximum: fail(path,'Text exceeds its admitted length or has an invalid type.')
    try: value.encode('utf-8')
    except UnicodeError: fail(path,'Invalid Unicode is not accepted.')

def uuid4(value, path):
    try:
        parsed=uuid.UUID(value) if type(value) is str else None
        if parsed is None or parsed.version!=4 or str(parsed)!=value: raise ValueError
    except (ValueError,AttributeError): fail(path,'A canonical lowercase UUIDv4 is required.')

def depth(value, level=0):
    if level>12: fail('','JSON nesting exceeds 12 levels.')
    if isinstance(value,dict):
        for k,v in value.items(): text(k,1000,'key');depth(v,level+1)
    elif isinstance(value,list):
        for v in value: depth(v,level+1)
    elif isinstance(value,str): text(value,65536,'text')

def unique_ids(value, allowed, minimum, maximum, path):
    if type(value) is not list or not minimum<=len(value)<=maximum: fail(path,'The list has an invalid size.')
    if any(type(v) is not str or v not in allowed for v in value): fail(path,'The list contains an unadmitted identifier.')
    if len(set(value))!=len(value): fail(path,'Duplicate identifiers are not accepted.')

def claim_ref(value,path):
    obj(value,('snapshot_id','finding_id','semantic_hash'),path=path)
    for k in ('snapshot_id','semantic_hash'):
        if type(value[k]) is not str or not HASH.fullmatch(value[k]): fail(path+'.'+k,'A full SHA-256 identity is required.')
    text(value['finding_id'],500,path+'.finding_id',1)
    if not RE_FINDING_ID.fullmatch(value['finding_id']):fail(path+'.finding_id','A canonical finding ID is required.')

def validate_plan(plan,core):
    obj(plan,('district','map_session','issue_id','service_area_id','steps'),path='plan')
    d=plan['district'];obj(d,('state_fips','chamber','code','boundary_session'),path='plan.district')
    if d['state_fips']!='15' or d['chamber'] not in ('house','senate') or type(d['code']) is not str or not re.fullmatch(r'[0-9]{3}',d['code'],re.ASCII): fail('plan.district','An admitted Hawaiʻi district is required.')
    if not 1<=int(d['code'])<=(51 if d['chamber']=='house' else 25) or type(d['boundary_session']) is not int or d['boundary_session']!=2024: fail('plan.district','Only the admitted 2024 statistical districts are supported.')
    if type(plan['map_session']) is not int or plan['map_session'] not in (2024,2026): fail('plan.map_session','Map session must be 2024 or 2026.')
    if plan['issue_id'] not in ('aging_at_home','custom'): fail('plan.issue_id','Choose aging_at_home or custom.')
    if plan['service_area_id'] is not None and (type(plan['service_area_id']) is not str or plan['service_area_id'] not in SERVICES): fail('plan.service_area_id','Unknown staff service-area choice.')
    steps=plan['steps']
    if type(steps) is not list or len(steps)>8: fail('plan.steps','A plan holds at most eight steps.')
    ids=set()
    for i,s in enumerate(steps):
        p=f'plan.steps[{i}]';obj(s,('step_id','operation','args'),path=p)
        if type(s['step_id']) is not str or not re.fullmatch(r's[0-9]{1,3}',s['step_id'],re.ASCII) or s['step_id'] in ids: fail(p+'.step_id','A unique s plus 1–3 digit identifier is required.')
        ids.add(s['step_id']);op=s['operation'];a=s['args']
        if op=='profile':
            obj(a,('metric_ids',),path=p+'.args')
            if a['metric_ids'] is not None: unique_ids(a['metric_ids'],core.metrics,1,20,p+'.args.metric_ids')
        elif op=='compare':
            obj(a,('metric_ids','comparison_geography'),path=p+'.args');unique_ids(a['metric_ids'],core.metrics,1,4,p+'.args.metric_ids')
            text(a['comparison_geography'],80,p+'.args.comparison_geography',1)
            if not re.fullmatch(r'HI-(?:STATE|COUNTY-[0-9]{3}|HOUSE-[0-9]{3}|SENATE-[0-9]{3})-2024',a['comparison_geography'],re.ASCII): fail(p+'.args.comparison_geography','A canonical geography ID is required.')
        elif op=='program_evidence':
            obj(a,('program_ids',),path=p+'.args');unique_ids(a['program_ids'],core.programs,1,5,p+'.args.program_ids')
        elif op=='outreach_lead':
            if isinstance(a,dict) and (set(a)-{'program_id'}): fail(p+'.args','The full reviewed hypothesis basis and State references are required.','reviewed_basis_required')
            obj(a,('program_id',),path=p+'.args');unique_ids([a['program_id']],core.programs,1,1,p+'.args.program_id')
        elif op=='administrative_evidence':
            obj(a,('observation_ids',),path=p+'.args');unique_ids(a['observation_ids'],core.administrative_rows,1,8,p+'.args.observation_ids')
        else: fail(p+'.operation','Unsupported plan operation.')
    return plan

def date(value,path):
    if value is None:return
    try:
        if type(value) is not str or datetime.date.fromisoformat(value).isoformat()!=value:raise ValueError
    except ValueError: fail(path,'Use an ISO YYYY-MM-DD date.')

def validate_request(raw,core,snapshot_id):
    common=('schema_version','operation_version','recipe_version','snapshot_id','request_id','case_id','branch_id','revision','mode','plan')
    if type(raw) is not dict: fail('','A JSON object is required.')
    mode=raw.get('mode')
    if type(mode) is not str:fail('mode','Choose interpret, run or brief.')
    extra={'interpret':('utterance',),'run':('selected_claim_refs','selected_action_ref'),'brief':('selected_claim_refs','selected_action_ref','staff_edits','checklist_edits','tracking','edits_reviewed_for')}.get(mode)
    if extra is None:fail('mode','Choose interpret, run or brief.')
    obj(raw,common+extra);depth(raw)
    for k in ('request_id','case_id','branch_id'):uuid4(raw[k],k)
    integer(raw['revision'],0,2147483647,'revision')
    if raw['schema_version']!=SCHEMA_VERSION:fail('schema_version','This schema version is unavailable.','version_mismatch',409)
    if raw['operation_version']!=OPERATION_VERSION:fail('operation_version','This operation version is unavailable.','version_mismatch',409)
    if raw['snapshot_id']!=snapshot_id: raise InvestigationError(409,'snapshot_unavailable','This case needs a different evidence snapshot. Historical R2 cases require the matching live R2 app or the documented r2 profile with retained original inputs.','snapshot_id','open_matching_release_or_keep_saved_case')
    plan=raw['plan']
    if plan is not None: validate_plan(plan,core)
    elif mode!='interpret':fail('plan','A plan is required.')
    expected=(plan['issue_id']+'/1') if plan else raw['recipe_version']
    if raw['recipe_version'] not in ('aging_at_home/1','custom/1') or raw['recipe_version']!=expected:fail('recipe_version','The recipe version is unavailable or conflicts with the issue.','version_mismatch',409)
    if mode=='interpret':text(raw['utterance'],500,'utterance',1);return
    refs=raw['selected_claim_refs']
    if type(refs) is not list or len(refs)>8:fail('selected_claim_refs','Select at most eight findings.')
    seen=set()
    for i,r in enumerate(refs):
        claim_ref(r,f'selected_claim_refs[{i}]');key=tuple(r[k] for k in ('snapshot_id','finding_id','semantic_hash'))
        if key in seen:fail('selected_claim_refs','Duplicate selections are not accepted.')
        seen.add(key)
    action=raw['selected_action_ref']
    if action is not None:
        obj(action,('action_id','semantic_hash'),path='selected_action_ref')
        if action['action_id'] not in ('kupuna_verify/1','snap_verify/1','medquest_verify/1','hcv_verify/1') or type(action['semantic_hash']) is not str or not HASH.fullmatch(action['semantic_hash']):fail('selected_action_ref','Invalid action identity.')
    if mode!='brief':return
    if not refs:fail('selected_claim_refs','A printable brief requires at least one finding.')
    edits=raw['staff_edits'];obj(edits,(),('title','note','next_steps','finding_notes'),'staff_edits')
    for k,limit in [('title',90),('note',400),('next_steps',300)]:
        if k in edits:text(edits[k],limit,'staff_edits.'+k)
    if 'finding_notes' in edits:
        notes=edits['finding_notes'];obj(notes,(),notes.keys() if isinstance(notes,dict) else (),'staff_edits.finding_notes')
        if len(notes)>8:fail('staff_edits.finding_notes','At most eight finding notes are admitted.')
        for h,t in notes.items():
            if not HASH.fullmatch(h) or h not in {r['semantic_hash'] for r in refs}:fail('staff_edits.finding_notes','Finding notes must identify selected canonical claims.')
            text(t,160,'staff_edits.finding_notes')
    check=raw['checklist_edits']
    if type(check) is not list or len(check)>6:fail('checklist_edits','At most six checklist items are admitted.')
    ids=set()
    for i,item in enumerate(check):
        p=f'checklist_edits[{i}]';obj(item,('item_id',),('text','owner_role','due_date','completed'),p)
        if item['item_id'] not in ('agency_route','partner_plan','next_check','custom1','custom2','custom3') or item['item_id'] in ids:fail(p,'An admitted unique checklist ID is required.')
        ids.add(item['item_id'])
        for k,lim in [('text',120),('owner_role',80)]:
            if k in item:text(item[k],lim,p+'.'+k)
        if 'due_date' in item:date(item['due_date'],p+'.due_date')
        if 'completed' in item and type(item['completed']) is not bool:fail(p+'.completed','A boolean is required.')
    track=raw['tracking']
    if track is not None:
        obj(track,('label','baseline','as_of'),path='tracking');text(track['label'],80,'tracking.label')
        if track['baseline'] is not None:integer(track['baseline'],0,1000000000,'tracking.baseline')
        date(track['as_of'],'tracking.as_of')
    review=raw['edits_reviewed_for']
    if review is not None:
        obj(review,('branch_id','revision','plan_hash'),path='edits_reviewed_for');uuid4(review['branch_id'],'edits_reviewed_for.branch_id');integer(review['revision'],0,2147483647,'edits_reviewed_for.revision')
        if type(review['plan_hash']) is not str or not HASH.fullmatch(review['plan_hash']):fail('edits_reviewed_for.plan_hash','A full plan hash is required.')
