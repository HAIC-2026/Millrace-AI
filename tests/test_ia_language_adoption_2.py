"""Offline SECOND configuration adoption (previous active c0d -> one new active) on the same ledger.
Temp directories, the actual saved DEV 6-entry shape, fake transport/secret only; no host control state."""
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_RECORD_SHA256, ADOPTION2_CHECKPOINT,
    ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY, POLICY_HASH, BudgetLedger, approval_v2, approval_v3, reservation)
from tools import ia_language_config_adoption_2 as helper

FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'ia-language-dev-v5-replay.json').read_text())
RECORD1=dumps(FIXTURE['first_adoption_record'])
REF=FIXTURE['first_adoption_record']['original_approval_reference']
CATALOG=FIXTURE['first_adoption_record']['catalog_digest']
NEW='sha256:'+'1'*64
PINS={'transition_reference':'root-go-adoption-2','source_component_sha256':'sha256:'+'2'*64,
    'image_digest':'sha256:'+'3'*64,'review_receipt_sha256':'sha256:'+'4'*64}

def baseline(root):
    """Seq30/count6/no-hold ledger: 3 unstamped origin entries, then the 3 actual settled DEV entries (c0d)."""
    root=Path(root);(root/'ledger').mkdir(mode=0o700)
    (root/'config-adoption.json').write_bytes(RECORD1)
    (root/'approval.json').write_bytes(dumps(approval_v2(REF,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,6)))
    entries=[]
    for n,cost in enumerate((9179666,9179667,9179667)):
        entries.append({'entry_id':f'00000000-0000-4000-8000-00000000000{n}','sequence':5*n+1,'bucket':'test','state':'settled',
            'created_at':1.0,'reserved_nano_usd':reservation(),'settled_estimate_nano_usd':cost,'payload_hash':'sha256:'+'9'*64,
            'counted_input_tokens':8600,'count_requests':1,'model_calls':1,'usage':None,'terminal_code':'invalid_provider_arguments','settled_at':2.0})
    entries+=[copy.deepcopy(c['settled_entry']) for c in FIXTURE['cases']]
    state={'schema_version':'ia-language-ledger/1','ledger_id':ADOPTION_LEDGER_ID,'created_at':0.5,'approval_reference':REF,
        'config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'policy_hash':POLICY_HASH,'limits_nano_usd':POLICY['limits_nano_usd'],
        'sequence':30,'entries':entries,'cost_basis':POLICY['cost_basis'],'provider_billed_comparison':None}
    (root/'ledger'/'budget.json').write_bytes(dumps(state))
    for lock in ('job.lock','budget.lock'):(root/'ledger'/lock).write_bytes(b'')
    return root

