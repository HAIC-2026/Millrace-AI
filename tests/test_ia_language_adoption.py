"""Offline origin-to-active configuration adoption and cumulative count admission.
Temp directories, fake transport/secret only; no credentials, network or host control state."""
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
from districtbrief import ia_language_accounting as accounting
from districtbrief.ia_language_accounting import (ADOPTION_CHECKPOINT, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH,
    POLICY, POLICY_HASH, BudgetLedger, adoption_record, approval_v2, reservation)
from tools import ia_language_config_adoption as helper

ACTIVE='sha256:'+'1'*64
CATALOG='sha256:'+'c'*64
REF='original-qualification-reference'
PINS={'transition_reference':'root-go-adoption-1','source_component_sha256':'sha256:'+'2'*64,
    'image_digest':'sha256:'+'3'*64,'review_receipt_sha256':'sha256:'+'4'*64}
SETTLED=(9179666,9179667,9179667)

def baseline(root):
    """Seq15/count3/no-hold origin83 ledger shaped like the observed live checkpoint."""
    root=Path(root);(root/'ledger').mkdir(mode=0o700)
    approval={'schema_version':'ia-language-approval/1','approved':True,'approval_reference':REF,
        'limits_nano_usd':POLICY['limits_nano_usd'],'provider':'openai','model':POLICY['model'],
        'policy_hash':POLICY_HASH,'config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'stage':'qualification'}
    (root/'approval.json').write_bytes(dumps(approval))
    entries=[]
    for n,cost in enumerate(SETTLED):
        entries.append({'entry_id':f'00000000-0000-4000-8000-00000000000{n}','sequence':5*n+1,'bucket':'test','state':'settled',
            'created_at':1.0,'reserved_nano_usd':reservation(),'settled_estimate_nano_usd':cost,'payload_hash':'sha256:'+'9'*64,
            'counted_input_tokens':8600,'count_requests':1,'model_calls':1,'usage':None,'terminal_code':'invalid_provider_arguments','settled_at':2.0})
    state={'schema_version':'ia-language-ledger/1','ledger_id':ADOPTION_LEDGER_ID,'created_at':0.5,'approval_reference':REF,
        'config_hash':ADOPTION_ORIGIN_CONFIG_HASH,'policy_hash':POLICY_HASH,'limits_nano_usd':POLICY['limits_nano_usd'],
        'sequence':15,'entries':entries,'cost_basis':POLICY['cost_basis'],'provider_billed_comparison':None}
    (root/'ledger'/'budget.json').write_bytes(dumps(state))
    for lock in ('job.lock','budget.lock'):(root/'ledger'/lock).write_bytes(b'')
    return root

def adopt(root,**over):
    kw=dict(PINS,active_config_hash=ACTIVE,catalog_digest=CATALOG,max_count_requests=6,protected=False);kw.update(over)
    return helper.adopt(root,**kw)

def put(path,data):
    if path.exists():os.chmod(path,0o640)  # offline fixtures only: published files are 0440
    path.write_bytes(data)

def active(root):return BudgetLedger(ACTIVE,root,protected=False,catalog_digest=CATALOG)

class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=baseline(self.tmp.name)
        self.budget=self.root/'ledger'/'budget.json';self.pre=self.budget.read_bytes()
        self.approval=self.root/'approval.json';self.record=self.root/'config-adoption.json'
    def tearDown(self):self.tmp.cleanup()
    def blocked(self,ledger,job=True):
        # The job lock checks authority only; ledger-content faults are caught at every ledger read.
        for call in (ledger.summary,lambda:ledger.reserve('test','h'),lambda:ledger.reserve('demo','h'))+((ledger.acquire_job,) if job else ()):
            with self.assertRaises(LanguageError):call()

    def test_adoption_preserves_exact_ledger_and_distinguishes_origin_from_active(self):
        old_approval=json.loads(self.approval.read_bytes());out=adopt(self.root)
        self.assertEqual(self.budget.read_bytes(),self.pre)
        self.assertEqual(out['budget_sha256_unchanged'],'sha256:'+hashlib.sha256(self.pre).hexdigest())
        self.assertEqual((out['provider_calls'],out['ledger_writes'],out['resumed']),(0,0,False))
        a=json.loads(self.approval.read_bytes())
        self.assertEqual(a['schema_version'],'ia-language-approval/2');self.assertEqual(a['max_count_requests'],6)
        self.assertEqual(a['stage'],'evaluation');self.assertEqual(a['config_hash'],ACTIVE)
        for k in ('approval_reference','limits_nano_usd','provider','model','policy_hash'):self.assertEqual(a[k],old_approval[k])
        self.assertEqual(a['adoption_record_sha256'],'sha256:'+hashlib.sha256(self.record.read_bytes()).hexdigest())
        s=active(self.root).summary()
        self.assertEqual((s['ledger_id'],s['sequence'],s['count_requests'],s['unresolved']),(ADOPTION_LEDGER_ID,15,3,False))
        self.assertEqual((s['config_hash'],s['financial_origin_config_hash'],s['active_config_hash']),(ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION_ORIGIN_CONFIG_HASH,ACTIVE))
        self.assertEqual((s['max_count_requests'],s['count_capacity_remaining'],s['approval_reference']),(6,3,REF))
        self.assertEqual(s['buckets']['test']['settled_usage_estimate_nano_usd'],27539000)
        self.assertEqual(s['buckets']['test']['available_nano_usd'],12972461000)
        self.assertEqual(s['buckets']['demo']['available_nano_usd'],10000000000)
        self.assertEqual(s['buckets']['test']['held_liability_nano_usd'],0)
        self.assertEqual(self.budget.read_bytes(),self.pre)  # reads never rewrite

    def test_exactly_three_more_counts_no_refund_and_fourth_blocked_both_buckets_after_restart(self):
        adopt(self.root);ledger=active(self.root);old=json.loads(self.pre)['entries']
        codes=('count_rejected','invalid_provider_arguments','completed')
        for code in codes:
            e=ledger.reserve('test','h');ledger.count_dispatched(e);ledger.release_before_dispatch(e,code)
        state=json.loads(self.budget.read_bytes())
        self.assertEqual(state['entries'][:3],old)  # old entries untouched, unstamped
        self.assertTrue(all(e['config_hash']==ACTIVE for e in state['entries'][3:]))
        self.assertEqual(state['config_hash'],ADOPTION_ORIGIN_CONFIG_HASH);self.assertEqual(state['ledger_id'],ADOPTION_LEDGER_ID)
        for restarted in (ledger,active(self.root)):
            self.assertEqual(restarted.summary()['count_requests'],6);self.assertEqual(restarted.summary()['count_capacity_remaining'],0)
            for b in ('test','demo'):
                with self.assertRaises(LanguageError) as c:restarted.reserve(b,'h')
                self.assertEqual(c.exception.code,'count_ceiling_reached')

    def test_predispatch_rechecks_durable_cumulative_count(self):
        adopt(self.root);ledger=active(self.root)
        for _ in range(2):
            e=ledger.reserve('demo','h');ledger.count_dispatched(e);ledger.release_before_dispatch(e,'x')
        e=ledger.reserve('test','h')  # admitted at count5
        state=json.loads(self.budget.read_bytes())  # another authority consumed the last attempt durably
        extra=copy.deepcopy(state['entries'][-1]);extra.update(entry_id='other',state='released',count_requests=1)
        state['entries'].insert(-1,extra);put(self.budget,dumps(state))
        with self.assertRaises(LanguageError) as c:ledger.count_dispatched(e)
        self.assertEqual(c.exception.code,'count_ceiling_reached')
        ledger.release_before_dispatch(e,'count_ceiling_reached')
        self.assertEqual(ledger.summary()['count_requests'],6)

    def test_forged_or_mismatched_record_blocks_before_spending(self):
        adopt(self.root);good=json.loads(self.record.read_bytes());approval=json.loads(self.approval.read_bytes())
        mutations={'active':('active_config_hash','sha256:'+'5'*64),'origin':('origin_config_hash','sha256:'+'6'*64),
            'policy':('policy_hash','sha256:'+'7'*64),'catalog':('catalog_digest','sha256:'+'8'*64),
            'ledger':('ledger_id','00000000-0000-4000-8000-000000000000'),'reference':('original_approval_reference','other'),
            'schema':('schema_version','ia-language-config-adoption/2'),'pin':('image_digest','latest'),
            'transition':('transition_reference',''),'checkpoint':('checkpoint',dict(good['checkpoint'],count_requests=0)),
            'checkpoint_bool':('checkpoint',dict(good['checkpoint'],unresolved=0)),'extra':('aliases',[ACTIVE])}
        for name,(k,v) in mutations.items():
            with self.subTest(name):
                r=dict(good,**{k:v});raw=dumps(r)
                put(self.record,raw)
                put(self.approval,dumps(dict(approval,adoption_record_sha256='sha256:'+hashlib.sha256(raw).hexdigest())))
                self.blocked(active(self.root))
        put(self.record,dumps(good))
        for name,raw in {'noncanonical':json.dumps(good,indent=1).encode(),'truncated':dumps(good)[:-9],'empty':b''}.items():
            with self.subTest(name):
                put(self.record,raw)
                put(self.approval,dumps(dict(approval,adoption_record_sha256='sha256:'+hashlib.sha256(raw).hexdigest())))
                self.blocked(active(self.root))
        put(self.record,dumps(good));put(self.approval,dumps(approval));self.assertEqual(active(self.root).summary()['count_requests'],3)
        with self.subTest('sha_mismatch'):
            put(self.approval,dumps(dict(approval,adoption_record_sha256='sha256:'+'0'*64)));self.blocked(active(self.root))
        put(self.approval,dumps(approval))
        with self.subTest('wrong_runtime_catalog_or_missing_catalog'):
            self.blocked(BudgetLedger(ACTIVE,self.root,protected=False,catalog_digest='sha256:'+'d'*64))
            self.blocked(BudgetLedger(ACTIVE,self.root,protected=False))
        with self.subTest('symlink'):
            target=self.root/'real.json';self.record.rename(target);self.record.symlink_to(target);self.blocked(active(self.root))
            self.record.unlink();target.rename(self.record)
        with self.subTest('missing'):
            self.record.rename(self.root/'gone');self.blocked(active(self.root));(self.root/'gone').rename(self.record)
        with self.subTest('foreign_entry_provenance'):
            state=json.loads(self.pre);state['entries'][0]['config_hash']='sha256:'+'f'*64
            put(self.budget,dumps(state));self.blocked(active(self.root),job=False);put(self.budget,self.pre)
        with self.subTest('protected_owner_mode'):
            self.blocked(BudgetLedger(ACTIVE,self.root,protected=True,catalog_digest=CATALOG))
        self.assertEqual(self.budget.read_bytes(),self.pre)

    def test_strict_ceiling_and_stage_semantics(self):
        adopt(self.root);approval=json.loads(self.approval.read_bytes())
        for bad in (True,6.0,'6',0,-1,257,None,10**100):
            with self.subTest(bad=bad):
                put(self.approval,dumps(dict(approval,max_count_requests=bad)));self.blocked(active(self.root))
        missing=dict(approval);missing.pop('max_count_requests');put(self.approval,dumps(missing));self.blocked(active(self.root))
        put(self.approval,dumps(dict(approval,stage='qualification')));self.blocked(active(self.root))
        put(self.approval,dumps(dict(approval,schema_version='ia-language-approval/1')));self.blocked(active(self.root))
        put(self.approval,dumps(approval));self.assertEqual(active(self.root).summary()['max_count_requests'],6)

    def test_legacy_v1_evaluation_requires_ceiling_and_qualification_stays_three(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'ledger').mkdir(mode=0o700);ledger=BudgetLedger('sha256:'+'a'*64,root,protected=False)
            a=ledger.approval_template('fresh',stage='evaluation');a.pop('max_count_requests')
            (root/'approval.json').write_bytes(dumps(a))
            with self.assertRaises(LanguageError):ledger.initialize('fresh')
            (root/'approval.json').write_bytes(dumps(ledger.approval_template('fresh',max_count_requests=100)))
            ledger.initialize('fresh');self.assertEqual(ledger.summary()['max_count_requests'],3)
            for _ in range(3):
                e=ledger.reserve('test','h');ledger.count_dispatched(e);ledger.release_before_dispatch(e,'x')
            with self.assertRaises(LanguageError) as c:ledger.reserve('demo','h')
            self.assertEqual(c.exception.code,'qualification_reconciliation_required')
            # A staged record disables every legacy authority, including fresh same-config ones.
            (root/'config-adoption.json').write_bytes(b'{}');self.blocked(ledger)

    def test_legacy_origin_authority_cannot_spend_after_record_or_commit(self):
        origin=BudgetLedger(ADOPTION_ORIGIN_CONFIG_HASH,self.root,protected=False,catalog_digest=CATALOG)
        with self.assertRaises(LanguageError) as c:origin.reserve('test','h')
        self.assertEqual(c.exception.code,'qualification_reconciliation_required')  # cap3 before adoption
        adopt(self.root);self.blocked(origin)
        self.assertEqual(self.budget.read_bytes(),self.pre)

    def test_adopted_authority_never_initializes_even_if_budget_missing(self):
        adopt(self.root);self.budget.rename(self.root/'moved')
        with self.assertRaises(LanguageError) as c:active(self.root).initialize(REF)
        self.assertEqual(c.exception.code,'ledger_initialization_forbidden');self.assertFalse(self.budget.exists())
        for call in (active(self.root).summary,lambda:active(self.root).reserve('test','h')):
            with self.assertRaises(LanguageError):call()

    def refused(self,code,**over):
        before=self.approval.read_bytes()
        with self.assertRaises(helper.AdoptionError) as c:adopt(self.root,**over)
        self.assertEqual(c.exception.code,code);self.assertEqual(self.approval.read_bytes(),before)
        self.assertEqual(self.budget.read_bytes(),self.pre);return c

    def test_helper_refuses_bad_preconditions_without_writing(self):
        for over,code in (({'active_config_hash':ADOPTION_ORIGIN_CONFIG_HASH},'invalid_pin'),({'catalog_digest':'cc64'},'invalid_pin'),
                ({'image_digest':'sha256:'+'A'*64},'invalid_pin'),({'transition_reference':' '},'invalid_transition_reference'),
                ({'max_count_requests':3},'invalid_max_count_requests'),({'max_count_requests':257},'invalid_max_count_requests'),
                ({'max_count_requests':True},'invalid_max_count_requests')):
            with self.subTest(over=over):self.refused(code,**over);self.assertFalse(self.record.exists())
        a=json.loads(self.approval.read_bytes())
        for name,mut in {'stage':{'stage':'evaluation'},'config':{'config_hash':'sha256:'+'e'*64},'policy':{'policy_hash':'sha256:'+'e'*64}}.items():
            with self.subTest(name):
                put(self.approval,dumps(dict(a,**mut)));self.refused('approval_not_reviewed_origin');self.assertFalse(self.record.exists())
        put(self.approval,dumps(a))
        self.refused('root_required',protected=True)
        real=Path(os.path.realpath(self.root))
        with patch.object(helper.os,'geteuid',return_value=0):
            if real!=self.root:self.refused('control_realpath_mismatch',protected=True)
            with self.assertRaises(helper.AdoptionError) as c:helper.adopt(real,**dict(PINS,active_config_hash=ACTIVE,catalog_digest=CATALOG,max_count_requests=6))
            self.assertEqual(c.exception.code,'control_ancestor_unprotected')  # user-owned temp ancestors
            with patch.object(helper,'_ancestors'),self.assertRaises(LanguageError) as c:
                helper.adopt(real,**dict(PINS,active_config_hash=ACTIVE,catalog_digest=CATALOG,max_count_requests=6))
            self.assertEqual(c.exception.code,'control_permissions')  # temp owner/mode is not root:10001 0750
        self.assertFalse(self.record.exists());self.assertEqual(self.budget.read_bytes(),self.pre)

    def test_helper_refuses_ledger_state_mismatch(self):
        good=json.loads(self.pre)
        cases={'uuid':dict(good,ledger_id='00000000-0000-4000-8000-000000000001'),'header':dict(good,config_hash=ACTIVE),
            'sequence':dict(good,sequence=16),'reference':dict(good,approval_reference='x')}
        for state in ('reserved','dispatched','unknown'):
            s=copy.deepcopy(good);s['entries'].append(dict(s['entries'][0],entry_id='h',state=state,count_requests=0));cases[state]=s
        s=copy.deepcopy(good);s['entries'][0]['config_hash']=ACTIVE;cases['stamped']=s
        for name,state in cases.items():
            with self.subTest(name):
                put(self.budget,dumps(state));self.pre=self.budget.read_bytes()
                with self.assertRaises(helper.AdoptionError):adopt(self.root)
                self.assertFalse(self.record.exists());self.assertEqual(self.budget.read_bytes(),self.pre)

    def test_helper_refuses_halted_and_busy_locks_nonblocking(self):
        halt=self.root/'ledger'/'HALTED';halt.write_bytes(b'');self.refused('accounting_halted');halt.unlink()
        for lock in ('job.lock','budget.lock'):
            with self.subTest(lock):
                fd=os.open(self.root/'ledger'/lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                try:self.refused('busy');self.assertFalse(self.record.exists())
                finally:os.close(fd)
        (self.root/'ledger'/'job.lock').unlink()
        with self.assertRaises(OSError):adopt(self.root)  # never creates a root-owned service lock
        self.assertFalse((self.root/'ledger'/'job.lock').exists())

    def test_runtime_job_holder_blocks_adoption_and_adoption_blocks_runtime(self):
        origin=BudgetLedger(ADOPTION_ORIGIN_CONFIG_HASH,self.root,protected=False)
        fd=origin.acquire_job()
        try:self.refused('busy')
        finally:origin.release_job(fd)
        real=helper._adopt_locked;seen=[]
        def during(*a,**k):
            for call in (active(self.root).acquire_job,origin.acquire_job,origin.summary):
                with self.assertRaises(LanguageError) as c:call()
                seen.append(c.exception.code)
            return real(*a,**k)
        with patch.object(helper,'_adopt_locked',during):adopt(self.root)
        self.assertEqual(seen,['approval_unavailable','busy','accounting_busy'])

    def test_fault_injection_blocks_and_never_resets(self):
        real_fsync,real_replace=os.fsync,os.replace
        faults={'record_fsync':('fsync',1),'record_dir_fsync':('fsync',2),'approval_fsync':('fsync',3),
            'approval_rename':('replace',1),'approval_dir_fsync':('fsync',5)}
        for name,(kind,n) in faults.items():
            with self.subTest(name):
                self.tearDown();self.setUp();calls=[]
                def fail(*a,real=real_fsync if kind=='fsync' else real_replace):
                    calls.append(a)
                    if len(calls)==n:raise OSError('injected')
                    return real(*a)
                with patch.object(helper.os,kind,side_effect=fail):
                    with self.assertRaises(helper.AdoptionError) as c:adopt(self.root)
                self.assertEqual(c.exception.code,'adoption_commit_uncertain_halted')
                self.assertTrue((self.root/'ledger'/'HALTED').exists());self.assertEqual(self.budget.read_bytes(),self.pre)
                self.blocked(active(self.root));self.blocked(BudgetLedger(ADOPTION_ORIGIN_CONFIG_HASH,self.root,protected=False))
                self.refused('accounting_halted')
        with self.subTest('postverify'):
            self.tearDown();self.setUp()
            with patch.object(BudgetLedger,'_read',side_effect=LanguageError('ledger_unavailable',503)):
                with self.assertRaises(helper.AdoptionError):adopt(self.root)
            self.assertTrue((self.root/'ledger'/'HALTED').exists());self.assertEqual(self.budget.read_bytes(),self.pre)

    def test_crash_after_record_resumes_identical_record_only(self):
        sha='sha256:'+hashlib.sha256(self.pre).hexdigest()
        record=dumps(adoption_record(active_config_hash=ACTIVE,catalog_digest=CATALOG,original_approval_reference=REF,budget_sha256=sha,**PINS))
        conflict=dumps(adoption_record(active_config_hash=ACTIVE,catalog_digest=CATALOG,original_approval_reference=REF,budget_sha256=sha,**dict(PINS,transition_reference='other-go')))
        helper._publish_exclusive(self.record,conflict,False)  # interrupted conflicting transition
        self.blocked(active(self.root));self.blocked(BudgetLedger(ADOPTION_ORIGIN_CONFIG_HASH,self.root,protected=False))
        self.refused('adoption_conflict');self.assertEqual(self.record.read_bytes(),conflict)
        self.record.unlink();helper._publish_exclusive(self.record,record,False)  # interrupted identical transition
        out=adopt(self.root);self.assertTrue(out['resumed']);self.assertEqual(self.record.read_bytes(),record)
        again=adopt(self.root);self.assertTrue(again['resumed']);self.assertEqual(again['adoption_record_sha256'],out['adoption_record_sha256'])
        self.refused('adoption_conflict',transition_reference='other-go')
        self.refused('adoption_conflict',max_count_requests=7)
        self.assertEqual(self.budget.read_bytes(),self.pre)

class AdoptedProviderAndOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from public_app import load_core
        from districtbrief.investigation import Investigation
        cls.i=Investigation(load_core())
    def setUp(self):
        import test_ia_language_contract as contract
        from districtbrief.ia_language import prepare_request
        from test_ia_language_accounting import usage
        self.tmp=tempfile.TemporaryDirectory();self.root=baseline(self.tmp.name);adopt(self.root)
        h=contract.LanguageContractTests();h.i=self.i;self.prepared=prepare_request(h.request(),self.i,'session')
        self.calls=[];self.secrets=0;self.usage=usage()
    def tearDown(self):self.tmp.cleanup()
    def transport(self,method,path,body,secret,deadline):
        from districtbrief.ia_language_provider import MODEL
        self.calls.append(path)
        if path.endswith('input_tokens'):return 200,{'object':'response.input_tokens','input_tokens':1000}
        return 200,{'status':'completed','model':MODEL,'service_tier':'default','reasoning':{'effort':'low'},'usage':self.usage,'output':[]}
    def secret(self):self.secrets+=1;return 'fake-secret-never-network'
    def test_three_fake_calls_then_no_secret_or_transport_both_buckets(self):
        from districtbrief.ia_language_provider import OpenAIProvider
        provider=OpenAIProvider(transport=self.transport,secret_reader=self.secret)
        for _ in range(3):
            with self.assertRaises(LanguageError):  # semantic/output failure still consumes the attempt
                provider.interpret(self.prepared,active(self.root),'test',threading.Event(),time.monotonic()+25,lambda:None)
        self.assertEqual(len(self.calls),6);self.assertEqual(self.secrets,3)
        s=active(self.root).summary();self.assertEqual((s['count_requests'],s['count_capacity_remaining'],s['unresolved']),(6,0,False))
        self.assertEqual(s['buckets']['test']['settled_usage_estimate_nano_usd'],27539000+3*1500000)
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError):
                OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,active(self.root),bucket,threading.Event(),time.monotonic()+25,lambda:None)
        self.assertEqual(len(self.calls),6);self.assertEqual(self.secrets,3)
    def test_forged_record_blocks_before_secret_and_transport(self):
        from districtbrief.ia_language_provider import OpenAIProvider
        rec=self.root/'config-adoption.json';put(rec,rec.read_bytes().replace(b'root-go',b'rootxgo'))
        with self.assertRaises(LanguageError):
            OpenAIProvider(transport=self.transport,secret_reader=self.secret).interpret(self.prepared,active(self.root),'test',threading.Event(),time.monotonic()+25,lambda:None)
        self.assertEqual((self.calls,self.secrets),([],0))
    def test_operator_evaluate_refuses_before_question_input_under_cap6(self):
        from tools import ia_language_operator as operator
        opened=[]
        def ledger(config_hash,**kw):
            self.assertEqual(kw['catalog_digest'][:7],'sha256:');return active(self.root)
        with patch.object(operator,'BudgetLedger',ledger),patch.object(operator,'questions',side_effect=lambda *a,**k:opened.append(a)),\
                patch.object(operator,'protected_path',side_effect=lambda *a,**k:opened.append(a)):
            out=io.StringIO()
            with redirect_stdout(out):code=operator.main(['evaluate','--questions','/run/ia1-eval/sealed.jsonl','--output','/run/ia1-eval/results/x.jsonl'])
        self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue())['code'],'count_capacity_insufficient');self.assertEqual(opened,[])
    def test_operator_identity_reports_computed_hash_without_control_access(self):
        from tools import ia_language_operator as operator
        from districtbrief.ia_language_provider import configuration_hash
        out=io.StringIO()
        with patch.object(BudgetLedger,'approval',side_effect=AssertionError('no control access')),redirect_stdout(out):
            self.assertEqual(operator.main(['identity']),0)
        r=json.loads(out.getvalue());self.assertEqual(r['active_config_hash'],configuration_hash(r['catalog_digest']));self.assertEqual(r['policy_hash'],POLICY_HASH)

if __name__=='__main__':unittest.main()
