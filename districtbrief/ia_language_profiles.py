"""Validated model profiles. Model, effort, rates, caps and expected response identity are DATA
(ia_language_profiles.json); a new model or effort needs new reviewed data plus funding admission,
never a code edit. Selection is operator-only (protected env/CLI), never from a question or client."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import hashlib
from pathlib import Path
import re
from .ia_language import LanguageError, dumps, strict_json

PROFILES_PATH=Path(__file__).with_name('ia_language_profiles.json')
SCHEMA='ia-language-profiles/1'
RATE_KEYS=('uncached_input','cached_input','cache_write_30m','output')
# Short-context bound: above 272K input tokens OpenAI bills long-context rates, so a profile cap
# above it would make the declared short-context rates wrong. Output is bounded by the transport.
SHORT_CONTEXT_INPUT_LIMIT=272000
MAX_OUTPUT_LIMIT=128000
_MODEL=re.compile(r'gpt-[A-Za-z0-9._-]{1,60}')
_PROFILE=re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
_EFFORT=re.compile(r'[a-z]{1,16}')
_DATE=re.compile(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]')
_MODEL_KEYS={'provider','api','processing','supported_reasoning_efforts','rates_nano_usd_per_token','pricing_source','pricing_checked'}
_PROFILE_KEYS={'model','reasoning_effort','service_tier','max_input_tokens','max_output_tokens','expected_response'}
_EXPECTED_KEYS={'model','service_tier','reasoning_effort'}

@dataclass(frozen=True)
class Profile:
    profile_id:str
    model:str
    reasoning_effort:str
    service_tier:str
    max_input_tokens:int
    max_output_tokens:int
    rates:dict=field(repr=False)
    expected_model:str
    expected_service_tier:str
    expected_reasoning_effort:str
    profile_hash:str
    def public_identity(self):
        return {'profile_id':self.profile_id,'model':self.model,'reasoning_effort':self.reasoning_effort,
                'service_tier':self.service_tier,'profile_hash':self.profile_hash}

def _int(v,lo,hi):return type(v) is int and lo<=v<=hi

def _model(model_id,m):
    if not _MODEL.fullmatch(model_id) or type(m) is not dict or set(m)!=_MODEL_KEYS:raise ValueError()
    # Only the OpenAI Responses API at Standard processing: no Fast/Flex/Batch/Regional pricing.
    if m['provider']!='openai' or m['api']!='responses' or m['processing']!='standard':raise ValueError()
    efforts=m['supported_reasoning_efforts']
    if type(efforts) is not list or not 1<=len(efforts)<=16 or len(set(efforts))!=len(efforts) or not all(type(e) is str and _EFFORT.fullmatch(e) for e in efforts):raise ValueError()
    rates=m['rates_nano_usd_per_token']
    if type(rates) is not dict or set(rates)!=set(RATE_KEYS) or not all(_int(rates[k],1,1000000) for k in RATE_KEYS):raise ValueError()
    if type(m['pricing_source']) is not str or not m['pricing_source'].startswith('https://') or len(m['pricing_source'])>200:raise ValueError()
    if type(m['pricing_checked']) is not str or not _DATE.fullmatch(m['pricing_checked']):raise ValueError()

def _profile(profile_id,p,models):
    if type(profile_id) is not str or not _PROFILE.fullmatch(profile_id) or type(p) is not dict or set(p)!=_PROFILE_KEYS:raise ValueError()
    m=models.get(p['model']) if type(p['model']) is str else None
    if m is None or p['reasoning_effort'] not in m['supported_reasoning_efforts'] or p['service_tier']!='default':raise ValueError()
    if not _int(p['max_input_tokens'],1,SHORT_CONTEXT_INPUT_LIMIT) or not _int(p['max_output_tokens'],1,MAX_OUTPUT_LIMIT):raise ValueError()
    e=p['expected_response']
    if type(e) is not dict or set(e)!=_EXPECTED_KEYS or type(e['model']) is not str or not _MODEL.fullmatch(e['model']):raise ValueError()
    # The accepted response identity is exactly the configured request identity: a data edit can never make one
    # profile accept (and price) another model's, tier's or effort's response.
    if e['model']!=p['model'] or e['service_tier']!=p['service_tier'] or e['reasoning_effort']!=p['reasoning_effort']:raise ValueError()
    record={'profile_id':profile_id,'profile':p,'model':{p['model']:m}}
    return Profile(profile_id=profile_id,model=p['model'],reasoning_effort=p['reasoning_effort'],service_tier=p['service_tier'],
        max_input_tokens=p['max_input_tokens'],max_output_tokens=p['max_output_tokens'],rates=copy.deepcopy(m['rates_nano_usd_per_token']),
        expected_model=e['model'],expected_service_tier=e['service_tier'],expected_reasoning_effort=e['reasoning_effort'],
        profile_hash='sha256:'+hashlib.sha256(dumps(record)).hexdigest())

def parse_profiles(raw):
    """Strictly validate profile data bytes; any defect rejects the whole file."""
    try:
        d=strict_json(raw)
        if type(d) is not dict or set(d)!={'schema_version','models','profiles'} or d['schema_version']!=SCHEMA:raise ValueError()
        if type(d['models']) is not dict or type(d['profiles']) is not dict or not 1<=len(d['models'])<=16 or not 1<=len(d['profiles'])<=32:raise ValueError()
        for model_id,m in d['models'].items():_model(model_id,m)
        return {pid:_profile(pid,p,d['models']) for pid,p in d['profiles'].items()}
    except (ValueError,KeyError,TypeError,UnicodeError,RecursionError):raise LanguageError('profile_unavailable',503) from None

def load_profiles(path=PROFILES_PATH):
    try:raw=Path(path).read_bytes()
    except OSError:raise LanguageError('profile_unavailable',503) from None
    return parse_profiles(raw)

def load_profile(profile_id,path=PROFILES_PATH):
    profiles=load_profiles(path)
    if type(profile_id) is not str or profile_id not in profiles:raise LanguageError('profile_unavailable',503)
    return profiles[profile_id]

def known_models(path=PROFILES_PATH):
    return frozenset(p.model for p in load_profiles(path).values())
