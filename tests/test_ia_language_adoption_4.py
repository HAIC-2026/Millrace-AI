"""Offline FOURTH configuration adoption (record-3 active 829 -> one new active) on the same ledger.
Temp directories with a SYNTHETIC 127-entry checkpoint (synthetic entry IDs/timestamps/payload hashes and
synthetic record-2/record-3 bindings); no actual ledger bytes, host control state or network. Differences
from production: the record-2, record-3, approval-4 and budget SHA pins are overridden test-locally with the
synthetic fixture's hashes; every function under test (parser, validators, locks, publish, post-verify) runs
unstubbed. A separate test proves the unpatched production pins are the reviewed values and refuse the
synthetic fixture. The exact actual-checkpoint proof is private evidence outside the source package.
Protected-mode cases here use the local owner mapping only; they are not actual Linux root proof."""
import copy
import fcntl
import hashlib
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
    ADOPTION3_ACTIVE_CONFIG_HASH, ADOPTION_HISTORICAL_CATALOG_DIGEST, ADOPTION_LEDGER_ID, ADOPTION_ORIGIN_CONFIG_HASH, POLICY_HASH,
    BudgetLedger, approval_v5, reservation)
from tools import ia_language_config_adoption_4 as helper

FIXTURES=Path(__file__).parent/'fixtures'
V5=json.loads((FIXTURES/'ia-language-dev-v5-replay.json').read_text())
CP=json.loads((FIXTURES/'ia-language-adoption4-synthetic.json').read_text())
assert CP['synthetic'] is True
OVERRIDE=CP['test_pin_overrides']
ACC_PINS=('ADOPTION2_RECORD_SHA256','ADOPTION3_BUDGET_SHA256','ADOPTION3_RECORD_SHA256','ADOPTION4_BUDGET_SHA256')
PRODUCTION={'ADOPTION2_RECORD_SHA256':'sha256:b9658c7dd729cda749c51433cf62afcbd7fc7ae491d9f0189018c34427476612',
    'ADOPTION3_BUDGET_SHA256':'sha256:e54e30ce03d8db72982e4cd8dbf5bb24712b8fbacd002d12dedad4c7279ae888',
    'ADOPTION3_RECORD_SHA256':'sha256:d89e7782dd312fd00390da4f661b2b852ed0457b644dca49f0bf4c0724703fc0',
    'ADOPTION4_BUDGET_SHA256':'sha256:9746c445dcbb36e95a9eb7c40093d134bc0880410b14c087941fc5e0050dfffe'}
PRODUCTION_APPROVAL4='sha256:74ede06c347c9e20794f4387d55d6c35dcd414f9fc6760d7c9437e4408dc8356'
RECORD1=dumps(V5['first_adoption_record']);RECORD2=dumps(CP['record2']);RECORD3=dumps(CP['record3'])
APPROVAL4=dumps(CP['approval4']);BUDGET=dumps(CP['budget'])
REF=CP['record3']['original_approval_reference']
NEW='sha256:'+'1'*64
NEW_CATALOG='sha256:'+'8'*64  # deliberately NOT the historical catalog: only record 4 binds the running catalog
PINS={'transition_reference':'root-go-adoption-4','source_component_sha256':'sha256:'+'2'*64,
      'image_digest':'sha256:'+'3'*64,'review_receipt_sha256':'sha256:'+'4'*64}
