"""One durable IA authority. Holds are temporary; settled estimates are not invoices."""
from __future__ import annotations
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from .ia_language import LanguageError, dumps, strict_json

CONTROL_DIR=Path('/run/haic-language-control')
MODEL='gpt-6.1-terra'
MAX_INPUT=12288
MAX_OUTPUT=2048
NONMODEL_CONTINGENCY_NANO=2000000000
# Official global Standard short-context USD/1M, fetched 2026-11-13.
# One nano-USD per token = $0.001 per million tokens.
RATES={'uncached_input':1000,'cached_input':50,'cache_write_30m':1250,'output':5000}
POLICY={'schema_version':'ia-language-budget/1','model':MODEL,'effort':'low','service_tier':'default',
        'max_input_tokens':MAX_INPUT,'max_output_tokens':MAX_OUTPUT,'rates_nano_usd_per_token':RATES,
        'reservation_cushion_percent':20,'cache_mode':'explicit_without_breakpoints',
        'pricing_source':'https://developers.openai.com/api/docs/pricing','pricing_checked':'2026-11-13',
        'cost_basis':'provider_reported_usage_at_documented_rates_not_invoice',
        'count_endpoint_price':'not_published_in_fetched_pricing_documentation',
        'limits_nano_usd':{'test':15000000000,'demo':10000000000},
        'contingency_nano_usd':{'test':NONMODEL_CONTINGENCY_NANO,'demo':0},
        'contingency_basis':'qualified_fixed_count_or_nonmodel_allowance_not_a_fee_bound_or_settled_cost',
        'qualification_count_limit':3}
POLICY_HASH='sha256:'+hashlib.sha256(dumps(POLICY)).hexdigest()
# Count admission is outside POLICY so the reviewed financial policy hash is unchanged.
# Finite ALLOWABLE range for root-reviewed approval metadata, not an approved ceiling: every
# actual ceiling still comes from a separately reviewed protected approval (record-2 helper: 7).
# Dollar limits, rates, contingency and unknown-usage holds bound spend independently.
MAX_COUNT_CEILING=256
# The one reviewed financial-continuity transition. The active hash is runtime
# metadata in the protected record, never a self-referential source constant.
ADOPTION_FILE='config-adoption.json'
ADOPTION_SCHEMA='ia-language-config-adoption/1'
ADOPTION_ORIGIN_CONFIG_HASH='sha256:83d2b631088c95239a2eccee151e6bab33432e4c699c29c9de2545689f87113b'
ADOPTION_LEDGER_ID='7483357b-58a8-482c-8d17-b7b6a68fc3ba'
ADOPTION_CHECKPOINT={'sequence':15,'count_requests':3,'settled_nano_usd':27539000,'held_nano_usd':0,'unresolved':False}
_SHA=re.compile(r'sha256:[0-9a-f]{64}')
_V1_KEYS={'schema_version','approved','approval_reference','limits_nano_usd','provider','model','policy_hash','config_hash','stage'}
_V2_KEYS=_V1_KEYS|{'adoption_record_sha256','max_count_requests'}
_RECORD_KEYS={'schema_version','ledger_id','origin_config_hash','active_config_hash','policy_hash','catalog_digest',
    'original_approval_reference','transition_reference','source_component_sha256','image_digest','review_receipt_sha256','checkpoint'}

# The one reviewed second transition: exactly the committed first record's active
# configuration to one new active configuration, same ledger and financial origin.
# The new active hash is runtime metadata in record 2, never a source constant.
ADOPTION2_FILE='config-adoption-2.json'
ADOPTION2_SCHEMA='ia-language-config-adoption/2'
ADOPTION1_RECORD_SHA256='sha256:6500cdfc254776678ba183ad2881d020cabef399742450ef2b10f234b65d849a'
ADOPTION1_ACTIVE_CONFIG_HASH='sha256:c0d16d5887152871c7b2a40781c24133bdf82c22ecbdf6169d49e55ba24cbcd1'
ADOPTION1_MAX_COUNT_REQUESTS=6
ADOPTION2_CHECKPOINT={'sequence':30,'count_requests':6,'settled_nano_usd':55078000,'held_nano_usd':0,'unresolved':False}
ADOPTION2_MAX_COUNT_REQUESTS=7
_V3_KEYS=_V2_KEYS|{'adoption2_record_sha256'}
_RECORD2_KEYS={'schema_version','ledger_id','origin_config_hash','previous_active_config_hash','active_config_hash',
    'previous_adoption_record_sha256','policy_hash','catalog_digest','original_approval_reference','transition_reference',
    'source_component_sha256','image_digest','review_receipt_sha256','checkpoint'}

