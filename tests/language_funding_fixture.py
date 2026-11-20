"""Shared offline fixture: a protected-mode-off funding record and the active FundingLedger."""
import copy
from pathlib import Path
from districtbrief.ia_language import dumps
from districtbrief.ia_language_funding import FundingLedger, initialize_ledger, reservation
from districtbrief.ia_language_profiles import PROFILES_PATH, load_profile, load_profiles, parse_profiles
from test_ia_language_accounting import usage  # noqa: F401  (shared usage builder)

PROFILE=load_profile('terra-medium')
SOL=load_profile('sol-low')
MODEL=PROFILE.model
def _historical_low():
    """TEST-ONLY replay profile: the historical Terra/low origin, never production data."""
    import json
    d=json.loads(PROFILES_PATH.read_text());p=d['profiles']['terra-medium']
    p['reasoning_effort']=p['expected_response']['reasoning_effort']='low'
    d['profiles']={'historical-terra-low':p}
    return parse_profiles(dumps(d))['historical-terra-low']
HISTORICAL_LOW=_historical_low()
LEDGER_ID='5b0c9f8e-3d3a-4c55-9a51-8a2b1c3d4e5f'
# The saved DEV replay requests carry the earlier 20-measure public evidence identity. Guided-only measures leave the
# Ask value-free catalog (digest) and the outbound provider payload unchanged, so tests that replay those exact saved
# requests rebind only their evidence identity, explicitly, to the running snapshot. Case files are never rebound.
# A saved selected finding is re-derived from its unchanged original finding ID under the running confirmed plan.
EARLIER_PUBLIC_SNAPSHOT='sha256:b1f06a08f8d61f5a5a15bf1f02c3ebf71c2e70a48442fe9f702a3cc837a28479'
def rebind_saved_requests(fixture,investigation):
    snapshot_id=investigation.snapshot_id
    for case in fixture['cases']:
        context=case['request']['context']
        for held in (context,case.get('expected',{}).get('bound_tokens') or {}):
            if held.get('snapshot_id') in (EARLIER_PUBLIC_SNAPSHOT,snapshot_id):held['snapshot_id']=snapshot_id
            else:raise AssertionError('unexpected saved evidence identity')
        refs=context.get('selected_claim_refs') or []
        if refs and refs[0]['snapshot_id']!=snapshot_id:
            run={'schema_version':'haic-investigation/1','operation_version':context['operation_version'],
                 'recipe_version':context['recipe_version'],'snapshot_id':snapshot_id,'request_id':case['request']['request_id'],
                 **{k:context[k] for k in ('case_id','branch_id','revision')},'mode':'run','plan':copy.deepcopy(context['confirmed_plan']),
                 'selected_claim_refs':[],'selected_action_ref':None}
            current={c['claim_ref']['finding_id']:c['claim_ref'] for c in investigation.handle(run)['claims']}
            assert all(r['snapshot_id']==EARLIER_PUBLIC_SNAPSHOT and r['finding_id'] in current for r in refs)
            context['selected_claim_refs']=[copy.deepcopy(current[r['finding_id']]) for r in refs]
    return fixture

def funding_record(**changes):
    profiles=load_profiles()
    f={'schema_version':'ia-language-funding/1','approved':True,'approval_reference':'approved-test-reference',
       'ledger_id':LEDGER_ID,'total_limit_nano_usd':25000000000,
       'limits_nano_usd':{'test':15000000000,'demo':10000000000},
       'contingency_nano_usd':{'test':2000000000,'demo':0},
       'admission':{'test':{'terra-medium':395,'sol-low':10},'demo':{'terra-medium':100}},
       'profile_hashes':{k:profiles[k].profile_hash for k in ('terra-medium','sol-low')},
       'max_starts':505,
       'carry_forward':{'starts':0,'settled_nano_usd':{'test':0,'demo':0},'held_nano_usd':0,
           'sources':[{'kind':'canonical_ledger','id':'0f0e0d0c-0b0a-4908-8706-050403020100','file_sha256':'a'*64,'sequence':0,
               'entries':0,'starts':0,'released_zero_start':0,'settled_nano_usd':{'test':0,'demo':0},'held_nano_usd':0,
               'unresolved_entries':0,'reference':'test:fixture-origin'}]}}
    for k,v in changes.items():f[k]=copy.deepcopy(v)
    return f

def ledger_fixture(directory,config='sha256:'+'a'*64,profile=None,funding=None):
    root=Path(directory);(root/'ledger').mkdir(mode=0o700,exist_ok=True)
    (root/'funding.json').write_bytes(dumps(funding or funding_record()))
    initialize_ledger(root,protected=False)
    return FundingLedger(profile or PROFILE,root,config_hash=config,protected=False)

def bound(ledger,profile):
    """A second ledger object over the same files, bound to another selected profile."""
    return FundingLedger(profile,ledger.control_dir,config_hash=ledger.config_hash,protected=False)

__all__=['HISTORICAL_LOW','PROFILE','SOL','MODEL','funding_record','ledger_fixture','bound','usage','reservation']
