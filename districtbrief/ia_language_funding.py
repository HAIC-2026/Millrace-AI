"""The ONE active production/evaluation money authority.

A root-owned funding record (funding.json) carries forward the already-spent history by reference to
the immutable old ledgers (no copied historical transactions), sets finite current limits, an explicit
reserve for the unpublished Count fee and per-bucket, per-profile start admission. One serialized
ledger (ledger/ledger.json) records only new starts for every profile and both buckets.
Holds are temporary; settled estimates are provider-reported usage at documented rates, not invoices.
The lock, durable write and entry state transitions are the reviewed legacy BudgetLedger mechanics.
"""
from __future__ import annotations
import copy
import hashlib
import os
from pathlib import Path
import re
import time
import uuid
from .ia_language import LanguageError, dumps, strict_json
from .ia_language_accounting import BudgetLedger
from .ia_language_profiles import PROFILES_PATH, Profile, load_profiles

CONTROL_DIR=Path('/run/haic-language-control')
FUNDING_FILE='funding.json'
LEDGER_FILE='ledger.json'
# Root-owned sentinel (root:10001 0440 in the root-owned control dir, so uid 10001 cannot remove it), written by
# the protected funding step right after the one-shot init. It pins the ledger's genesis: init refuses once it
# exists, and a protected ledger without it, or with a different genesis (a re-created ledger), is unavailable.
GENESIS_FILE='ledger-genesis.json'
GENESIS_SCHEMA='ia-language-ledger-genesis/1'
_GENESIS_KEYS=('schema_version','ledger_id','created_at','carry_forward_sha256')
FUNDING_SCHEMA='ia-language-funding/1'
LEDGER_SCHEMA='ia-language-funding-ledger/1'
BUCKETS=('test','demo')
# Safety ceiling on any approved project total; the approved total itself is root-owned data.
PROJECT_TOTAL_CEILING_NANO_USD=25000000000
MAX_STARTS_CEILING=10000
RESERVATION_CUSHION_PERCENT=20
COST_BASIS='provider_reported_usage_at_documented_rates_not_invoice'
COUNT_ENDPOINT_PRICE='not_published_in_fetched_pricing_documentation'
CONTINGENCY_BASIS='explicit_planning_reserve_for_unpublished_count_fee_not_a_fee_bound_or_settled_cost'
SOURCE_KINDS=('canonical_ledger','evaluation_journal')
STATES=('reserved','dispatched','unknown','settled','released')
_SHA=re.compile(r'sha256:[0-9a-f]{64}')
_HEX=re.compile(r'[0-9a-f]{64}')
_UUID=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
_PID=re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
_REF=re.compile(r'[A-Za-z0-9:._/@+=-]{8,300}')
_FUNDING_KEYS={'schema_version','approved','approval_reference','ledger_id','total_limit_nano_usd','limits_nano_usd',
    'contingency_nano_usd','admission','profile_hashes','max_starts','carry_forward'}
_CARRY_KEYS={'starts','settled_nano_usd','held_nano_usd','sources'}
_SOURCE_KEYS={'kind','id','file_sha256','sequence','entries','starts','released_zero_start','settled_nano_usd',
    'held_nano_usd','unresolved_entries','reference'}
_STATE_KEYS={'schema_version','ledger_id','carry_forward_sha256','created_at','sequence','entries','cost_basis'}
_ENTRY_KEYS={'entry_id','sequence','bucket','state','created_at','reserved_nano_usd','settled_estimate_nano_usd','payload_hash',
    'profile_id','profile_hash','config_hash','counted_input_tokens','count_requests','model_calls','usage','terminal_code'}

def _int(v,lo=0,hi=PROJECT_TOTAL_CEILING_NANO_USD):return type(v) is int and lo<=v<=hi
def _buckets(v,check=_int):return type(v) is dict and set(v)==set(BUCKETS) and all(check(v[b]) for b in BUCKETS)

def reservation(profile,input_tokens=None):
    """Worst-case hold: counted (or capped) input at the uncached rate plus the full output cap, +20%."""
    n=profile.max_input_tokens if input_tokens is None else input_tokens
    if type(n) is not int or not 0<n<=profile.max_input_tokens:raise LanguageError('input_token_limit')
    base=n*profile.rates['uncached_input']+profile.max_output_tokens*profile.rates['output']
    return (base*(100+RESERVATION_CUSHION_PERCENT)+99)//100

