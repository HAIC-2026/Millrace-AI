"""Offline THIRD configuration adoption (record-2 active 82a -> one new active) on the same ledger.
Temp directories with a SYNTHETIC 7-entry checkpoint (synthetic entry IDs/timestamps/payload hashes/record-2
bindings); no actual ledger bytes, host control state or network. Differences from production: the record-2,
approval-3 and budget SHA pins are overridden test-locally (accounting module and helper module) with the
synthetic fixture's hashes; every function under test (parser, validators, locks, publish, post-verify) runs
unstubbed. Separate tests prove the unpatched production pins are the reviewed values and refuse the synthetic
fixture. The exact actual-checkpoint proof is private evidence outside the source package.
Protected-mode cases here use the local owner mapping only; they are not actual Linux root proof."""
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from districtbrief.ia_language import LanguageError, dumps, strict_json
from districtbrief import ia_language_accounting as acc
from districtbrief.ia_language_accounting import (ADOPTION1_ACTIVE_CONFIG_HASH, ADOPTION1_RECORD_SHA256, ADOPTION2_ACTIVE_CONFIG_HASH,
    ADOPTION2_RECORD_SHA256, ADOPTION3_BUDGET_SHA256, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY_HASH, BudgetLedger,
    approval_v4, reservation)
from tools import ia_language_config_adoption_3 as helper

FIXTURES=Path(__file__).parent/'fixtures'
V5=json.loads((FIXTURES/'ia-language-dev-v5-replay.json').read_text())
CP=json.loads((FIXTURES/'ia-language-adoption3-synthetic.json').read_text())
assert CP['synthetic'] is True
PINS_OVERRIDE=CP['test_pin_overrides']
RECORD2_PIN,APPROVAL3_PIN,BUDGET_PIN=(PINS_OVERRIDE[k] for k in ('ADOPTION2_RECORD_SHA256','APPROVAL3_SHA256','ADOPTION3_BUDGET_SHA256'))
PRODUCTION={'ADOPTION2_RECORD_SHA256':'sha256:b9658c7dd729cda749c51433cf62afcbd7fc7ae491d9f0189018c34427476612',
    'APPROVAL3_SHA256':'sha256:9fdf89a68066212d2057eae6c49e6ca1aa3735100bd523c41be7742b04d19b3a',
    'ADOPTION3_BUDGET_SHA256':'sha256:e54e30ce03d8db72982e4cd8dbf5bb24712b8fbacd002d12dedad4c7279ae888'}
RECORD1=dumps(V5['first_adoption_record']);RECORD2=dumps(CP['record2']);APPROVAL3=dumps(CP['approval3']);BUDGET=dumps(CP['budget'])
REF=CP['record2']['original_approval_reference'];CATALOG=CP['record2']['catalog_digest']
NEW='sha256:'+'1'*64
PINS={'transition_reference':'root-go-adoption-3','source_component_sha256':'sha256:'+'2'*64,
      'image_digest':'sha256:'+'3'*64,'review_receipt_sha256':'sha256:'+'4'*64}
def sha(raw):return 'sha256:'+__import__('hashlib').sha256(raw).hexdigest()
def fp(p):s=os.stat(p);return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
def put(path,data):
    if path.exists():os.chmod(path,0o640)  # offline fixtures only: published files are 0440
    path.write_bytes(data)

class ThirdAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.override()
        self.tmp=tempfile.TemporaryDirectory();r=self.root=Path(self.tmp.name)
        (r/'ledger').mkdir(mode=0o700)
        for name,data in (('config-adoption.json',RECORD1),('config-adoption-2.json',RECORD2),('approval.json',APPROVAL3)):(r/name).write_bytes(data)
        (r/'ledger'/'budget.json').write_bytes(BUDGET)
        for lock in ('job.lock','budget.lock'):(r/'ledger'/lock).write_bytes(b'')
        self.budget=r/'ledger'/'budget.json';self.approval=r/'approval.json';self.record3=r/'config-adoption-3.json'
        self.history={p:(p.read_bytes(),fp(p)) for p in (self.budget,r/'config-adoption.json',r/'config-adoption-2.json')}
        time.sleep(0.01)  # a rewrite would visibly move mtime_ns
    def tearDown(self):
        if (self.root/'ledger').is_dir():os.chmod(self.root/'ledger',0o700)  # undo uncreatable_marker
        self.tmp.cleanup()
    def override(self):
        # Test-local pin overrides only (constants, not functions): accounting globals and the helper's imported copies.
        for module,names in ((acc,('ADOPTION2_RECORD_SHA256','ADOPTION3_BUDGET_SHA256')),(helper,('ADOPTION2_RECORD_SHA256','ADOPTION3_BUDGET_SHA256','APPROVAL3_SHA256'))):
            for name in names:
                p=patch.object(module,name,PINS_OVERRIDE[name]);p.start();self.addCleanup(p.stop)
    def adopt(self,**over):
        kw=dict(active_config_hash=NEW,catalog_digest=CATALOG,expected_budget_sha256=BUDGET_PIN,max_count_requests=7,protected=False,**PINS)
        kw.update(over);return helper.adopt3(self.root,**kw)
    def refused(self,code,**over):
        with self.assertRaises(helper.AdoptionError) as c:self.adopt(**over)
        self.assertEqual(c.exception.code,code)
    def ledger(self,config=NEW):return BudgetLedger(config,self.root,protected=False,catalog_digest=CATALOG)
    def assert_history(self):
        for p,(raw,f) in self.history.items():self.assertEqual((p.read_bytes(),fp(p)),(raw,f),p.name)
    def assert_untouched(self):
        self.assert_history();self.assertEqual(self.approval.read_bytes(),APPROVAL3);self.assertFalse(self.record3.exists())

    def test_production_pins_are_reviewed_values_and_refuse_the_synthetic_fixture(self):
        patch.stopall()  # drop only this test's overrides; cleanup stop() calls are idempotent
        self.assertEqual({k:getattr(acc if k!='APPROVAL3_SHA256' else helper,k) for k in PRODUCTION},PRODUCTION)
        self.assertEqual({k:getattr(helper,k) for k in PRODUCTION},PRODUCTION)
        self.assertNotIn(BUDGET_PIN,PRODUCTION.values());self.assertNotIn(RECORD2_PIN,PRODUCTION.values())
        self.refused('second_record_mismatch',expected_budget_sha256=PRODUCTION['ADOPTION3_BUDGET_SHA256'])  # synthetic record 2 is never the reviewed record 2
        self.refused('budget_pin_mismatch',expected_budget_sha256=BUDGET_PIN)  # only the e54 budget is admissible
        self.assert_untouched()

    def test_fixture_is_synthetic_and_matches_test_pins(self):
        self.assertTrue(CP['synthetic']);self.assertTrue(all(e['entry_id'].startswith('00000000-0000-4000-8000-') for e in CP['budget']['entries']))
        self.assertTrue(CP['record2']['transition_reference'].startswith('SYNTHETIC'))
        self.assertEqual([sha(x) for x in (RECORD1,RECORD2,APPROVAL3,BUDGET)],
            [ADOPTION1_RECORD_SHA256,RECORD2_PIN,APPROVAL3_PIN,BUDGET_PIN])
        self.assertEqual((acc.ADOPTION2_RECORD_SHA256,acc.ADOPTION3_BUDGET_SHA256,helper.APPROVAL3_SHA256),(RECORD2_PIN,BUDGET_PIN,APPROVAL3_PIN))
        s=self.ledger(ADOPTION2_ACTIVE_CONFIG_HASH).summary()  # current v3 authority still reads before adoption
        self.assertEqual((s['approval_schema'],s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining'],s['adoption3_record_sha256']),
            ('ia-language-approval/3',35,7,7,0,None))
        self.assertEqual(s['config_lineage'],[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH])

    def test_adopts_exactly_once_with_zero_headroom_and_preserves_history(self):
        out=self.adopt()
        self.assert_history()
        record=self.record3.read_bytes();r=strict_json(record)
        self.assertEqual((r['schema_version'],r['previous_active_config_hash'],r['previous_adoption_record_sha256'],r['active_config_hash'],r['checkpoint']),
            ('ia-language-config-adoption/3',ADOPTION2_ACTIVE_CONFIG_HASH,RECORD2_PIN,NEW,
             {'sequence':35,'count_requests':7,'settled_nano_usd':63617000,'held_nano_usd':0,'unresolved':False,'budget_sha256':BUDGET_PIN}))
        self.assertEqual({k:r[k] for k in PINS},PINS)
        self.assertEqual(self.approval.read_bytes(),dumps(approval_v4(REF,NEW,sha(record),7)))
        a=strict_json(self.approval.read_bytes())
        self.assertEqual((a['adoption_record_sha256'],a['adoption2_record_sha256'],a['adoption3_record_sha256'],a['max_count_requests'],a['policy_hash']),
            (ADOPTION1_RECORD_SHA256,RECORD2_PIN,sha(record),7,POLICY_HASH))
        s=self.ledger().summary()
        self.assertEqual(s['config_lineage'],[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,NEW])
        self.assertEqual([(x['record'],x['sha256'],x['transition_reference']) for x in s['adoption_lineage']],
            [('config-adoption.json',ADOPTION1_RECORD_SHA256,V5['first_adoption_record']['transition_reference']),
             ('config-adoption-2.json',RECORD2_PIN,CP['record2']['transition_reference']),
             ('config-adoption-3.json',sha(record),'root-go-adoption-3')])
        self.assertEqual((s['previous_active_config_hash'],s['active_config_hash'],s['financial_origin_config_hash'],s['ledger_id'],
            s['count_capacity_remaining'],s['buckets']['test']['settled_usage_estimate_nano_usd'],s['unresolved']),
            (ADOPTION2_ACTIVE_CONFIG_HASH,NEW,ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION_LEDGER_ID,0,63617000,False))
        self.assertEqual((out['provider_calls'],out['ledger_writes'],out['count_capacity_remaining'],out['resumed']),(0,0,0,False))
        with self.assertRaises(LanguageError) as c:self.ledger().reserve('test','sha256:'+'9'*64)
        self.assertEqual(c.exception.code,'count_ceiling_reached');self.assert_history()
        # Idempotent re-run after commit: no write, same authority.
        before=(self.approval.read_bytes(),fp(self.approval),record,fp(self.record3))
        self.assertTrue(self.adopt()['resumed']);self.assertEqual((self.approval.read_bytes(),fp(self.approval),self.record3.read_bytes(),fp(self.record3)),before)
        # Old record-2 authority and config can no longer spend.
        with self.assertRaises(LanguageError):self.ledger(ADOPTION2_ACTIVE_CONFIG_HASH).summary()

    def test_fixed_pins_and_inputs_refuse_without_writes(self):
        for code,over in (('invalid_max_count_requests',{'max_count_requests':8}),('invalid_max_count_requests',{'max_count_requests':127}),
                          ('budget_pin_mismatch',{'expected_budget_sha256':'sha256:'+'5'*64}),('invalid_pin',{'active_config_hash':ADOPTION2_ACTIVE_CONFIG_HASH}),
                          ('invalid_pin',{'active_config_hash':ADOPTION1_ACTIVE_CONFIG_HASH}),('invalid_pin',{'active_config_hash':ADOPTION_ORIGIN_CONFIG_HASH}),
                          ('invalid_pin',{'image_digest':'latest'}),('invalid_transition_reference',{'transition_reference':CP['record2']['transition_reference']}),
                          ('invalid_transition_reference',{'transition_reference':' '}),('root_required' if os.geteuid()!=0 else 'control_ancestor_unprotected',{'protected':True})):
            with self.subTest(code=code,over=over):self.refused(code,**over);self.assert_untouched()

    def test_wrong_records_or_approval_refuse(self):
        for name,data,code in (('config-adoption.json',RECORD1+b' ','first_record_mismatch'),('config-adoption-2.json',RECORD2.replace(b'SYNTHETIC',b'SYNTHETIX'),'second_record_mismatch'),
                               ('approval.json',dumps(dict(CP['approval3'],max_count_requests=8)),'approval_not_reviewed_second_transition'),
                               ('approval.json',dumps(dict(CP['approval3'],config_hash=NEW)),'approval_not_reviewed_second_transition')):
            with self.subTest(name=name):
                old=(self.root/name).read_bytes();put(self.root/name,data);self.refused(code);put(self.root/name,old)
                self.assertFalse(self.record3.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL3)

    def test_ledger_counter_uuid_and_stamp_mismatches_halt_before_publish(self):
        def mutate(f):
            b=copy.deepcopy(CP['budget']);f(b);return dumps(b)
        def seq(b):b['sequence']=36
        def held(b):b['entries'][-1].update(state='dispatched')
        def uuid(b):b['ledger_id']='00000000-0000-4000-8000-000000000000'
        def stamp(b):b['entries'][-1]['config_hash']=ADOPTION1_ACTIVE_CONFIG_HASH
        def unstamped(b):del b['entries'][3]['config_hash']
        def extra(b):b['entries'].append(dict(b['entries'][-1],sequence=36,entry_id='x'));b['sequence']=40
        def settled(b):b['entries'][-1]['settled_estimate_nano_usd']+=1
        cases=(('seq',seq,'ledger_checkpoint_mismatch'),('held',held,'ledger_checkpoint_mismatch'),('uuid',uuid,'ledger_identity_mismatch'),
               ('stamp',stamp,'ledger_checkpoint_mismatch'),('unstamped',unstamped,'ledger_checkpoint_mismatch'),('extra',extra,'ledger_checkpoint_mismatch'),
               ('settled',settled,'ledger_checkpoint_mismatch'))
        for name,f,code in cases:
            with self.subTest(name=name):
                data=mutate(f);put(self.budget,data)
                self.refused('budget_pin_mismatch')  # the exact e54 pin refuses first
                with patch.object(helper,'ADOPTION3_BUDGET_SHA256',sha(data)):self.refused(code,expected_budget_sha256=sha(data))
                self.assertFalse(self.record3.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL3);self.assertFalse((self.root/'ledger'/'HALTED').exists())
        put(self.budget,BUDGET)

    def test_conflicts_halt_marker_locks_and_missing_ledger(self):
        put(self.record3,b'{}');self.refused('adoption_conflict');self.record3.unlink()
        put(self.approval,dumps(approval_v4(REF,NEW,'sha256:'+'6'*64,7)));self.refused('adoption_conflict');put(self.approval,APPROVAL3)
        (self.root/'ledger'/'HALTED').write_bytes(b'');self.refused('accounting_halted');(self.root/'ledger'/'HALTED').unlink()
        for lock in ('job.lock','budget.lock'):
            fd=os.open(self.root/'ledger'/lock,os.O_RDWR)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.refused('busy')
            finally:os.close(fd)
        self.assert_untouched()
        self.budget.unlink()
        with self.assertRaises((helper.AdoptionError,OSError,LanguageError)):self.adopt()
        self.assertFalse(self.budget.exists());self.assertFalse(self.record3.exists())

    def test_io_failure_after_record_publish_halts_and_fails_closed(self):
        with patch.object(helper,'_publish_atomic',side_effect=OSError('disk')):self.refused('adoption_commit_uncertain_halted')
        self.assertTrue((self.root/'ledger'/'HALTED').exists());self.assertTrue(self.record3.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL3)
        self.assert_history()
        # Staged record 3 disables the v3 authority; the new config has no v4 approval; nothing initializes.
        for config in (ADOPTION2_ACTIVE_CONFIG_HASH,NEW):
            with self.assertRaises(LanguageError):self.ledger(config).summary()
        self.refused('accounting_halted')
        with patch.object(helper,'_publish_exclusive',side_effect=OSError('disk')):
            self.record3.unlink();(self.root/'ledger'/'HALTED').unlink();self.refused('adoption_commit_uncertain_halted')
        self.assertFalse(self.record3.exists());self.assertTrue((self.root/'ledger'/'HALTED').exists());self.assert_history()

    def uncreatable_marker(self):
        os.chmod(self.root/'ledger',0o500)  # restored in tearDown
    def test_unconfirmed_halt_marker_is_reported_distinctly_and_state_left_for_inspection(self):
        # Fault after record 3 publish, and the HALTED marker cannot be created: never claim "halted".
        def fault(*_a,**_k):self.uncreatable_marker();raise OSError('approval storage fault')
        with patch.object(helper,'_publish_atomic',side_effect=fault):self.refused('adoption_commit_uncertain_halt_unconfirmed')
        self.assertFalse((self.root/'ledger'/'HALTED').exists());self.assertTrue(self.record3.exists())
        self.assertEqual(self.approval.read_bytes(),APPROVAL3);self.assert_history()
    def test_fault_after_approval_commit_halts_or_reports_unconfirmed(self):
        real=acc.BudgetLedger._read
        def failing(ledger):raise LanguageError('ledger_unavailable',503)
        with patch.object(acc.BudgetLedger,'_read',failing):self.refused('adoption_commit_uncertain_halted')
        self.assertTrue((self.root/'ledger'/'HALTED').exists())
        self.assertEqual(strict_json(self.approval.read_bytes())['schema_version'],'ia-language-approval/4')  # partial state left as found
        self.assertTrue(self.record3.exists());self.assert_history()
        # Same fault point, marker uncreatable.
        self.tearDown();self.setUp()
        def failing2(ledger):self.uncreatable_marker();raise LanguageError('ledger_unavailable',503)
        with patch.object(acc.BudgetLedger,'_read',failing2):self.refused('adoption_commit_uncertain_halt_unconfirmed')
        self.assertFalse((self.root/'ledger'/'HALTED').exists());self.assertEqual(strict_json(self.approval.read_bytes())['schema_version'],'ia-language-approval/4')
        self.assert_history()
    def test_cli_commit_uncertain_envelope_exit3_and_refusal_exit2(self):
        real=helper.adopt3
        argv=['--control-dir',str(self.root),'--active-config-hash',NEW,'--catalog-digest',CATALOG,'--transition-reference','root-go-adoption-3',
            '--source-component-sha256',PINS['source_component_sha256'],'--image-digest',PINS['image_digest'],'--review-receipt-sha256',PINS['review_receipt_sha256'],
            '--expected-budget-sha256',BUDGET_PIN,'--max-count-requests','7']
        def run():
            buf=io.StringIO()
            with patch.object(helper,'adopt3',lambda *a,**k:real(*a,**dict(k,protected=False))),redirect_stdout(buf):code=helper.main(argv)
            return code,json.loads(buf.getvalue())
        with patch.object(helper,'_publish_atomic',side_effect=OSError('fault')):code,out=run()
        self.assertEqual((code,out['status'],out['code'],out['inspect_control_state']),(3,'commit_uncertain','adoption_commit_uncertain_halted',True))
        self.assertTrue((self.root/'ledger'/'HALTED').exists())
        code,out=run()  # halted: ordinary pre-write refusal
        self.assertEqual((code,out['status'],out['code']),(2,'refused','accounting_halted'))
        (self.root/'ledger'/'HALTED').unlink();self.record3.unlink()
        def fault(*_a,**_k):self.uncreatable_marker();raise OSError('fault')
        with patch.object(helper,'_publish_atomic',side_effect=fault):code,out=run()
        self.assertEqual((code,out['status'],out['code']),(3,'commit_uncertain','adoption_commit_uncertain_halt_unconfirmed'))

    def test_runtime_v4_lineage_positions_and_no_reinitialization(self):
        self.adopt();base=copy.deepcopy(CP['budget'])
        def entry(stamp,seq):
            return {'entry_id':'e-new','sequence':seq,'bucket':'test','state':'reserved','created_at':1.0,'reserved_nano_usd':reservation(),
                'settled_estimate_nano_usd':None,'payload_hash':'sha256:'+'9'*64,'config_hash':stamp,'counted_input_tokens':None,
                'count_requests':0,'model_calls':0,'usage':None,'terminal_code':None}
        for stamp,seq,ok in ((NEW,36,True),(ADOPTION2_ACTIVE_CONFIG_HASH,36,False),(ADOPTION1_ACTIVE_CONFIG_HASH,36,False),
                             (ADOPTION_ORIGIN_CONFIG_HASH,36,False),(NEW,35,False),('sha256:'+'7'*64,36,False)):
            with self.subTest(stamp=stamp[:15],seq=seq):
                b=copy.deepcopy(base);b['entries'].append(entry(stamp,seq));b['sequence']=seq;put(self.budget,dumps(b))
                if ok:self.assertTrue(self.ledger().summary()['unresolved'])
                else:
                    with self.assertRaises(LanguageError) as c:self.ledger().summary()
                    self.assertEqual(c.exception.code,'ledger_unavailable')
        put(self.budget,BUDGET)
        # Reserve through the runtime stamps NEW at seq 36 only after a separate cap raise; at ceiling 7 it refuses.
        with self.assertRaises(LanguageError):self.ledger().initialize(REF)
        self.budget.unlink()
        with self.assertRaises(LanguageError) as c:self.ledger().initialize(REF)
        self.assertEqual(c.exception.code,'ledger_initialization_forbidden');self.assertFalse(self.budget.exists())

    def test_backward_compatibility_of_first_and_second_authorities(self):
        # v1 and v2 refuse whenever a third record exists; v3 refuses once record 3 is staged.
        self.record3.write_bytes(b'{}')
        l=self.ledger(ADOPTION_ORIGIN_CONFIG_HASH)
        put(self.approval,dumps(l.approval_template(REF)))
        with self.assertRaises(LanguageError):l.approval()
        from districtbrief.ia_language_accounting import approval_v2
        put(self.approval,dumps(approval_v2(REF,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,6)))
        with self.assertRaises(LanguageError):self.ledger(ADOPTION1_ACTIVE_CONFIG_HASH).approval()
        put(self.approval,APPROVAL3)
        with self.assertRaises(LanguageError):self.ledger(ADOPTION2_ACTIVE_CONFIG_HASH).approval()
        self.record3.unlink();self.assertEqual(self.ledger(ADOPTION2_ACTIVE_CONFIG_HASH).approval()['schema_version'],'ia-language-approval/3')

    def test_cli_refusal_shape(self):
        buf=io.StringIO()
        with redirect_stdout(buf):code=helper.main(['--control-dir',str(self.root),'--active-config-hash',NEW,'--catalog-digest',CATALOG,
            '--transition-reference','x','--source-component-sha256','sha256:'+'2'*64,'--image-digest','sha256:'+'3'*64,
            '--review-receipt-sha256','sha256:'+'4'*64,'--expected-budget-sha256',BUDGET_PIN,'--max-count-requests','7'])
        self.assertEqual(code,2);out=json.loads(buf.getvalue())
        self.assertEqual((out['status'],out['provider_calls']),('refused',0));self.assertIn(out['code'],('root_required','control_ancestor_unprotected'))
        self.assert_untouched()

if __name__=='__main__':unittest.main()