def sha(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def put(path,data):
    if path.exists():os.chmod(path,0o640)  # offline fixtures only: published files are 0440
    path.write_bytes(data)
def ledger(root,config=NEW,catalog=CATALOG):return BudgetLedger(config,root,protected=False,catalog_digest=catalog)

class SecondAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=baseline(self.tmp.name)
        self.budget=self.root/'ledger'/'budget.json';self.pre=self.budget.read_bytes()
        self.approval=self.root/'approval.json';self.v2=self.approval.read_bytes()
        self.record1=self.root/'config-adoption.json';self.record2=self.root/'config-adoption-2.json'
    def tearDown(self):self.tmp.cleanup()
    def adopt(self,**over):
        kw=dict(PINS,active_config_hash=NEW,catalog_digest=CATALOG,expected_budget_sha256=sha(self.pre),max_count_requests=7,protected=False)
        kw.update(over);return helper.adopt2(self.root,**kw)
    def blocked(self,l,job=True):
        for call in (l.summary,lambda:l.reserve('test','h'),lambda:l.reserve('demo','h'))+((l.acquire_job,) if job else ()):
            with self.assertRaises(LanguageError):call()
    def unchanged(self,approval=None):
        self.assertEqual(self.budget.read_bytes(),self.pre);self.assertEqual(self.record1.read_bytes(),RECORD1)
        self.assertEqual(self.approval.read_bytes(),approval or self.v2);self.assertFalse((self.root/'ledger'/'HALTED').exists())

    def test_fixture_is_exact_first_record_and_actual_dev_checkpoint(self):
        self.assertEqual(sha(RECORD1),ADOPTION1_RECORD_SHA256)
        self.assertEqual(sha(self.v2)[:15],'sha256:0d3d7b8a')
        s=ledger(self.root,ADOPTION1_ACTIVE_CONFIG_HASH).summary()
        self.assertEqual((s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining'],s['unresolved']),(30,6,6,0,False))
        self.assertEqual(s['buckets']['test']['settled_usage_estimate_nano_usd'],55078000)

    def test_second_adoption_preserves_ledger_and_first_record_and_reports_lineage(self):
        out=self.adopt();self.assertEqual((out['provider_calls'],out['ledger_writes'],out['resumed']),(0,0,False))
        self.assertEqual(self.budget.read_bytes(),self.pre);self.assertEqual(self.record1.read_bytes(),RECORD1)
        self.assertEqual(out['budget_sha256_unchanged'],sha(self.pre))
        r=json.loads(self.record2.read_bytes());a=json.loads(self.approval.read_bytes())
        self.assertEqual((r['origin_config_hash'],r['previous_active_config_hash'],r['active_config_hash'],r['previous_adoption_record_sha256']),
            (ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,NEW,ADOPTION1_RECORD_SHA256))
        self.assertEqual(r['checkpoint'],dict(ADOPTION2_CHECKPOINT,budget_sha256=sha(self.pre)))
        self.assertEqual(a,approval_v3(REF,NEW,sha(self.record2.read_bytes()),7));self.assertEqual(self.approval.read_bytes(),dumps(a))
        s=ledger(self.root).summary()
        self.assertEqual((s['ledger_id'],s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining']),(ADOPTION_LEDGER_ID,30,6,7,1))
        self.assertEqual((s['financial_origin_config_hash'],s['previous_active_config_hash'],s['active_config_hash']),(ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,NEW))
        self.assertEqual(s['config_lineage'],[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,NEW])
        self.assertEqual([x['record'] for x in s['adoption_lineage']],['config-adoption.json','config-adoption-2.json'])
        self.assertEqual(s['adoption_lineage'][1]['sha256'],out['adoption2_record_sha256']);self.assertEqual(s['approval_schema'],'ia-language-approval/3')

    def test_exactly_one_more_count_no_refund_then_blocked_both_buckets_after_restart(self):
        self.adopt();l=ledger(self.root);eid=l.reserve('demo','h');l.count_dispatched(eid);l.release_before_dispatch(eid,'semantic_failure')
        state=json.loads(self.budget.read_bytes());new=state['entries'][-1]
        self.assertEqual((new['config_hash'],new['count_requests'],len(state['entries'])),(NEW,1,7));self.assertGreater(new['sequence'],30)
        self.assertEqual(state['entries'][:6],json.loads(self.pre)['entries'])  # history bytes-identical in content
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError) as c:ledger(self.root).reserve(bucket,'h')
            self.assertEqual(c.exception.code,'count_ceiling_reached')
        s=ledger(self.root).summary();self.assertEqual((s['count_requests'],s['count_capacity_remaining']),(7,0))

    def test_old_authorities_cannot_spend(self):
        # Partially staged record 2 with the old v2: old active (new code) and new active are refused; old binary is cap6-exhausted.
        with patch.object(helper,'_publish_atomic',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.adopt()
        self.assertTrue(self.record2.exists());self.assertEqual(self.approval.read_bytes(),self.v2)
        for config in (NEW,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION_ORIGIN_CONFIG_HASH):self.blocked(ledger(self.root,config))
        self.adopt()
        for config in (ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION_ORIGIN_CONFIG_HASH,'sha256:'+'5'*64):self.blocked(ledger(self.root,config))
        self.blocked(ledger(self.root,NEW,'sha256:'+'8'*64))
        self.blocked(BudgetLedger(NEW,self.root,protected=True,catalog_digest=CATALOG))

    def test_runtime_rejects_forged_records_approval_and_lineage(self):
        self.adopt();r2=self.record2.read_bytes();a3=self.approval.read_bytes();state=json.loads(self.pre)
        bad_approvals=[]
        for k,v in (('max_count_requests',396),('max_count_requests',7.0),('max_count_requests',0),('max_count_requests','7'),('max_count_requests',True),
                ('adoption_record_sha256','sha256:'+'6'*64),('adoption2_record_sha256','sha256:'+'6'*64),('config_hash',ADOPTION1_ACTIVE_CONFIG_HASH),
                ('approval_reference','other'),('stage','qualification'),('policy_hash','sha256:'+'7'*64),('extra',1)):
            a=json.loads(a3);a[k]=v;bad_approvals.append(dumps(a))
        a=json.loads(a3);del a['adoption2_record_sha256'];bad_approvals.append(dumps(a))
        for raw in bad_approvals:
            put(self.approval,raw);self.blocked(ledger(self.root));put(self.approval,a3)
        for path,raw in ((self.record2,r2.replace(b'root-go-adoption-2',b'root-go-adoption-x')),(self.record1,RECORD1.replace(b'new25',b'new26')),
                (self.record2,json.dumps(json.loads(r2),indent=1).encode())):
            orig=path.read_bytes();put(path,raw);self.blocked(ledger(self.root));put(path,orig)
        for path in (self.record1,self.record2):
            orig=path.read_bytes();path.unlink();self.blocked(ledger(self.root));path.write_bytes(orig)
        ledger(self.root).summary()
        def entry(**kw):
            e=copy.deepcopy(state['entries'][-1]);e.update(entry_id='00000000-0000-4000-8000-0000000000aa',**kw);return e
        forged=[entry(sequence=31),entry(config_hash=NEW,sequence=20),entry(config_hash=ADOPTION_ORIGIN_CONFIG_HASH,sequence=31),
                entry(config_hash=None,sequence=31)]
        unstamped=entry(sequence=31);del unstamped['config_hash'];forged.append(unstamped)
        for e in forged:
            s=copy.deepcopy(state);s['entries'].append(e);put(self.budget,dumps(s))
            with self.assertRaises(LanguageError) as c:ledger(self.root).summary()
            self.assertEqual(c.exception.code,'ledger_unavailable')
        put(self.budget,self.pre);self.assertEqual(ledger(self.root).summary()['count_requests'],6)

    def test_allowable_range_395_is_metadata_only_and_money_guards_unchanged(self):
        from districtbrief import ia_language_accounting as acc
        self.assertEqual((acc.MAX_COUNT_CEILING,acc.ADOPTION2_MAX_COUNT_REQUESTS,acc.POLICY['qualification_count_limit']),(395,7,3))
        self.assertEqual(acc.POLICY_HASH,'sha256:14ec7c8f8dede96f5ad543dfce02c7a3eb57e74edb40391a3aefeff897375ac5')
        self.assertEqual(acc.POLICY['limits_nano_usd'],{'test':15000000000,'demo':10000000000})
        out=self.adopt();self.assertEqual((out['max_count_requests'],out['count_capacity_remaining']),(7,1))  # helper default stays 7
        a3=self.approval.read_bytes();r2sha=sha(self.record2.read_bytes())
        # A root-reviewed v3 may carry up to 395; the next value and non-plain ints are refused.
        put(self.approval,dumps(approval_v3(REF,NEW,r2sha,395)))
        s=ledger(self.root).summary();self.assertEqual((s['max_count_requests'],s['count_capacity_remaining']),(395,389))
        for bad in (396,0,True,395.0,'395'):
            put(self.approval,dumps(approval_v3(REF,NEW,r2sha,bad)));self.blocked(ledger(self.root))
        put(self.approval,dumps(approval_v3(REF,NEW,r2sha,395)))
        # Count headroom never bypasses dollar limits or unknown-usage holds.
        with patch.object(acc,'reservation',return_value=15000000000):
            with self.assertRaises(LanguageError) as c:ledger(self.root).reserve('test','h')
            self.assertEqual(c.exception.code,'budget_exhausted')
        l=ledger(self.root);eid=l.reserve('demo','h');l.count_dispatched(eid);l.unknown(eid,'transport_unknown')
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError) as c:ledger(self.root).reserve(bucket,'h')
            self.assertEqual(c.exception.code,'unresolved_liability')
        state=json.loads(self.budget.read_bytes());self.assertEqual(state['entries'][:6],json.loads(self.pre)['entries'])
        put(self.approval,a3)

    def test_adopted3_never_initializes_even_if_budget_missing(self):
        self.adopt();self.budget.unlink()
        with self.assertRaises(LanguageError) as c:ledger(self.root).initialize(REF)
        self.assertEqual(c.exception.code,'ledger_initialization_forbidden');self.assertFalse(self.budget.exists())

    def test_helper_refuses_bad_preconditions_without_writing(self):
        cases={'pin':dict(active_config_hash='nope'),'origin':dict(active_config_hash=ADOPTION_ORIGIN_CONFIG_HASH),
            'previous':dict(active_config_hash=ADOPTION1_ACTIVE_CONFIG_HASH),'cap6':dict(max_count_requests=6),'cap8':dict(max_count_requests=8),
            'cap128':dict(max_count_requests=128),'cap256':dict(max_count_requests=256),'capfloat':dict(max_count_requests=7.0),'capbool':dict(max_count_requests=True),'ref':dict(transition_reference=' '),
            'sameref':dict(transition_reference=FIXTURE['first_adoption_record']['transition_reference']),
            'budgetpin':dict(expected_budget_sha256='sha256:'+'0'*64),'catalog':dict(catalog_digest='sha256:'+'8'*64)}
        for name,over in cases.items():
            with self.assertRaises(helper.AdoptionError,msg=name):self.adopt(**over)
            self.unchanged();self.assertFalse(self.record2.exists())
        for raw in (RECORD1.replace(b'"sequence":15',b'"sequence":16'),RECORD1+b'\n'):
            put(self.record1,raw)
            with self.assertRaises(helper.AdoptionError) as c:self.adopt()
            self.assertEqual(c.exception.code,'first_record_mismatch');put(self.record1,RECORD1);self.assertFalse(self.record2.exists())
        for raw in (dumps(approval_v2(REF,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,7)),
                dumps(approval_v2('other',ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,6)),
                dumps(approval_v3(REF,NEW,'sha256:'+'6'*64,7)),self.v2+b' '):
            put(self.approval,raw)
            with self.assertRaises(helper.AdoptionError):self.adopt()
            self.assertFalse(self.record2.exists());self.assertEqual(self.approval.read_bytes(),raw);put(self.approval,self.v2)

    def test_helper_refuses_ledger_state_mismatch(self):
        base=json.loads(self.pre)
        def mutate(f):
            s=copy.deepcopy(base);f(s);return s
        def extra(s):
            e=copy.deepcopy(s['entries'][-1]);e.update(entry_id='x',sequence=30,state='released',count_requests=0,settled_estimate_nano_usd=0);s['entries'].append(e)
        variants=[mutate(lambda s:s.update(sequence=31)),mutate(lambda s:s.update(ledger_id='00000000-0000-4000-8000-000000000000')),
            mutate(lambda s:s.update(policy_hash='sha256:'+'7'*64)),mutate(lambda s:s.update(config_hash=ADOPTION1_ACTIVE_CONFIG_HASH)),
            mutate(lambda s:s.update(approval_reference='other')),mutate(lambda s:s['entries'][3].update(state='unknown')),
            mutate(lambda s:s['entries'][3].update(config_hash=NEW)),mutate(lambda s:s['entries'][0].update(config_hash=ADOPTION_ORIGIN_CONFIG_HASH)),
            mutate(lambda s:s['entries'][3].update(sequence=12)),mutate(lambda s:s['entries'][0].update(settled_estimate_nano_usd=9179665)),
            mutate(lambda s:s['entries'].reverse()),mutate(extra),mutate(lambda s:s['entries'].pop())]
        for s in variants:
            raw=dumps(s);put(self.budget,raw)
            with self.assertRaises((helper.AdoptionError,KeyError,TypeError)):self.adopt(expected_budget_sha256=sha(raw))
            self.assertFalse(self.record2.exists());self.assertEqual(self.approval.read_bytes(),self.v2);self.assertEqual(self.budget.read_bytes(),raw)

    def test_helper_refuses_halted_and_busy_locks_nonblocking(self):
        (self.root/'ledger'/'HALTED').write_bytes(b'')
        with self.assertRaises(helper.AdoptionError) as c:self.adopt()
        self.assertEqual(c.exception.code,'accounting_halted');(self.root/'ledger'/'HALTED').unlink()
        for lock in ('job.lock','budget.lock'):
            fd=os.open(self.root/'ledger'/lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:
                begin=time.monotonic()
                with self.assertRaises(helper.AdoptionError) as c:self.adopt()
                self.assertEqual(c.exception.code,'busy');self.assertLess(time.monotonic()-begin,1)
            finally:os.close(fd)
            self.unchanged();self.assertFalse(self.record2.exists())
        if os.geteuid()!=0:
            with self.assertRaises(helper.AdoptionError) as c:self.adopt(protected=True)
            self.assertEqual(c.exception.code,'root_required')

    def test_storage_fault_halts_and_never_resets(self):
        with patch.object(helper,'_publish_atomic',side_effect=OSError('disk')):
            with self.assertRaises(helper.AdoptionError) as c:self.adopt()
        self.assertEqual(c.exception.code,'adoption_commit_uncertain_halted')
        self.assertTrue((self.root/'ledger'/'HALTED').exists());self.assertEqual(self.budget.read_bytes(),self.pre)
        self.assertEqual(self.approval.read_bytes(),self.v2);self.assertEqual(self.record1.read_bytes(),RECORD1)
        for config in (NEW,ADOPTION1_ACTIVE_CONFIG_HASH):self.blocked(ledger(self.root,config))
        with self.assertRaises(helper.AdoptionError) as c:self.adopt()
        self.assertEqual(c.exception.code,'accounting_halted')

    def test_crash_after_record_resumes_identical_only_and_committed_rerun_is_inert(self):
        with patch.object(helper,'_publish_atomic',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.adopt()
        staged=self.record2.read_bytes()
        with self.assertRaises(helper.AdoptionError) as c:self.adopt(transition_reference='different-go')
        self.assertEqual(c.exception.code,'adoption_conflict');self.assertEqual(self.record2.read_bytes(),staged);self.unchanged()
        out=self.adopt();self.assertTrue(out['resumed']);self.assertEqual(self.record2.read_bytes(),staged)
        committed=self.approval.read_bytes();again=self.adopt();self.assertTrue(again['resumed'])
        self.assertEqual((self.approval.read_bytes(),self.record2.read_bytes(),self.budget.read_bytes()),(committed,staged,self.pre))
        self.record2.unlink()
        with self.assertRaises(helper.AdoptionError) as c:self.adopt()
        self.assertEqual(c.exception.code,'adoption_conflict')

    def test_cli_refusal_shape(self):
        out=io.StringIO()
        with redirect_stdout(out):code=helper.main(['--control-dir',str(self.root),'--active-config-hash',NEW,'--catalog-digest',CATALOG,
            '--transition-reference','x','--source-component-sha256',PINS['source_component_sha256'],'--image-digest',PINS['image_digest'],
            '--review-receipt-sha256',PINS['review_receipt_sha256'],'--expected-budget-sha256',sha(self.pre),'--max-count-requests','127'])
        self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue()),{'status':'refused','code':'invalid_max_count_requests','provider_calls':0})
        self.unchanged()

class SecondAdoptionProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from public_app import load_core
        from districtbrief.investigation import Investigation
        cls.i=Investigation(load_core())
    def setUp(self):
        from districtbrief.ia_language import prepare_request
        from test_ia_language_accounting import usage
        self.tmp=tempfile.TemporaryDirectory();self.root=baseline(self.tmp.name)
        helper.adopt2(self.root,**PINS,active_config_hash=NEW,catalog_digest=CATALOG,
            expected_budget_sha256=sha((self.root/'ledger'/'budget.json').read_bytes()),max_count_requests=7,protected=False)
        self.prepared=prepare_request(copy.deepcopy(FIXTURE['cases'][0]['request']),self.i,'session')
        self.calls=[];self.secrets=0;self.usage=usage()
    def tearDown(self):self.tmp.cleanup()
    def transport(self,method,path,body,secret,deadline):
        from districtbrief.ia_language_provider import MODEL
        self.calls.append(path)
        if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
        return 200,{'status':'completed','model':MODEL,'service_tier':'default','reasoning':{'effort':'low'},'usage':self.usage,'output':[]}
    def secret(self):self.secrets+=1;return 'fake-secret-never-network'
    def interpret(self,bucket):
        from districtbrief.ia_language_provider import OpenAIProvider
        return OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,ledger(self.root),bucket,threading.Event(),time.monotonic()+25,lambda:None)
    def test_retired_record2_ledger_is_refused_before_secret_or_transport(self):
        before=ledger(self.root).summary()
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError) as failure:self.interpret(bucket)
            self.assertEqual(failure.exception.code,'profile_unavailable')
        self.assertEqual((self.calls,self.secrets),([],0));self.assertEqual(ledger(self.root).summary(),before)
    def test_forged_record2_blocks_before_secret_and_transport(self):
        rec=self.root/'config-adoption-2.json';put(rec,rec.read_bytes().replace(b'root-go',b'rootxgo'))
        with self.assertRaises(LanguageError):self.interpret('test')
        self.assertEqual((self.calls,self.secrets),([],0))
if __name__=='__main__':unittest.main()