def parse_usage(raw,profile):
    """Input is inclusive of cache buckets; reasoning is a SUBSET of output (never billed twice)."""
    if type(raw) is not dict or set(raw)!={'input_tokens','input_tokens_details','output_tokens','output_tokens_details','total_tokens'}:raise LanguageError('unknown_usage')
    i,o,total=(raw[k] for k in ('input_tokens','output_tokens','total_tokens'))
    if any(type(n) is not int or n<0 for n in (i,o,total)) or total!=i+o:raise LanguageError('unknown_usage')
    details=raw['input_tokens_details'];out=raw['output_tokens_details']
    if type(details) is not dict or not {'cached_tokens','cache_write_tokens'}<=set(details) or set(details)-{'cached_tokens','cache_write_tokens','cache_write_tokens_details'}:raise LanguageError('unknown_usage')
    cached=details['cached_tokens'];writes=details.get('cache_write_tokens',0)
    if any(type(n) is not int or n<0 for n in (cached,writes)) or cached+writes>i:raise LanguageError('unknown_usage')
    if details.get('cache_write_tokens_details') is not None:
        d=details['cache_write_tokens_details']
        if type(d) is not dict or set(d)-{'ttl_30m_tokens','ttl_12h_tokens'}:raise LanguageError('unknown_usage')
        if any(type(v) is not int or v<0 for v in d.values()) or sum(d.values())!=writes:raise LanguageError('unknown_usage')
        if d.get('ttl_12h_tokens',0):raise LanguageError('unexpected_cache_write')
    if type(out) is not dict or set(out)!={'reasoning_tokens'} or type(out['reasoning_tokens']) is not int or not 0<=out['reasoning_tokens']<=o:raise LanguageError('unknown_usage')
    if i>profile.max_input_tokens or o>profile.max_output_tokens:raise LanguageError('usage_exceeds_limits')
    return {'input_tokens':i,'uncached_input_tokens':i-cached-writes,'cached_input_tokens':cached,
            'cache_write_tokens':writes,'output_tokens':o,'reasoning_tokens_within_output':out['reasoning_tokens'],
            'total_tokens':total}

def usage_cost(usage,profile):
    r=profile.rates
    return (usage['uncached_input_tokens']*r['uncached_input']+usage['cached_input_tokens']*r['cached_input']+
            usage['cache_write_tokens']*r['cache_write_30m']+usage['output_tokens']*r['output'])

def financial_plan(f,profiles):
    """Worst case if every admitted start holds and settles its full reservation. Pure; no I/O."""
    buckets={}
    for b in BUCKETS:
        holds={pid:{'cap':cap,'reservation_per_start_nano_usd':reservation(profiles[pid]),'worst_case_nano_usd':cap*reservation(profiles[pid])}
               for pid,cap in sorted(f['admission'][b].items())}
        carried=f['carry_forward']['settled_nano_usd'][b];contingency=f['contingency_nano_usd'][b]
        worst=carried+contingency+sum(h['worst_case_nano_usd'] for h in holds.values())
        buckets[b]={'limit_nano_usd':f['limits_nano_usd'][b],'carried_settled_nano_usd':carried,'count_fee_contingency_nano_usd':contingency,
            'admitted_new_starts':sum(h['cap'] for h in holds.values()),'by_profile':holds,'worst_case_total_nano_usd':worst,
            'headroom_nano_usd':f['limits_nano_usd'][b]-worst,'fits':worst<=f['limits_nano_usd'][b]}
    worst=sum(x['worst_case_total_nano_usd'] for x in buckets.values());new=sum(x['admitted_new_starts'] for x in buckets.values())
    total={'limit_nano_usd':f['total_limit_nano_usd'],'bucket_limits_nano_usd':sum(f['limits_nano_usd'].values()),
        'worst_case_total_nano_usd':worst,'headroom_nano_usd':f['total_limit_nano_usd']-worst,
        'fits':worst<=f['total_limit_nano_usd'] and sum(f['limits_nano_usd'].values())<=f['total_limit_nano_usd']}
    contingency=sum(f['contingency_nano_usd'].values())
    return {'ok':total['fits'] and all(x['fits'] for x in buckets.values()) and f['max_starts']==f['carry_forward']['starts']+new,
        'buckets':buckets,'total':total,'carried_starts':f['carry_forward']['starts'],'admitted_new_starts':new,'max_starts':f['max_starts'],
        # The Count fee is unpublished for EVERY historical and new count request; the reserve is planning, not a fee bound.
        'count_fee':{'price':COUNT_ENDPOINT_PRICE,'historical_count_requests':f['carry_forward']['starts'],'planned_new_count_requests':new,
            'contingency_nano_usd':contingency,'implied_reserve_per_count_full_history_nano_usd':contingency//f['max_starts'] if f['max_starts'] else None,
            'basis':CONTINGENCY_BASIS},
        'cost_basis':COST_BASIS,'reservation_cushion_percent':RESERVATION_CUSHION_PERCENT}