# The one reviewed third transition: exactly record 2's committed active configuration to one new
# active configuration, same ledger and financial origin, at the exhausted 7-count checkpoint.
# Its fixed initial ceiling stays 7 (no new headroom). The new active hash is runtime metadata in
# record 3, never a source constant; record 2 and its active hash are fixed reviewed pins.
ADOPTION3_FILE='config-adoption-3.json'
ADOPTION3_SCHEMA='ia-language-config-adoption/3'
ADOPTION2_RECORD_SHA256='sha256:b9658c7dd729cda749c51433cf62afcbd7fc7ae491d9f0189018c34427476612'
ADOPTION2_ACTIVE_CONFIG_HASH='sha256:82a17a69839d94d8f83b59c6627a27a3f5cc23ed0385b04cd76b8d8dea26264a'
ADOPTION3_CHECKPOINT={'sequence':35,'count_requests':7,'settled_nano_usd':63617000,'held_nano_usd':0,'unresolved':False}
ADOPTION3_BUDGET_SHA256='sha256:e54e30ce03d8db72982e4cd8dbf5bb24712b8fbacd002d12dedad4c7279ae888'
ADOPTION3_MAX_COUNT_REQUESTS=7
_V4_KEYS=_V3_KEYS|{'adoption3_record_sha256'}
_RECORD3_KEYS=_RECORD2_KEYS

# The one reviewed fourth transition: exactly record 3's committed active configuration (829) to one
# new active configuration, same ledger and financial origin, at the exhausted 127-count checkpoint.
# Its fixed initial ceiling stays 127 (no new headroom). The new active hash is runtime metadata in
# record 4, never a source constant; record 3, its active hash and the checkpoint budget are fixed pins.
ADOPTION4_FILE='config-adoption-4.json'
ADOPTION4_SCHEMA='ia-language-config-adoption/4'
ADOPTION3_RECORD_SHA256='sha256:d89e7782dd312fd00390da4f661b2b852ed0457b644dca49f0bf4c0724703fc0'
ADOPTION3_ACTIVE_CONFIG_HASH='sha256:829d32a72679282b91c8232e29f9a7786a1293b83f8791e208caba79340d8739'
ADOPTION4_CHECKPOINT={'sequence':635,'count_requests':127,'settled_nano_usd':1101867000,'held_nano_usd':0,'unresolved':False}
ADOPTION4_BUDGET_SHA256='sha256:9746c445dcbb36e95a9eb7c40093d134bc0880410b14c087941fc5e0050dfffe'
ADOPTION4_MAX_COUNT_REQUESTS=127
# Records 1-3 were committed under this value-free catalog. Under approval v5 they are exact byte
# pins, so their catalog binding is historical; only record 4 binds the running catalog.
ADOPTION_HISTORICAL_CATALOG_DIGEST='sha256:cc6467496100f8aff2f54096b4f4daf798f296fe6e1e75403200d66df4cb00eb'
_V5_KEYS=_V4_KEYS|{'adoption4_record_sha256'}
_RECORD4_KEYS=_RECORD2_KEYS
# v5 positional lineage of the preserved history: (stamp, exclusive lower, inclusive upper entry sequence).
_V5_LINEAGE=((None,0,ADOPTION_CHECKPOINT['sequence']),
    (ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION_CHECKPOINT['sequence'],ADOPTION2_CHECKPOINT['sequence']),
    (ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION2_CHECKPOINT['sequence'],ADOPTION3_CHECKPOINT['sequence']),
    (ADOPTION3_ACTIVE_CONFIG_HASH,ADOPTION3_CHECKPOINT['sequence'],ADOPTION4_CHECKPOINT['sequence']))

def _sha(v):return type(v) is str and _SHA.fullmatch(v) is not None
def _ref(v):return type(v) is str and bool(v.strip()) and len(v)<=500
def _ceiling(v):return type(v) is int and 1<=v<=MAX_COUNT_CEILING

def count_ceiling(a):
    """Cumulative count_requests across both buckets. Qualification stays capped at 3;
    evaluation is only bounded admission and always needs an explicit finite ceiling."""
    if a['stage']=='qualification':return min(POLICY['qualification_count_limit'],a.get('max_count_requests',POLICY['qualification_count_limit']))
    return a['max_count_requests']

def adoption_record(*,active_config_hash,catalog_digest,original_approval_reference,transition_reference,
        source_component_sha256,image_digest,review_receipt_sha256,budget_sha256):
    return {'schema_version':ADOPTION_SCHEMA,'ledger_id':ADOPTION_LEDGER_ID,'origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,
        'active_config_hash':active_config_hash,'policy_hash':POLICY_HASH,'catalog_digest':catalog_digest,
        'original_approval_reference':original_approval_reference,'transition_reference':transition_reference,
        'source_component_sha256':source_component_sha256,'image_digest':image_digest,'review_receipt_sha256':review_receipt_sha256,
        'checkpoint':dict(ADOPTION_CHECKPOINT,budget_sha256=budget_sha256)}

def approval_v2(reference,active_config_hash,record_sha256,max_count_requests):
    return {'schema_version':'ia-language-approval/2','approved':True,'approval_reference':reference,
        'limits_nano_usd':copy.deepcopy(POLICY['limits_nano_usd']),'provider':'openai','model':MODEL,'policy_hash':POLICY_HASH,
        'config_hash':active_config_hash,'stage':'evaluation','adoption_record_sha256':record_sha256,'max_count_requests':max_count_requests}