CHECKPOINT={'sequence':635,'count_requests':127,'settled_nano_usd':1101867000,'held_nano_usd':0,'unresolved':False}
def sha(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()
def fp(p):s=os.stat(p);return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
def put(path,data):
    if path.exists():os.chmod(path,0o640)  # offline fixtures only: published files are 0440
    path.write_bytes(data)

class FourthAdoptionTests(unittest.TestCase):
    def setUp(self):
        for name in ACC_PINS:
            p=patch.object(acc,name,OVERRIDE[name]);p.start();self.addCleanup(p.stop)
        p=patch.object(helper,'APPROVAL4_SHA256',OVERRIDE['APPROVAL4_SHA256']);p.start();self.addCleanup(p.stop)
        self.tmp=tempfile.TemporaryDirectory();r=self.root=Path(self.tmp.name)
        (r/'ledger').mkdir(mode=0o700)
        for name,data in (('config-adoption.json',RECORD1),('config-adoption-2.json',RECORD2),('config-adoption-3.json',RECORD3),
                ('approval.json',APPROVAL4)):(r/name).write_bytes(data)
        (r/'ledger'/'budget.json').write_bytes(BUDGET)
        for lock in ('job.lock','budget.lock'):(r/'ledger'/lock).write_bytes(b'')
        self.budget=r/'ledger'/'budget.json';self.approval=r/'approval.json';self.record4=r/'config-adoption-4.json'
        self.halted=r/'ledger'/'HALTED'
        self.history={p:(p.read_bytes(),fp(p)) for p in (self.budget,r/'config-adoption.json',r/'config-adoption-2.json',r/'config-adoption-3.json')}
        time.sleep(0.01)  # a rewrite would visibly move mtime_ns
    def tearDown(self):
        if (self.root/'ledger').is_dir():os.chmod(self.root/'ledger',0o700)  # undo uncreatable_marker
        self.tmp.cleanup()
    def adopt(self,**over):
        kw=dict(active_config_hash=NEW,catalog_digest=NEW_CATALOG,expected_budget_sha256=OVERRIDE['ADOPTION4_BUDGET_SHA256'],
            max_count_requests=127,protected=False,**PINS)
        kw.update(over);return helper.adopt4(self.root,**kw)
    def refused(self,code,**over):
        with self.assertRaises(helper.AdoptionError) as c:self.adopt(**over)
        self.assertEqual(c.exception.code,code)
    def ledger(self,config=NEW,catalog=NEW_CATALOG):return BudgetLedger(config,self.root,protected=False,catalog_digest=catalog)
    def old_ledger(self):return self.ledger(ADOPTION3_ACTIVE_CONFIG_HASH,ADOPTION_HISTORICAL_CATALOG_DIGEST)
    def assert_history(self):
        for p,(raw,f) in self.history.items():self.assertEqual((p.read_bytes(),fp(p)),(raw,f),p.name)
    def assert_untouched(self):
        self.assert_history();self.assertEqual(self.approval.read_bytes(),APPROVAL4);self.assertFalse(self.record4.exists())
    def uncreatable_marker(self):os.chmod(self.root/'ledger',0o500)  # restored in tearDown

    def test_production_pins_are_reviewed_values_and_refuse_the_synthetic_fixture(self):
        patch.stopall()  # drop only this test's overrides; cleanup stop() calls are idempotent
        self.assertEqual({k:getattr(acc,k) for k in PRODUCTION},PRODUCTION)
        self.assertEqual(helper.APPROVAL4_SHA256,PRODUCTION_APPROVAL4)
        self.assertEqual((acc.ADOPTION4_CHECKPOINT,acc.ADOPTION4_MAX_COUNT_REQUESTS,acc.ADOPTION3_ACTIVE_CONFIG_HASH),
            (CHECKPOINT,127,'sha256:829d32a72679282b91c8232e29f9a7786a1293b83f8791e208caba79340d8739'))
        self.assertFalse(set(OVERRIDE.values())&(set(PRODUCTION.values())|{PRODUCTION_APPROVAL4}))
        # The exact committed approval v4 at ceiling 127 is derivable from reviewed constants alone.
        self.assertEqual(sha(dumps(acc.approval_v4(REF,acc.ADOPTION3_ACTIVE_CONFIG_HASH,acc.ADOPTION3_RECORD_SHA256,127))),PRODUCTION_APPROVAL4)
        self.refused('second_record_mismatch',expected_budget_sha256=PRODUCTION['ADOPTION4_BUDGET_SHA256'])  # synthetic records are never the reviewed records
        self.refused('budget_pin_mismatch')  # only the 9746 budget is admissible
        self.assert_untouched()

    def test_fixture_is_synthetic_and_current_v4_authority_reads_before_adoption(self):
        self.assertTrue(all(e['entry_id'].startswith('00000000-0000-4000-8000-') for e in CP['budget']['entries']))
        self.assertTrue(CP['record2']['transition_reference'].startswith('SYNTHETIC') and CP['record3']['transition_reference'].startswith('SYNTHETIC'))
        self.assertEqual([sha(x) for x in (RECORD1,RECORD2,RECORD3,APPROVAL4,BUDGET)],[ADOPTION1_RECORD_SHA256,
            *(OVERRIDE[k] for k in ('ADOPTION2_RECORD_SHA256','ADOPTION3_RECORD_SHA256','APPROVAL4_SHA256','ADOPTION4_BUDGET_SHA256'))])
        s=self.old_ledger().summary()
        self.assertEqual((s['approval_schema'],s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining'],
            s['adoption4_record_sha256']),('ia-language-approval/4',635,127,127,0,None))
        # The new configuration has no authority at all until record 4 and approval v5 are committed.
        with self.assertRaises(LanguageError):self.ledger().summary()

    def test_adopts_exactly_once_with_zero_headroom_and_preserves_all_127_entries(self):
        out=self.adopt()
        self.assert_history()
        record=self.record4.read_bytes();r=strict_json(record)
        self.assertEqual((r['schema_version'],r['previous_active_config_hash'],r['previous_adoption_record_sha256'],r['active_config_hash'],
            r['catalog_digest'],r['checkpoint']),('ia-language-config-adoption/4',ADOPTION3_ACTIVE_CONFIG_HASH,OVERRIDE['ADOPTION3_RECORD_SHA256'],
            NEW,NEW_CATALOG,dict(CHECKPOINT,budget_sha256=OVERRIDE['ADOPTION4_BUDGET_SHA256'])))
        self.assertEqual({k:r[k] for k in PINS},PINS)
        self.assertEqual(self.approval.read_bytes(),dumps(approval_v5(REF,NEW,sha(record),127)))
        a=strict_json(self.approval.read_bytes())
        self.assertEqual((a['schema_version'],a['adoption_record_sha256'],a['adoption2_record_sha256'],a['adoption3_record_sha256'],
            a['adoption4_record_sha256'],a['max_count_requests'],a['policy_hash'],a['limits_nano_usd']),
            ('ia-language-approval/5',ADOPTION1_RECORD_SHA256,OVERRIDE['ADOPTION2_RECORD_SHA256'],OVERRIDE['ADOPTION3_RECORD_SHA256'],
             sha(record),127,POLICY_HASH,{'test':15000000000,'demo':10000000000}))
        s=self.ledger().summary()
        self.assertEqual(s['config_lineage'],[ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,
            ADOPTION3_ACTIVE_CONFIG_HASH,NEW])
        self.assertEqual([(x['record'],x['sha256'],x['transition_reference']) for x in s['adoption_lineage']],
            [('config-adoption.json',ADOPTION1_RECORD_SHA256,V5['first_adoption_record']['transition_reference']),
             ('config-adoption-2.json',OVERRIDE['ADOPTION2_RECORD_SHA256'],CP['record2']['transition_reference']),
             ('config-adoption-3.json',OVERRIDE['ADOPTION3_RECORD_SHA256'],CP['record3']['transition_reference']),
             ('config-adoption-4.json',sha(record),'root-go-adoption-4')])
        test,demo=s['buckets']['test'],s['buckets']['demo']
        self.assertEqual((s['previous_active_config_hash'],s['active_config_hash'],s['financial_origin_config_hash'],s['ledger_id'],
            s['sequence'],s['count_requests'],s['max_count_requests'],s['count_capacity_remaining'],s['unresolved']),
            (ADOPTION3_ACTIVE_CONFIG_HASH,NEW,ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION_LEDGER_ID,635,127,127,0,False))
        self.assertEqual((test['entries'],test['settled_usage_estimate_nano_usd'],test['held_liability_nano_usd'],test['nonmodel_contingency_nano_usd'],
            test['available_nano_usd'],demo['entries'],demo['available_nano_usd']),
            (127,1101867000,0,2000000000,15000000000-1101867000-2000000000,0,10000000000))
        self.assertEqual((out['provider_calls'],out['ledger_writes'],out['count_capacity_remaining'],out['resumed'],out['entries_preserved']),(0,0,0,False,127))
        for bucket in ('test','demo'):
            with self.assertRaises(LanguageError) as c:self.ledger().reserve(bucket,'sha256:'+'9'*64)
            self.assertEqual(c.exception.code,'count_ceiling_reached')
        self.assert_history()
        # Idempotent re-run after commit: no write, same authority.
        before=(self.approval.read_bytes(),fp(self.approval),record,fp(self.record4))
        self.assertTrue(self.adopt()['resumed']);self.assertEqual((self.approval.read_bytes(),fp(self.approval),self.record4.read_bytes(),fp(self.record4)),before)
        # Old record-3 authority and configuration can no longer read or spend.
        with self.assertRaises(LanguageError):self.old_ledger().summary()

    def test_fixed_pins_and_inputs_refuse_without_writes(self):
        for code,over in (('invalid_max_count_requests',{'max_count_requests':128}),('invalid_max_count_requests',{'max_count_requests':135}),
                          ('invalid_max_count_requests',{'max_count_requests':0}),('invalid_max_count_requests',{'max_count_requests':True}),
                          ('budget_pin_mismatch',{'expected_budget_sha256':'sha256:'+'5'*64}),
                          *((('invalid_pin',{'active_config_hash':h}) for h in (ADOPTION3_ACTIVE_CONFIG_HASH,ADOPTION2_ACTIVE_CONFIG_HASH,
                              ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION_ORIGIN_CONFIG_HASH,'UNKNOWN',None))),
                          ('invalid_pin',{'image_digest':'latest'}),('invalid_pin',{'catalog_digest':'UNKNOWN'}),
                          ('invalid_transition_reference',{'transition_reference':CP['record3']['transition_reference']}),
                          ('invalid_transition_reference',{'transition_reference':' '}),
                          ('root_required' if os.geteuid()!=0 else 'control_ancestor_unprotected',{'protected':True})):
            with self.subTest(code=code,over=over):self.refused(code,**over);self.assert_untouched()

    def test_wrong_records_or_approval_refuse(self):
        for name,data,code in (('config-adoption.json',RECORD1+b' ','first_record_mismatch'),
                               ('config-adoption-2.json',RECORD2.replace(b'SYNTHETIC',b'SYNTHETIX'),'second_record_mismatch'),
                               ('config-adoption-3.json',RECORD3.replace(b'SYNTHETIC',b'SYNTHETIX'),'third_record_mismatch'),
                               ('approval.json',dumps(dict(CP['approval4'],max_count_requests=7)),'approval_not_reviewed_third_transition'),
                               ('approval.json',dumps(dict(CP['approval4'],max_count_requests=128)),'approval_not_reviewed_third_transition'),
                               ('approval.json',dumps(dict(CP['approval4'],config_hash=NEW)),'approval_not_reviewed_third_transition')):
            with self.subTest(name=name,code=code):
                old=(self.root/name).read_bytes();put(self.root/name,data);self.refused(code);put(self.root/name,old)
                self.assertFalse(self.record4.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL4);self.assertFalse(self.halted.exists())

    def test_ledger_counter_uuid_and_stamp_mismatches_refuse_before_publish(self):
        def mutate(f):
            b=copy.deepcopy(CP['budget']);f(b);return dumps(b)
        def seq(b):b['sequence']=636
        def held(b):b['entries'][-1].update(state='dispatched')
        def released(b):b['entries'][-1].update(state='released')
        def uuid(b):b['ledger_id']='00000000-0000-4000-8000-000000000000'
        def stamp(b):b['entries'][-1]['config_hash']=ADOPTION2_ACTIVE_CONFIG_HASH
        def moved(b):b['entries'][6]['config_hash']=ADOPTION3_ACTIVE_CONFIG_HASH
        def unstamped(b):del b['entries'][50]['config_hash']
        def dropped(b):del b['entries'][60]
        def extra(b):b['entries'].append(dict(b['entries'][-1],sequence=636,entry_id='x'));b['sequence']=640
        def settled(b):b['entries'][-1]['settled_estimate_nano_usd']+=1
        def shifted(b):b['entries'][10]['settled_estimate_nano_usd']+=1;b['entries'][11]['settled_estimate_nano_usd']-=1  # same total, still exact-pin refused
        def reset(b):b['entries']=[];b['sequence']=0
        cases=(('seq',seq,'ledger_checkpoint_mismatch'),('held',held,'ledger_checkpoint_mismatch'),('released',released,'ledger_checkpoint_mismatch'),
               ('uuid',uuid,'ledger_identity_mismatch'),('stamp',stamp,'ledger_checkpoint_mismatch'),('moved',moved,'ledger_checkpoint_mismatch'),
               ('unstamped',unstamped,'ledger_checkpoint_mismatch'),('dropped',dropped,'ledger_checkpoint_mismatch'),
               ('extra',extra,'ledger_checkpoint_mismatch'),('settled',settled,'ledger_checkpoint_mismatch'),('shifted',shifted,None),
               ('reset',reset,'ledger_checkpoint_mismatch'))
        for name,f,code in cases:
            with self.subTest(name=name):
                data=mutate(f);put(self.budget,data)
                self.refused('budget_pin_mismatch')  # the exact budget pin refuses first, for every mutation
                if code is not None:
                    with patch.object(acc,'ADOPTION4_BUDGET_SHA256',sha(data)):self.refused(code,expected_budget_sha256=sha(data))
                self.assertFalse(self.record4.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL4);self.assertFalse(self.halted.exists())
        put(self.budget,BUDGET)

    def test_conflicts_halt_marker_locks_and_missing_ledger(self):
        put(self.record4,b'{}');self.refused('adoption_conflict');self.record4.unlink()
        put(self.approval,dumps(approval_v5(REF,NEW,'sha256:'+'6'*64,127)));self.refused('adoption_conflict');put(self.approval,APPROVAL4)
        self.halted.write_bytes(b'');self.refused('accounting_halted');self.halted.unlink()
        for lock in ('job.lock','budget.lock'):
            fd=os.open(self.root/'ledger'/lock,os.O_RDWR)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.refused('busy')
            finally:os.close(fd)
        self.assert_untouched()
        self.budget.unlink()
        with self.assertRaises((helper.AdoptionError,OSError,LanguageError)):self.adopt()
        self.assertFalse(self.budget.exists());self.assertFalse(self.record4.exists())

    def test_io_failure_after_record_publish_halts_and_fails_closed(self):
        with patch.object(helper,'_publish_atomic',side_effect=OSError('disk')):self.refused('adoption_commit_uncertain_halted')
        self.assertTrue(self.halted.exists());self.assertTrue(self.record4.exists());self.assertEqual(self.approval.read_bytes(),APPROVAL4)
        self.assert_history()
        # Staged record 4 disables the v4 authority; the new config has no v5 approval; nothing initializes; no retry path.
        for ledger in (self.old_ledger(),self.ledger()):
            with self.assertRaises(LanguageError):ledger.summary()
        self.refused('accounting_halted')
        with patch.object(helper,'_publish_exclusive',side_effect=OSError('disk')):
            self.record4.unlink();self.halted.unlink();self.refused('adoption_commit_uncertain_halted')
        self.assertFalse(self.record4.exists());self.assertTrue(self.halted.exists());self.assert_history()

    def test_unconfirmed_halt_marker_is_reported_distinctly_and_state_left_for_inspection(self):
        def fault(*_a,**_k):self.uncreatable_marker();raise OSError('approval storage fault')
        with patch.object(helper,'_publish_atomic',side_effect=fault):self.refused('adoption_commit_uncertain_halt_unconfirmed')
        self.assertFalse(self.halted.exists());self.assertTrue(self.record4.exists())
        self.assertEqual(self.approval.read_bytes(),APPROVAL4);self.assert_history()

    def test_fault_after_approval_commit_halts_or_reports_unconfirmed(self):
        def failing(ledger):raise LanguageError('ledger_unavailable',503)
        with patch.object(acc.BudgetLedger,'_read',failing):self.refused('adoption_commit_uncertain_halted')
        self.assertTrue(self.halted.exists())
        self.assertEqual(strict_json(self.approval.read_bytes())['schema_version'],'ia-language-approval/5')  # partial state left as found
        self.assertTrue(self.record4.exists());self.assert_history()
        with self.assertRaises(LanguageError) as c:self.ledger().reserve('test','sha256:'+'9'*64)  # shared marker blocks the runtime
        self.assertEqual(c.exception.code,'accounting_halted')
        self.tearDown();self.setUp()
        def failing2(ledger):self.uncreatable_marker();raise LanguageError('ledger_unavailable',503)
        with patch.object(acc.BudgetLedger,'_read',failing2):self.refused('adoption_commit_uncertain_halt_unconfirmed')
        self.assertFalse(self.halted.exists());self.assertEqual(strict_json(self.approval.read_bytes())['schema_version'],'ia-language-approval/5')
        self.assert_history()

    def test_cli_exit_codes_0_2_3(self):
        real=helper.adopt4
        argv=lambda:['--control-dir',str(self.root),'--active-config-hash',NEW,'--catalog-digest',NEW_CATALOG,'--transition-reference','root-go-adoption-4',
            '--source-component-sha256',PINS['source_component_sha256'],'--image-digest',PINS['image_digest'],'--review-receipt-sha256',PINS['review_receipt_sha256'],
            '--expected-budget-sha256',OVERRIDE['ADOPTION4_BUDGET_SHA256'],'--max-count-requests','127']
        def run(unprotected=True):
            buf=io.StringIO()
            target=(lambda *a,**k:real(*a,**dict(k,protected=False))) if unprotected else real
            with patch.object(helper,'adopt4',target),redirect_stdout(buf):code=helper.main(argv())
            return code,json.loads(buf.getvalue())
        code,out=run(unprotected=False)  # the real CLI is always protected: refusal before any read of financial state
        self.assertEqual((code,out['status'],out['provider_calls']),(2,'refused',0));self.assertIn(out['code'],('root_required','control_ancestor_unprotected'))
        self.assert_untouched()
        with patch.object(helper,'_publish_atomic',side_effect=OSError('fault')):code,out=run()
        self.assertEqual((code,out['status'],out['code'],out['inspect_control_state']),(3,'commit_uncertain','adoption_commit_uncertain_halted',True))
        self.assertTrue(self.halted.exists())
        code,out=run()  # halted: ordinary pre-write refusal, never a repair
        self.assertEqual((code,out['status'],out['code']),(2,'refused','accounting_halted'))
        self.halted.unlink();self.record4.unlink()
        def fault(*_a,**_k):self.uncreatable_marker();raise OSError('fault')
        with patch.object(helper,'_publish_atomic',side_effect=fault):code,out=run()
        self.assertEqual((code,out['status'],out['code']),(3,'commit_uncertain','adoption_commit_uncertain_halt_unconfirmed'))
        self.tearDown();self.setUp()
        code,out=run()
        self.assertEqual((code,out['status'],out['count_capacity_remaining'],out['ledger_writes']),(0,'adopted',0,0))

    def test_runtime_v5_lineage_positions_and_no_reinitialization(self):
        self.adopt();base=copy.deepcopy(CP['budget'])
        def entry(stamp,seq):
            e={'entry_id':'e-new','sequence':seq,'bucket':'test','state':'reserved','created_at':1.0,'reserved_nano_usd':reservation(),
                'settled_estimate_nano_usd':None,'payload_hash':'sha256:'+'9'*64,'counted_input_tokens':None,
                'count_requests':0,'model_calls':0,'usage':None,'terminal_code':None}
            if stamp is not None:e['config_hash']=stamp
            return e
        for stamp,seq,ok in ((NEW,636,True),(ADOPTION3_ACTIVE_CONFIG_HASH,636,False),(ADOPTION2_ACTIVE_CONFIG_HASH,636,False),
                             (ADOPTION1_ACTIVE_CONFIG_HASH,636,False),(ADOPTION_ORIGIN_CONFIG_HASH,636,False),(None,636,False),
                             (NEW,635,False),(NEW,36,False),('sha256:'+'7'*64,636,False)):
            with self.subTest(stamp=str(stamp)[:15],seq=seq):
                b=copy.deepcopy(base);b['entries'].append(entry(stamp,seq));b['sequence']=max(seq,635);put(self.budget,dumps(b))
                if ok:self.assertTrue(self.ledger().summary()['unresolved'])
                else:
                    with self.assertRaises(LanguageError) as c:self.ledger().summary()
                    self.assertEqual(c.exception.code,'ledger_unavailable')
        # A preserved entry restamped across a historical boundary is rejected by the runtime parser.
        for index,stamp in ((0,ADOPTION1_ACTIVE_CONFIG_HASH),(3,ADOPTION2_ACTIVE_CONFIG_HASH),(6,ADOPTION3_ACTIVE_CONFIG_HASH),(7,ADOPTION2_ACTIVE_CONFIG_HASH),(126,NEW)):
            with self.subTest(index=index):
                b=copy.deepcopy(base);b['entries'][index]['config_hash']=stamp;put(self.budget,dumps(b))
                with self.assertRaises(LanguageError):self.ledger().summary()
        put(self.budget,BUDGET)
        with self.assertRaises(LanguageError):self.ledger().initialize(REF)
        self.budget.unlink()
        with self.assertRaises(LanguageError) as c:self.ledger().initialize(REF)
        self.assertEqual(c.exception.code,'ledger_initialization_forbidden');self.assertFalse(self.budget.exists())

    def test_staged_or_committed_record4_disables_every_earlier_authority(self):
        self.record4.write_bytes(b'{}')
        l=self.ledger(ADOPTION_ORIGIN_CONFIG_HASH,ADOPTION_HISTORICAL_CATALOG_DIGEST)
        put(self.approval,dumps(l.approval_template(REF)))
        with self.assertRaises(LanguageError):l.approval()
        put(self.approval,dumps(acc.approval_v2(REF,ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION1_RECORD_SHA256,6)))
        with self.assertRaises(LanguageError):self.ledger(ADOPTION1_ACTIVE_CONFIG_HASH,ADOPTION_HISTORICAL_CATALOG_DIGEST).approval()
        put(self.approval,dumps(acc.approval_v3(REF,ADOPTION2_ACTIVE_CONFIG_HASH,acc.ADOPTION2_RECORD_SHA256,7)))
        with self.assertRaises(LanguageError):self.ledger(ADOPTION2_ACTIVE_CONFIG_HASH,ADOPTION_HISTORICAL_CATALOG_DIGEST).approval()
        put(self.approval,APPROVAL4)
        with self.assertRaises(LanguageError):self.old_ledger().approval()
        self.record4.unlink();self.assertEqual(self.old_ledger().approval()['schema_version'],'ia-language-approval/4')

    def test_v5_authority_requires_exact_historical_pins_and_running_catalog(self):
        self.adopt();good=strict_json(self.approval.read_bytes())
        self.assertEqual(self.ledger().approval()['schema_version'],'ia-language-approval/5')
        with self.assertRaises(LanguageError):self.ledger(catalog=ADOPTION_HISTORICAL_CATALOG_DIGEST).approval()  # record 4 binds the running catalog
        with self.assertRaises(LanguageError):self.ledger('sha256:'+'7'*64).approval()
        for key in ('adoption_record_sha256','adoption2_record_sha256','adoption3_record_sha256','adoption4_record_sha256'):
            with self.subTest(key=key):
                put(self.approval,dumps(dict(good,**{key:'sha256:'+'0'*64})))
                with self.assertRaises(LanguageError):self.ledger().approval()
        for bad in (dict(good,max_count_requests=257),dict(good,max_count_requests=0),dict(good,stage='qualification'),
                    {k:v for k,v in good.items() if k!='adoption4_record_sha256'},dict(good,extra=1),
                    dict(good,limits_nano_usd={'test':15000000001,'demo':10000000000})):
            put(self.approval,dumps(bad))
            with self.assertRaises(LanguageError):self.ledger().approval()

if __name__=='__main__':unittest.main()