def validate_funding(raw,profiles):
    """Strict funding record; every pinned profile must match current data and the worst case must fit."""
    try:
        f=strict_json(raw)
        if type(f) is not dict or set(f)!=_FUNDING_KEYS or f['schema_version']!=FUNDING_SCHEMA or f['approved'] is not True:raise ValueError()
        if type(f['approval_reference']) is not str or not _REF.fullmatch(f['approval_reference']):raise ValueError()
        if type(f['ledger_id']) is not str or not _UUID.fullmatch(f['ledger_id']):raise ValueError()
        if not _int(f['total_limit_nano_usd'],1) or not _buckets(f['limits_nano_usd']) or not _buckets(f['contingency_nano_usd']):raise ValueError()
        if any(f['contingency_nano_usd'][b]>f['limits_nano_usd'][b] for b in BUCKETS):raise ValueError()
        pins=f['profile_hashes']
        if type(pins) is not dict or not pins or not all(type(k) is str and _PID.fullmatch(k) and type(v) is str and _SHA.fullmatch(v) for k,v in pins.items()):raise ValueError()
        if any(k not in profiles or profiles[k].profile_hash!=v for k,v in pins.items()):raise ValueError()
        adm=f['admission']
        if type(adm) is not dict or set(adm)!=set(BUCKETS):raise ValueError()
        for b in BUCKETS:
            if type(adm[b]) is not dict or not all(k in pins and _int(v,0,MAX_STARTS_CEILING) for k,v in adm[b].items()):raise ValueError()
        if set(pins)!={k for b in BUCKETS for k in adm[b]}:raise ValueError()
        c=f['carry_forward']
        if type(c) is not dict or set(c)!=_CARRY_KEYS or not _int(c['starts'],0,MAX_STARTS_CEILING) or not _buckets(c['settled_nano_usd']) or c['held_nano_usd']!=0:raise ValueError()
        src=c['sources']
        if type(src) is not list or not 1<=len(src)<=8:raise ValueError()
        for s in src:
            if (type(s) is not dict or set(s)!=_SOURCE_KEYS or s['kind'] not in SOURCE_KINDS or type(s['id']) is not str or not _UUID.fullmatch(s['id'])
                    or type(s['file_sha256']) is not str or not _HEX.fullmatch(s['file_sha256']) or not all(_int(s[k],0,10**7) for k in ('sequence','entries','starts','released_zero_start'))
                    or not _buckets(s['settled_nano_usd']) or s['held_nano_usd']!=0 or s['unresolved_entries']!=0
                    or s['starts']+s['released_zero_start']>s['entries'] or type(s['reference']) is not str or not _REF.fullmatch(s['reference'])):raise ValueError()
        if len({s['id'] for s in src})!=len(src) or len({s['file_sha256'] for s in src})!=len(src):raise ValueError()
        if c['starts']!=sum(s['starts'] for s in src) or any(c['settled_nano_usd'][b]!=sum(s['settled_nano_usd'][b] for s in src) for b in BUCKETS):raise ValueError()
        if any(c['settled_nano_usd'][b]>f['limits_nano_usd'][b] for b in BUCKETS):raise ValueError()
        if not _int(f['max_starts'],1,MAX_STARTS_CEILING) or not financial_plan(f,profiles)['ok']:raise ValueError()
        return f
    except (ValueError,KeyError,TypeError,UnicodeError,RecursionError,LanguageError):raise LanguageError('approval_unavailable',503) from None

def carry_forward_sha256(f):return 'sha256:'+hashlib.sha256(dumps(f['carry_forward'])).hexdigest()