def validate_adoption_record(raw,approval,config_hash,catalog_digest):
    """Exact single origin-to-active pair; raises ValueError on any mismatch."""
    r=strict_json(raw)
    if type(r) is not dict or set(r)!=_RECORD_KEYS or raw!=dumps(r):raise ValueError()
    cp=r['checkpoint']
    if (r['schema_version']!=ADOPTION_SCHEMA or r['ledger_id']!=ADOPTION_LEDGER_ID or r['origin_config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH
            or not _sha(config_hash) or r['active_config_hash']!=config_hash or config_hash==ADOPTION_ORIGIN_CONFIG_HASH
            or r['policy_hash']!=POLICY_HASH or not _sha(catalog_digest) or r['catalog_digest']!=catalog_digest
            or r['original_approval_reference']!=approval['approval_reference'] or not _ref(r['transition_reference'])
            or not all(_sha(r[k]) for k in ('source_component_sha256','image_digest','review_receipt_sha256'))
            or type(cp) is not dict or set(cp)!=set(ADOPTION_CHECKPOINT)|{'budget_sha256'} or not _sha(cp['budget_sha256'])
            or any(type(cp[k]) is not type(v) or cp[k]!=v for k,v in ADOPTION_CHECKPOINT.items())
            or 'sha256:'+hashlib.sha256(raw).hexdigest()!=approval['adoption_record_sha256']):raise ValueError()
    return r

def adoption2_record(*,active_config_hash,catalog_digest,original_approval_reference,transition_reference,
        source_component_sha256,image_digest,review_receipt_sha256,budget_sha256):
    return {'schema_version':ADOPTION2_SCHEMA,'ledger_id':ADOPTION_LEDGER_ID,'origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,
        'previous_active_config_hash':ADOPTION1_ACTIVE_CONFIG_HASH,'active_config_hash':active_config_hash,
        'previous_adoption_record_sha256':ADOPTION1_RECORD_SHA256,'policy_hash':POLICY_HASH,'catalog_digest':catalog_digest,
        'original_approval_reference':original_approval_reference,'transition_reference':transition_reference,
        'source_component_sha256':source_component_sha256,'image_digest':image_digest,'review_receipt_sha256':review_receipt_sha256,
        'checkpoint':dict(ADOPTION2_CHECKPOINT,budget_sha256=budget_sha256)}

def approval_v3(reference,active_config_hash,record2_sha256,max_count_requests):
    a=approval_v2(reference,active_config_hash,ADOPTION1_RECORD_SHA256,max_count_requests)
    a.update(schema_version='ia-language-approval/3',adoption2_record_sha256=record2_sha256);return a

def validate_adoption2_record(raw,approval,config_hash,catalog_digest):
    """Exact single previous-active-to-new-active pair; raises ValueError on any mismatch."""
    r=strict_json(raw)
    if type(r) is not dict or set(r)!=_RECORD2_KEYS or raw!=dumps(r):raise ValueError()
    cp=r['checkpoint']
    if (r['schema_version']!=ADOPTION2_SCHEMA or r['ledger_id']!=ADOPTION_LEDGER_ID or r['origin_config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH
            or r['previous_active_config_hash']!=ADOPTION1_ACTIVE_CONFIG_HASH or r['previous_adoption_record_sha256']!=ADOPTION1_RECORD_SHA256
            or not _sha(config_hash) or r['active_config_hash']!=config_hash or config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH)
            or r['policy_hash']!=POLICY_HASH or not _sha(catalog_digest) or r['catalog_digest']!=catalog_digest
            or r['original_approval_reference']!=approval['approval_reference'] or not _ref(r['transition_reference'])
            or not all(_sha(r[k]) for k in ('source_component_sha256','image_digest','review_receipt_sha256'))
            or type(cp) is not dict or set(cp)!=set(ADOPTION2_CHECKPOINT)|{'budget_sha256'} or not _sha(cp['budget_sha256'])
            or any(type(cp[k]) is not type(v) or cp[k]!=v for k,v in ADOPTION2_CHECKPOINT.items())
            or 'sha256:'+hashlib.sha256(raw).hexdigest()!=approval['adoption2_record_sha256']):raise ValueError()
    return r

def adoption3_record(*,active_config_hash,catalog_digest,original_approval_reference,transition_reference,
        source_component_sha256,image_digest,review_receipt_sha256,budget_sha256):
    return {'schema_version':ADOPTION3_SCHEMA,'ledger_id':ADOPTION_LEDGER_ID,'origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,
        'previous_active_config_hash':ADOPTION2_ACTIVE_CONFIG_HASH,'active_config_hash':active_config_hash,
        'previous_adoption_record_sha256':ADOPTION2_RECORD_SHA256,'policy_hash':POLICY_HASH,'catalog_digest':catalog_digest,
        'original_approval_reference':original_approval_reference,'transition_reference':transition_reference,
        'source_component_sha256':source_component_sha256,'image_digest':image_digest,'review_receipt_sha256':review_receipt_sha256,
        'checkpoint':dict(ADOPTION3_CHECKPOINT,budget_sha256=budget_sha256)}

def approval_v4(reference,active_config_hash,record3_sha256,max_count_requests):
    a=approval_v3(reference,active_config_hash,ADOPTION2_RECORD_SHA256,max_count_requests)
    a.update(schema_version='ia-language-approval/4',adoption3_record_sha256=record3_sha256);return a

def validate_adoption3_record(raw,approval,config_hash,catalog_digest):
    """Exact single record-2-active-to-new-active pair; raises ValueError on any mismatch."""
    r=strict_json(raw)
    if type(r) is not dict or set(r)!=_RECORD3_KEYS or raw!=dumps(r):raise ValueError()
    cp=r['checkpoint']
    if (r['schema_version']!=ADOPTION3_SCHEMA or r['ledger_id']!=ADOPTION_LEDGER_ID or r['origin_config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH
            or r['previous_active_config_hash']!=ADOPTION2_ACTIVE_CONFIG_HASH or r['previous_adoption_record_sha256']!=ADOPTION2_RECORD_SHA256
            or not _sha(config_hash) or r['active_config_hash']!=config_hash
            or config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH)
            or r['policy_hash']!=POLICY_HASH or not _sha(catalog_digest) or r['catalog_digest']!=catalog_digest
            or r['original_approval_reference']!=approval['approval_reference'] or not _ref(r['transition_reference'])
            or not all(_sha(r[k]) for k in ('source_component_sha256','image_digest','review_receipt_sha256'))
            or type(cp) is not dict or set(cp)!=set(ADOPTION3_CHECKPOINT)|{'budget_sha256'} or cp['budget_sha256']!=ADOPTION3_BUDGET_SHA256
            or any(type(cp[k]) is not type(v) or cp[k]!=v for k,v in ADOPTION3_CHECKPOINT.items())
            or 'sha256:'+hashlib.sha256(raw).hexdigest()!=approval['adoption3_record_sha256']):raise ValueError()
    return r

def adoption4_record(*,active_config_hash,catalog_digest,original_approval_reference,transition_reference,
        source_component_sha256,image_digest,review_receipt_sha256,budget_sha256):
    return {'schema_version':ADOPTION4_SCHEMA,'ledger_id':ADOPTION_LEDGER_ID,'origin_config_hash':ADOPTION_ORIGIN_CONFIG_HASH,
        'previous_active_config_hash':ADOPTION3_ACTIVE_CONFIG_HASH,'active_config_hash':active_config_hash,
        'previous_adoption_record_sha256':ADOPTION3_RECORD_SHA256,'policy_hash':POLICY_HASH,'catalog_digest':catalog_digest,
        'original_approval_reference':original_approval_reference,'transition_reference':transition_reference,
        'source_component_sha256':source_component_sha256,'image_digest':image_digest,'review_receipt_sha256':review_receipt_sha256,
        'checkpoint':dict(ADOPTION4_CHECKPOINT,budget_sha256=budget_sha256)}

def approval_v5(reference,active_config_hash,record4_sha256,max_count_requests):
    a=approval_v4(reference,active_config_hash,ADOPTION3_RECORD_SHA256,max_count_requests)
    a.update(schema_version='ia-language-approval/5',adoption4_record_sha256=record4_sha256);return a

def validate_adoption4_record(raw,approval,config_hash,catalog_digest):
    """Exact single record-3-active-to-new-active pair; raises ValueError on any mismatch."""
    r=strict_json(raw)
    if type(r) is not dict or set(r)!=_RECORD4_KEYS or raw!=dumps(r):raise ValueError()
    cp=r['checkpoint']
    if (r['schema_version']!=ADOPTION4_SCHEMA or r['ledger_id']!=ADOPTION_LEDGER_ID or r['origin_config_hash']!=ADOPTION_ORIGIN_CONFIG_HASH
            or r['previous_active_config_hash']!=ADOPTION3_ACTIVE_CONFIG_HASH or r['previous_adoption_record_sha256']!=ADOPTION3_RECORD_SHA256
            or not _sha(config_hash) or r['active_config_hash']!=config_hash
            or config_hash in (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION3_ACTIVE_CONFIG_HASH)
            or r['policy_hash']!=POLICY_HASH or not _sha(catalog_digest) or r['catalog_digest']!=catalog_digest
            or r['original_approval_reference']!=approval['approval_reference'] or not _ref(r['transition_reference'])
            or not all(_sha(r[k]) for k in ('source_component_sha256','image_digest','review_receipt_sha256'))
            or type(cp) is not dict or set(cp)!=set(ADOPTION4_CHECKPOINT)|{'budget_sha256'} or cp['budget_sha256']!=ADOPTION4_BUDGET_SHA256
            or any(type(cp[k]) is not type(v) or cp[k]!=v for k,v in ADOPTION4_CHECKPOINT.items())
            or 'sha256:'+hashlib.sha256(raw).hexdigest()!=approval['adoption4_record_sha256']):raise ValueError()
    return r

def reservation(input_tokens=MAX_INPUT):
    if type(input_tokens) is not int or not 0<input_tokens<=MAX_INPUT:raise LanguageError('input_token_limit')
    base=input_tokens*RATES['uncached_input']+MAX_OUTPUT*RATES['output']
    return (base*120+99)//100

def parse_usage(raw):
    """Input is inclusive of cache buckets; reasoning is a subset of output."""
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
    if i>MAX_INPUT or o>MAX_OUTPUT:raise LanguageError('usage_exceeds_limits')
    return {'input_tokens':i,'uncached_input_tokens':i-cached-writes,'cached_input_tokens':cached,
            'cache_write_tokens':writes,'output_tokens':o,'reasoning_tokens_within_output':out['reasoning_tokens'],
            'total_tokens':total}

def usage_cost(usage):
    return (usage['uncached_input_tokens']*RATES['uncached_input']+
            usage['cached_input_tokens']*RATES['cached_input']+
            usage['cache_write_tokens']*RATES['cache_write_30m']+usage['output_tokens']*RATES['output'])

class BudgetLedger:
    def __init__(self,config_hash,control_dir=CONTROL_DIR,*,protected=True,catalog_digest=None):
        self.config_hash=config_hash;self.control_dir=Path(control_dir);self.directory=self.control_dir/'ledger'
        self.path=self.directory/'budget.json';self.protected=protected;self._faulted=False
        self.halt_path=self.directory/'HALTED';self.adoption_path=self.control_dir/ADOPTION_FILE
        self.adoption2_path=self.control_dir/ADOPTION2_FILE
        self.adoption3_path=self.control_dir/ADOPTION3_FILE
        self.adoption4_path=self.control_dir/ADOPTION4_FILE
        self.catalog_digest=catalog_digest
    def _check(self,p,mode,owner,group=None,directory=False):
        s=p.lstat()
        if stat.S_ISLNK(s.st_mode) or (not stat.S_ISDIR(s.st_mode) if directory else not stat.S_ISREG(s.st_mode)):raise LanguageError('control_permissions',503)
        if self.protected and (stat.S_IMODE(s.st_mode)!=mode or s.st_uid!=owner or (group is not None and s.st_gid!=group)):raise LanguageError('control_permissions',503)
    def _protected_read(self,p):
        self._check(p,0o440,0,10001)
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as f:raw=f.read(16385)
        if len(raw)>16384:raise ValueError()
        return raw
    def approval(self,reference=None):return self._authority(reference)[0]
    def _authority(self,reference=None):
        """Return (approval, adoption record or None) from one validated read; no shared instance state."""
        try:
            self._check(self.control_dir,0o750,0,10001,True)
            self._check(self.directory,0o700,10001,10001,True)
            a=strict_json(self._protected_read(self.control_dir/'approval.json'))
            v=a['schema_version'] if type(a) is dict else None
            keys=set(a) if type(a) is dict else set()
            if (not (v=='ia-language-approval/1' and (keys==_V1_KEYS or keys==_V1_KEYS|{'max_count_requests'}))
                    and not (v=='ia-language-approval/2' and keys==_V2_KEYS) and not (v=='ia-language-approval/3' and keys==_V3_KEYS)
                    and not (v=='ia-language-approval/4' and keys==_V4_KEYS) and not (v=='ia-language-approval/5' and keys==_V5_KEYS)):raise ValueError()
            if a['approved'] is not True or a['provider']!='openai' or a['model']!=MODEL or a['limits_nano_usd']!=POLICY['limits_nano_usd'] or a['policy_hash']!=POLICY_HASH or a['config_hash']!=self.config_hash or a['stage'] not in ('qualification','evaluation') or not _ref(a['approval_reference']) or (reference is not None and a['approval_reference']!=reference):raise ValueError()
            if ('max_count_requests' in a or a['stage']=='evaluation') and not _ceiling(a.get('max_count_requests')):raise ValueError()
            if v=='ia-language-approval/1':
                # A staged or committed adoption record disables every legacy authority.
                if any(os.path.lexists(p) for p in (self.adoption_path,self.adoption2_path,self.adoption3_path,self.adoption4_path)):raise ValueError()
                return a,None
            if a['stage']!='evaluation' or not _sha(a['adoption_record_sha256']):raise ValueError()
            if v=='ia-language-approval/2':
                # A staged or committed second record disables the first-transition authority.
                if any(os.path.lexists(p) for p in (self.adoption2_path,self.adoption3_path,self.adoption4_path)):raise ValueError()
                return a,validate_adoption_record(self._protected_read(self.adoption_path),a,self.config_hash,self.catalog_digest)
            if a['adoption_record_sha256']!=ADOPTION1_RECORD_SHA256 or not _sha(a['adoption2_record_sha256']):raise ValueError()
            # Under v5 records 1-3 bind their committed (historical) catalog; earlier authorities are unchanged.
            historical=ADOPTION_HISTORICAL_CATALOG_DIGEST if v=='ia-language-approval/5' else self.catalog_digest
            first=validate_adoption_record(self._protected_read(self.adoption_path),a,ADOPTION1_ACTIVE_CONFIG_HASH,historical)
            if v=='ia-language-approval/3':
                # v3: the immutable first record (exact pinned bytes) and record 2 must both bind.
                # A staged or committed third record disables the second-transition authority.
                if os.path.lexists(self.adoption3_path) or os.path.lexists(self.adoption4_path):raise ValueError()
                second=validate_adoption2_record(self._protected_read(self.adoption2_path),a,self.config_hash,self.catalog_digest)
                return a,dict(second,first_transition_reference=first['transition_reference'])
            # v4: records 1 and 2 are exact reviewed pins (their active hashes c0d/82a); record 3 binds the running config.
            if a['adoption2_record_sha256']!=ADOPTION2_RECORD_SHA256 or not _sha(a['adoption3_record_sha256']):raise ValueError()
            second=validate_adoption2_record(self._protected_read(self.adoption2_path),a,ADOPTION2_ACTIVE_CONFIG_HASH,historical)
            if v=='ia-language-approval/4':
                # A staged or committed fourth record disables the third-transition authority.
                if os.path.lexists(self.adoption4_path):raise ValueError()
                third=validate_adoption3_record(self._protected_read(self.adoption3_path),a,self.config_hash,self.catalog_digest)
                return a,dict(third,first_transition_reference=first['transition_reference'],second_transition_reference=second['transition_reference'])
            # v5: records 1-3 are exact reviewed pins (active hashes c0d/82a/829); record 4 binds the running config and catalog.
            if a['adoption3_record_sha256']!=ADOPTION3_RECORD_SHA256 or not _sha(a['adoption4_record_sha256']):raise ValueError()
            third=validate_adoption3_record(self._protected_read(self.adoption3_path),a,ADOPTION3_ACTIVE_CONFIG_HASH,historical)
            fourth=validate_adoption4_record(self._protected_read(self.adoption4_path),a,self.config_hash,self.catalog_digest)
            return a,dict(fourth,first_transition_reference=first['transition_reference'],second_transition_reference=second['transition_reference'],
                third_transition_reference=third['transition_reference'])
        except (OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError):raise LanguageError('approval_unavailable',503) from None
    def approval_template(self,reference,stage='qualification',max_count_requests=None):
        a={'schema_version':'ia-language-approval/1','approved':True,'approval_reference':reference,
                'limits_nano_usd':POLICY['limits_nano_usd'],'provider':'openai','model':MODEL,
                'policy_hash':POLICY_HASH,'config_hash':self.config_hash,'stage':stage}
        if stage=='evaluation' or max_count_requests is not None:
            a['max_count_requests']=POLICY['qualification_count_limit']*2 if max_count_requests is None else max_count_requests
        return a
    @contextmanager
    def _lock(self):
        fd=None
        try:
            self.approval()
            fd=os.open(self.directory/'budget.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self._faulted or self.halt_path.exists():raise LanguageError('accounting_halted',503)
            yield
        except BlockingIOError:raise LanguageError('accounting_busy',409) from None
        except OSError:raise LanguageError('accounting_unavailable',503) from None
        finally:
            if fd is not None:os.close(fd)
    def acquire_job(self):
        self.approval()
        if self._faulted or self.halt_path.exists():raise LanguageError('accounting_halted',503)
        try:
            fd=os.open(self.directory/'job.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BaseException:os.close(fd);raise
            return fd
        except BlockingIOError:raise LanguageError('busy',409) from None
        except OSError:raise LanguageError('accounting_unavailable',503) from None
    @staticmethod
    def release_job(fd):os.close(fd)
    def _read(self):
        try:
            a,adopted=self._authority()
            self._check(self.path,0o600,10001,10001)
            fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as f:state=strict_json(f.read(4*1024*1024+1))
            # Adopted authority reads the unchanged origin header; ordinary authority is same-config.
            origin=adopted['origin_config_hash'] if adopted else self.config_hash
            if state['schema_version']!='ia-language-ledger/1' or state['policy_hash']!=POLICY_HASH or state['config_hash']!=origin or state['limits_nano_usd']!=POLICY['limits_nano_usd'] or not isinstance(state['entries'],list):raise ValueError()
            if state['approval_reference']!=a['approval_reference'] or (adopted and state['ledger_id']!=adopted['ledger_id']):raise ValueError()
            previous=adopted.get('previous_active_config_hash') if adopted else None
            fourth=bool(adopted) and 'third_transition_reference' in adopted
            third=bool(adopted) and 'second_transition_reference' in adopted and not fourth
            for e in state['entries']:
                if e['bucket'] not in ('test','demo') or e['state'] not in ('reserved','dispatched','unknown','settled','released') or type(e['reserved_nano_usd']) is not int or e['reserved_nano_usd']<0:raise ValueError()
                if fourth:
                    # v5 lineage is positional: the preserved origin/c0d/82a/829 ranges end at sequence 635; new active seq>635.
                    stamp=e.get('config_hash');seq=e['sequence']
                    if type(seq) is not int or (stamp is None and 'config_hash' in e):raise ValueError()
                    if not (any(stamp==s and lo<seq<=hi for s,lo,hi in _V5_LINEAGE)
                            or (stamp==self.config_hash and seq>ADOPTION4_CHECKPOINT['sequence'])):raise ValueError()
                elif third:
                    # v4 lineage is positional: unstamped origin seq<=15, c0d 15<seq<=30, 82a 30<seq<=35, new active seq>35.
                    stamp=e.get('config_hash');seq=e['sequence']
                    if type(seq) is not int or (stamp is None and ('config_hash' in e or seq>ADOPTION_CHECKPOINT['sequence'])):raise ValueError()
                    if stamp is not None and not ((stamp==ADOPTION1_ACTIVE_CONFIG_HASH and ADOPTION_CHECKPOINT['sequence']<seq<=ADOPTION2_CHECKPOINT['sequence'])
                            or (stamp==ADOPTION2_ACTIVE_CONFIG_HASH and ADOPTION2_CHECKPOINT['sequence']<seq<=ADOPTION3_CHECKPOINT['sequence'])
                            or (stamp==self.config_hash and seq>ADOPTION3_CHECKPOINT['sequence'])):raise ValueError()
                # Unstamped historical entries derive the origin header; new entries carry their active config.
                elif e.get('config_hash',origin) not in ((origin,self.config_hash) if previous is None else (origin,previous,self.config_hash)):raise ValueError()
                if previous is not None and not third and not fourth:
                    # Lineage is positional: unstamped origin entries end at checkpoint 1, previous-active
                    # entries at checkpoint 2, and only later entries carry the new active configuration.
                    stamp=e.get('config_hash');seq=e['sequence']
                    if type(seq) is not int or (stamp is None and ('config_hash' in e or seq>ADOPTION_CHECKPOINT['sequence'])):raise ValueError()
                    if stamp==origin or (stamp==previous and not ADOPTION_CHECKPOINT['sequence']<seq<=ADOPTION2_CHECKPOINT['sequence']):raise ValueError()
                    if stamp==self.config_hash and seq<=ADOPTION2_CHECKPOINT['sequence']:raise ValueError()
                if type(e.get('count_requests',0)) is not int or e.get('count_requests',0) not in (0,1):raise ValueError()
                if e['state']=='settled' and (type(e['settled_estimate_nano_usd']) is not int or e['settled_estimate_nano_usd']<0 or e['settled_estimate_nano_usd']>e['reserved_nano_usd']):raise ValueError()
            return state
        except (OSError,ValueError,KeyError,TypeError):raise LanguageError('ledger_unavailable',503) from None
    def _write(self,state):
        tmp=self.directory/('.budget-'+uuid.uuid4().hex)
        fd=None
        try:
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:
                fd=None;f.write(dumps(state));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
            dfd=os.open(self.directory,os.O_RDONLY)
            try:os.fsync(dfd)
            finally:os.close(dfd)
        except OSError:
            self._faulted=True
            # A shared halt marker prevents another process from treating a failed
            # settlement/write as permission to spend. Never remove it automatically.
            try:
                hfd=os.open(self.halt_path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
                try:os.fsync(hfd)
                finally:os.close(hfd)
                dfd=os.open(self.directory,os.O_RDONLY)
                try:os.fsync(dfd)
                finally:os.close(dfd)
            except OSError:pass
            raise LanguageError('accounting_storage_failure',503) from None
        finally:
            if fd is not None:os.close(fd)
            try:tmp.unlink(missing_ok=True)
            except OSError:pass
    def initialize(self,reference):
        with self._lock():
            a=self.approval(reference)
            # Adopted authority never creates another ledger, even if budget.json disappears.
            if a['schema_version']!='ia-language-approval/1' or any(os.path.lexists(p) for p in (self.adoption_path,self.adoption2_path,self.adoption3_path,self.adoption4_path)):raise LanguageError('ledger_initialization_forbidden',409)
            if self.path.exists() or self.path.is_symlink():raise LanguageError('ledger_exists',409)
            state={'schema_version':'ia-language-ledger/1','ledger_id':str(uuid.uuid4()),'created_at':time.time(),
                'approval_reference':a['approval_reference'],'config_hash':self.config_hash,'policy_hash':POLICY_HASH,
                'limits_nano_usd':copy.deepcopy(POLICY['limits_nano_usd']),'sequence':0,'entries':[],
                'cost_basis':POLICY['cost_basis'],'provider_billed_comparison':None}
            self._write(state);return self._summary(state)
    def _summary(self,state):
        a,adopted=self._authority();buckets={}
        for b,limit in state['limits_nano_usd'].items():
            entries=[e for e in state['entries'] if e['bucket']==b]
            settled=sum(e['settled_estimate_nano_usd'] for e in entries if e['state']=='settled')
            held=sum(e['reserved_nano_usd'] for e in entries if e['state'] in ('reserved','dispatched','unknown'))
            contingency=POLICY['contingency_nano_usd'][b]
            buckets[b]={'limit_nano_usd':limit,'settled_usage_estimate_nano_usd':settled,'held_liability_nano_usd':held,
                'nonmodel_contingency_nano_usd':contingency,'available_nano_usd':limit-settled-held-contingency,'entries':len(entries)}
        count=sum(e.get('count_requests',0) for e in state['entries']);ceiling=count_ceiling(a)
        return {'ledger_id':state['ledger_id'],'sequence':state['sequence'],'approval_reference':state['approval_reference'],
                'config_hash':state['config_hash'],'financial_origin_config_hash':state['config_hash'],
                'active_config_hash':self.config_hash,'approval_schema':a['schema_version'],
                'adoption_record_sha256':a.get('adoption_record_sha256'),
                'adoption_transition_reference':adopted['transition_reference'] if adopted else None,
                'adoption2_record_sha256':a.get('adoption2_record_sha256'),
                'adoption3_record_sha256':a.get('adoption3_record_sha256'),
                'adoption4_record_sha256':a.get('adoption4_record_sha256'),
                'previous_active_config_hash':adopted.get('previous_active_config_hash') if adopted else None,
                'config_lineage':([state['config_hash']] if not adopted else [adopted['origin_config_hash'],
                    *([ADOPTION1_ACTIVE_CONFIG_HASH] if 'second_transition_reference' in adopted else []),
                    *([ADOPTION2_ACTIVE_CONFIG_HASH] if 'third_transition_reference' in adopted else []),
                    *([adopted['previous_active_config_hash']] if 'previous_active_config_hash' in adopted else []),self.config_hash]),
                'adoption_lineage':([] if not adopted else ([{'record':ADOPTION_FILE,'sha256':a['adoption_record_sha256'],
                    'transition_reference':adopted.get('first_transition_reference',adopted['transition_reference'])}]
                    +([{'record':ADOPTION2_FILE,'sha256':a['adoption2_record_sha256'],
                        'transition_reference':adopted.get('second_transition_reference',adopted['transition_reference'])}]
                      if 'adoption2_record_sha256' in a else [])
                    +([{'record':ADOPTION3_FILE,'sha256':a['adoption3_record_sha256'],
                        'transition_reference':adopted.get('third_transition_reference',adopted['transition_reference'])}]
                      if 'adoption3_record_sha256' in a else [])
                    +([{'record':ADOPTION4_FILE,'sha256':a['adoption4_record_sha256'],'transition_reference':adopted['transition_reference']}]
                      if 'adoption4_record_sha256' in a else []))),
                'max_count_requests':ceiling,'count_capacity_remaining':max(0,ceiling-count),
                'policy_hash':state['policy_hash'],'buckets':buckets,
                'unresolved':any(e['state'] in ('reserved','dispatched','unknown') for e in state['entries']),
                'cost_basis':state['cost_basis'],'provider_billed_comparison':state['provider_billed_comparison'],
                'control_directory_realpath':str(self.control_dir.resolve()),
                'count_endpoint_price':POLICY['count_endpoint_price'],
                'contingency_basis':POLICY['contingency_basis'],'count_requests':count,
                'stage':a['stage']}
    def summary(self):
        with self._lock():return self._summary(self._read())
    def reserve(self,bucket,payload_hash):
        if bucket not in ('test','demo'):raise LanguageError('invalid_bucket')
        with self._lock():
            state=self._read();summary=self._summary(state)
            if summary['unresolved']:raise LanguageError('unresolved_liability',503)
            if summary['count_requests']>=summary['max_count_requests']:
                raise LanguageError('qualification_reconciliation_required' if summary['stage']=='qualification' else 'count_ceiling_reached',503)
            amount=reservation()
            if summary['buckets'][bucket]['available_nano_usd']<amount:raise LanguageError('budget_exhausted',503)
            eid=str(uuid.uuid4());state['sequence']+=1
            state['entries'].append({'entry_id':eid,'sequence':state['sequence'],'bucket':bucket,'state':'reserved',
                'created_at':time.time(),'reserved_nano_usd':amount,'settled_estimate_nano_usd':None,
                'payload_hash':payload_hash,'config_hash':self.config_hash,'counted_input_tokens':None,'count_requests':0,
                'model_calls':0,'usage':None,'terminal_code':None})
            self._write(state);return eid
    def _update(self,eid,mutate,precheck=None):
        with self._lock():
            state=self._read();entry=next((e for e in state['entries'] if e['entry_id']==eid),None)
            if entry is None:raise LanguageError('ledger_entry_missing',503)
            if precheck is not None:precheck(state)
            mutate(entry);state['sequence']+=1;self._write(state)
    def count_dispatched(self,eid):
        # Durable cumulative ceiling immediately before transport; the attempt is persisted
        # before any count request and is never refunded.
        def ceiling(state):
            s=self._summary(state)
            if s['count_requests']>=s['max_count_requests']:raise LanguageError('count_ceiling_reached',503)
        def update(e):
            if e['state']!='reserved' or e['count_requests']!=0:raise LanguageError('accounting_state',503)
            e['count_requests']=1
        self._update(eid,update,ceiling)
    def counted(self,eid,tokens):
        amount=reservation(tokens)
        def update(e):
            if e['state']!='reserved':raise LanguageError('accounting_state',503)
            e.update(counted_input_tokens=tokens,reserved_nano_usd=amount)
        self._update(eid,update)
    def dispatched(self,eid):
        def update(e):
            if e['state']!='reserved' or e['counted_input_tokens'] is None:raise LanguageError('accounting_state',503)
            e.update(state='dispatched',model_calls=1)
        self._update(eid,update)
    def release_before_dispatch(self,eid,code):
        def update(e):
            if e['state']!='reserved':raise LanguageError('accounting_state',503)
            e.update(state='released',terminal_code=code,settled_estimate_nano_usd=0)
        self._update(eid,update)
    def unknown(self,eid,code):
        def update(e):
            if e['state'] not in ('reserved','dispatched','unknown'):raise LanguageError('accounting_state',503)
            e.update(state='unknown',terminal_code=code)
        self._update(eid,update)
    def settle(self,eid,usage,code):
        cost=usage_cost(usage)
        def update(e):
            if e['state']!='dispatched' or cost>e['reserved_nano_usd']:raise LanguageError('accounting_state',503)
            e.update(state='settled',usage=copy.deepcopy(usage),settled_estimate_nano_usd=cost,terminal_code=code,settled_at=time.time())
        self._update(eid,update)