def validate_state(state,f):
    """Ledger bytes bind the funding ledger id and the immutable carry-forward; entries are new starts only."""
    if type(state) is not dict or set(state)!=_STATE_KEYS or state['schema_version']!=LEDGER_SCHEMA or state['ledger_id']!=f['ledger_id']:raise ValueError()
    if state['carry_forward_sha256']!=carry_forward_sha256(f) or state['cost_basis']!=COST_BASIS or type(state['entries']) is not list:raise ValueError()
    if type(state['sequence']) is not int or state['sequence']<0:raise ValueError()
    last=0;ids=set()
    for e in state['entries']:
        if type(e) is not dict or set(e)-{'settled_at'}!=_ENTRY_KEYS or e['bucket'] not in BUCKETS or e['state'] not in STATES:raise ValueError()
        if type(e['sequence']) is not int or not last<e['sequence']<=state['sequence'] or e['entry_id'] in ids:raise ValueError()
        if type(e['profile_id']) is not str or not _PID.fullmatch(e['profile_id']) or type(e['profile_hash']) is not str or not _SHA.fullmatch(e['profile_hash']):raise ValueError()
        if not _int(e['reserved_nano_usd']) or e['count_requests'] not in (0,1) or e['model_calls'] not in (0,1) or type(e['count_requests']) is not int or type(e['model_calls']) is not int or e['model_calls']>e['count_requests']:raise ValueError()
        if e['state']=='settled' and (not _int(e['settled_estimate_nano_usd']) or e['settled_estimate_nano_usd']>e['reserved_nano_usd'] or type(e['usage']) is not dict):raise ValueError()
        if e['state']=='released' and (e['settled_estimate_nano_usd']!=0 or e['model_calls']):raise ValueError()
        last=e['sequence'];ids.add(e['entry_id'])
    return state

class FundingLedger(BudgetLedger):
    """Bound to ONE selected profile; reads and serializes the shared ledger for all profiles and buckets."""
    def __init__(self,profile,control_dir=CONTROL_DIR,*,config_hash,protected=True,profiles_path=PROFILES_PATH):
        if not isinstance(profile,Profile):raise LanguageError('profile_unavailable',503)
        self.profile=profile;self.config_hash=config_hash;self.control_dir=Path(control_dir);self.directory=self.control_dir/'ledger'
        self.path=self.directory/LEDGER_FILE;self.halt_path=self.directory/'HALTED';self.funding_path=self.control_dir/FUNDING_FILE
        self.genesis_path=self.control_dir/GENESIS_FILE
        self.protected=protected;self._faulted=False;self.profiles_path=profiles_path
    @property
    def reasoning_effort(self):return self.profile.reasoning_effort
    @property
    def profile_hash(self):return self.profile.profile_hash
    def _funding(self):
        try:
            self._check(self.control_dir,0o750,0,10001,True)
            self._check(self.directory,0o700,10001,10001,True)
            raw=self._protected_read(self.funding_path)
        except (OSError,ValueError):raise LanguageError('approval_unavailable',503) from None
        f=validate_funding(raw,load_profiles(self.profiles_path))
        if f['profile_hashes'].get(self.profile.profile_id)!=self.profile.profile_hash:raise LanguageError('approval_unavailable',503)
        return f,'sha256:'+hashlib.sha256(raw).hexdigest()
    def approval(self,reference=None):
        f,_=self._funding()
        if reference is not None and f['approval_reference']!=reference:raise LanguageError('approval_unavailable',503)
        return f
    def approval_template(self,*a,**k):raise LanguageError('approval_template_retired',409)
    def initialize(self,*a,**k):raise LanguageError('ledger_initialization_forbidden',409)
    def _load(self):
        f,fsha=self._funding()
        try:
            self._check(self.path,0o600,10001,10001)
            fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as h:raw=h.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise ValueError()
            state=validate_state(strict_json(raw),f);g=self._genesis()
            if (g is None and self.protected) or (g is not None and g!=genesis_record(state)):raise ValueError()
            return state,f,fsha
        except (OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError):raise LanguageError('ledger_unavailable',503) from None
    def _genesis(self):
        if not os.path.lexists(self.genesis_path):return None
        g=strict_json(self._protected_read(self.genesis_path))
        if type(g) is not dict or set(g)!=set(_GENESIS_KEYS) or g['schema_version']!=GENESIS_SCHEMA or type(g['created_at']) is not float:raise ValueError()
        return g
    def _read(self):return self._load()[0]
    def _summarize(self,state,f,fsha):
        e=state['entries'];c=f['carry_forward'];buckets={}
        for b in BUCKETS:
            mine=[x for x in e if x['bucket']==b]
            new=sum(x['settled_estimate_nano_usd'] for x in mine if x['state']=='settled')
            held=sum(x['reserved_nano_usd'] for x in mine if x['state'] in ('reserved','dispatched','unknown'))
            carried=c['settled_nano_usd'][b];contingency=f['contingency_nano_usd'][b];limit=f['limits_nano_usd'][b]
            buckets[b]={'limit_nano_usd':limit,'carried_settled_nano_usd':carried,'new_settled_nano_usd':new,
                'settled_usage_estimate_nano_usd':carried+new,'held_liability_nano_usd':held,'nonmodel_contingency_nano_usd':contingency,
                'available_nano_usd':limit-carried-new-held-contingency,'entries':len(mine),'new_starts':sum(x['count_requests'] for x in mine)}
        total={k:sum(buckets[b][k] for b in BUCKETS) for k in ('settled_usage_estimate_nano_usd','held_liability_nano_usd','nonmodel_contingency_nano_usd')}
        total.update(limit_nano_usd=f['total_limit_nano_usd'],available_nano_usd=f['total_limit_nano_usd']-sum(total.values()))
        admission={b:{pid:{'cap':cap,'used':sum(x['count_requests'] for x in e if x['bucket']==b and x['profile_id']==pid),}
                      for pid,cap in sorted(f['admission'][b].items())} for b in BUCKETS}
        for b in admission:
            for a in admission[b].values():a['remaining']=max(0,a['cap']-a['used'])
        new_starts=sum(x['count_requests'] for x in e);count=c['starts']+new_starts
        profiles=sorted({x['profile_id'] for x in e})
        return {'ledger_id':state['ledger_id'],'sequence':state['sequence'],'funding_sha256':fsha,'approval_reference':f['approval_reference'],
            'carry_forward_sha256':state['carry_forward_sha256'],'profile_id':self.profile.profile_id,'profile_hash':self.profile.profile_hash,
            'active_config_hash':self.config_hash,'carried_starts':c['starts'],'new_starts':new_starts,'count_requests':count,
            'max_count_requests':f['max_starts'],'count_capacity_remaining':max(0,f['max_starts']-count),'admission':admission,
            'buckets':buckets,'total':total,'new_generation_calls':sum(x['model_calls'] for x in e),
            'new_usage_totals_by_profile':{p:{k:sum((x['usage'] or {}).get(k,0) for x in e if x['profile_id']==p)
                for k in ('input_tokens','output_tokens','reasoning_tokens_within_output')} for p in profiles},
            'states':{s:sum(1 for x in e if x['state']==s) for s in STATES},
            'unresolved':any(x['state'] in ('reserved','dispatched','unknown') for x in e),
            'cost_basis':COST_BASIS,'count_endpoint_price':COUNT_ENDPOINT_PRICE,'contingency_basis':CONTINGENCY_BASIS,
            'control_directory_realpath':str(self.control_dir.resolve())}
    def summary(self):
        with self._lock():return self._summarize(*self._load())
    def _admit(self,s,bucket):
        a=s['admission'][bucket].get(self.profile.profile_id)
        if a is None:raise LanguageError('profile_not_admitted',503)
        if a['remaining']<=0 or s['count_capacity_remaining']<=0:raise LanguageError('count_ceiling_reached',503)
    def reserve(self,bucket,payload_hash):
        if bucket not in BUCKETS:raise LanguageError('invalid_bucket')
        with self._lock():
            state,f,fsha=self._load();s=self._summarize(state,f,fsha)
            if s['unresolved']:raise LanguageError('unresolved_liability',503)
            self._admit(s,bucket);amount=reservation(self.profile)
            if s['buckets'][bucket]['available_nano_usd']<amount or s['total']['available_nano_usd']<amount:raise LanguageError('budget_exhausted',503)
            eid=str(uuid.uuid4());state['sequence']+=1
            state['entries'].append({'entry_id':eid,'sequence':state['sequence'],'bucket':bucket,'state':'reserved',
                'created_at':time.time(),'reserved_nano_usd':amount,'settled_estimate_nano_usd':None,'payload_hash':payload_hash,
                'profile_id':self.profile.profile_id,'profile_hash':self.profile.profile_hash,'config_hash':self.config_hash,
                'counted_input_tokens':None,'count_requests':0,'model_calls':0,'usage':None,'terminal_code':None})
            self._write(state);return eid
    def _update(self,eid,mutate,precheck=None):
        with self._lock():
            state,f,fsha=self._load();entry=next((x for x in state['entries'] if x['entry_id']==eid),None)
            if entry is None:raise LanguageError('ledger_entry_missing',503)
            # An entry is only ever advanced by a ledger bound to the profile that reserved it.
            if entry['profile_hash']!=self.profile.profile_hash or entry['profile_id']!=self.profile.profile_id:raise LanguageError('accounting_state',503)
            if precheck is not None:precheck(self._summarize(state,f,fsha),entry)
            mutate(entry);state['sequence']+=1;self._write(state)
    def count_dispatched(self,eid):
        # Durable admission recheck immediately before transport; the attempt is persisted first and never refunded.
        def update(e):
            if e['state']!='reserved' or e['count_requests']!=0:raise LanguageError('accounting_state',503)
            e['count_requests']=1
        self._update(eid,update,lambda s,e:self._admit(s,e['bucket']))
    def counted(self,eid,tokens):
        amount=reservation(self.profile,tokens)
        def update(e):
            if e['state']!='reserved' or e['count_requests']!=1:raise LanguageError('accounting_state',503)
            e.update(counted_input_tokens=tokens,reserved_nano_usd=amount)
        self._update(eid,update)
    def dispatched(self,eid):
        # A generation is only ever recorded after its durable Count start (one start = one Count + <=1 generation).
        def update(e):
            if e['state']!='reserved' or e['counted_input_tokens'] is None or e['count_requests']!=1:raise LanguageError('accounting_state',503)
            e.update(state='dispatched',model_calls=1)
        self._update(eid,update)
    def settle(self,eid,usage,code):
        cost=usage_cost(usage,self.profile)
        def update(e):
            if e['state']!='dispatched' or cost>e['reserved_nano_usd']:raise LanguageError('accounting_state',503)
            e.update(state='settled',usage=copy.deepcopy(usage),settled_estimate_nano_usd=cost,terminal_code=code,settled_at=time.time())
        self._update(eid,update)

def genesis_record(state):
    return {'schema_version':GENESIS_SCHEMA,'ledger_id':state['ledger_id'],'created_at':state['created_at'],'carry_forward_sha256':state['carry_forward_sha256']}

def initialize_ledger(control_dir=CONTROL_DIR,*,protected=True,profiles_path=PROFILES_PATH):
    """One-shot creation of the empty new-entries ledger. Operator CLI only; never reachable from HTTP or the service."""
    raw_profiles=load_profiles(profiles_path)
    probe=FundingLedger(next(iter(raw_profiles.values())),control_dir,config_hash=None,protected=protected,profiles_path=profiles_path)
    try:raw=probe._protected_read(probe.funding_path)
    except (OSError,ValueError):raise LanguageError('approval_unavailable',503) from None
    f=validate_funding(raw,raw_profiles)
    ledger=FundingLedger(raw_profiles[sorted(f['profile_hashes'])[0]],control_dir,config_hash=None,protected=protected,profiles_path=profiles_path)
    with ledger._lock():
        # After the protected funding step sealed the genesis, initialization is refused forever.
        if os.path.lexists(ledger.genesis_path):raise LanguageError('ledger_initialization_forbidden',409)
        if os.path.lexists(ledger.path):raise LanguageError('ledger_exists',409)
        if set(os.listdir(ledger.directory))-{'budget.lock','job.lock'}:raise LanguageError('ledger_initialization_forbidden',409)
        state={'schema_version':LEDGER_SCHEMA,'ledger_id':f['ledger_id'],'carry_forward_sha256':carry_forward_sha256(f),
            'created_at':time.time(),'sequence':0,'entries':[],'cost_basis':COST_BASIS}
        ledger._write(state)
        return {'status':'initialized','ledger_id':f['ledger_id'],'carry_forward_sha256':state['carry_forward_sha256'],
                'funding_sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'entries':0,'genesis':genesis_record(state)}
